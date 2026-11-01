"""
Grab — one local app to download MP4 / MP3 from YouTube, X/Twitter, Instagram,
TikTok, Reddit, Vimeo, SoundCloud and ~1,000 other sites supported by yt-dlp.

Setup (once):
    pip install flask yt-dlp
    install ffmpeg  (Windows: winget install ffmpeg | macOS: brew install ffmpeg | Linux: apt install ffmpeg)

Run:
    python app.py        then open http://localhost:5000

Optional: Instagram / X often need you to be logged in. Set COOKIES_BROWSER to
the browser you're logged in with (chrome, firefox, edge, brave, safari):
    COOKIES_BROWSER=chrome python app.py      (Windows: set COOKIES_BROWSER=chrome)

Keep yt-dlp current — sites change often:  pip install -U yt-dlp
"""
import os
import re
import secrets
import shutil
import tempfile

from flask import Flask, Response, jsonify, request, send_file
import yt_dlp

app = Flask(__name__)

# Optional password when hosted online: set APP_PASSWORD (username can be anything)
APP_PASSWORD = os.environ.get("APP_PASSWORD")


@app.before_request
def require_password():
    if not APP_PASSWORD:
        return None
    auth = request.authorization
    if not auth or not secrets.compare_digest(auth.password or "", APP_PASSWORD):
        return Response("Password required", 401, {"WWW-Authenticate": 'Basic realm="Grab"'})
    return None

DRM_SERVICES = ("open.spotify.com", "spotify.link", "music.apple.com",
                "music.amazon.", "amazon.com/music", "tidal.com", "deezer.com")


def base_opts():
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    cookie_file = os.environ.get("COOKIES_FILE")
    if cookie_file and os.path.exists(cookie_file):
        # yt-dlp writes back to the cookie file, so use a writable copy
        tmp_cookies = os.path.join(tempfile.gettempdir(), "grab_cookies.txt")
        if not os.path.exists(tmp_cookies):
            shutil.copy(cookie_file, tmp_cookies)
        opts["cookiefile"] = tmp_cookies
    browser = os.environ.get("COOKIES_BROWSER")
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def check_url(url):
    if not re.match(r"^https?://\S+$", url or ""):
        return "Paste a full link starting with http:// or https://"
    if any(s in url.lower() for s in DRM_SERVICES):
        return "That service uses DRM-protected audio, so it isn't supported."
    return None


def clean_error(e):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    if "login" in msg.lower() or "cookies" in msg.lower():
        msg += "  (Tip: run with COOKIES_BROWSER=chrome — see top of app.py)"
    return msg[:400]


@app.post("/api/info")
def info():
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    err = check_url(url)
    if err:
        return jsonify(error=err), 400
    try:
        with yt_dlp.YoutubeDL({**base_opts(), "skip_download": True}) as ydl:
            i = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify(error=clean_error(e)), 400

    if i.get("_type") == "playlist":
        entries = [e for e in (i.get("entries") or []) if e]
        if not entries:
            return jsonify(error="No downloadable media found at that link."), 400
        i = entries[0]

    heights = sorted({f["height"] for f in i.get("formats") or []
                      if f.get("height") and f.get("vcodec") not in (None, "none")},
                     reverse=True)
    return jsonify(
        title=i.get("title") or "Untitled",
        uploader=i.get("uploader") or i.get("channel") or "",
        duration=i.get("duration"),
        thumbnail=i.get("thumbnail"),
        site=i.get("extractor_key") or "",
        heights=heights,
    )


@app.get("/api/download")
def download():
    url = request.args.get("url", "").strip()
    kind = request.args.get("kind", "mp4")
    q = request.args.get("q", "best")
    err = check_url(url)
    if err:
        return Response(err, status=400)

    tmp = tempfile.mkdtemp(prefix="grab_")
    opts = {**base_opts(), "outtmpl": os.path.join(tmp, "%(title).120B.%(ext)s"),
            "restrictfilenames": False}

    if kind == "mp3":
        kbps = q if q in ("128", "192", "256", "320") else "320"
        opts.update(format="bestaudio/best", postprocessors=[
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": kbps},
            {"key": "FFmpegMetadata"},
        ])
    else:
        h = f"[height<={int(q)}]" if q.isdigit() else ""
        opts.update(
            format=(f"bv*{h}[ext=mp4]+ba[ext=m4a]/bv*{h}+ba/b{h}[ext=mp4]/b{h}/b"),
            merge_output_format="mp4",
            postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = [os.path.join(tmp, f) for f in os.listdir(tmp)]
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            raise RuntimeError("Download produced no file.")
        path = max(files, key=os.path.getsize)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return Response(clean_error(e), status=400)

    resp = send_file(path, as_attachment=True, download_name=os.path.basename(path))
    resp.call_on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
    return resp


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grab</title>
<style>
:root{--bg:#0e0f13;--card:#171920;--line:#262934;--text:#eceef3;--mute:#8b90a0;--acc:#7c5cff;--acc2:#a48bff;--err:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;display:flex;justify-content:center;padding:48px 16px}
main{width:100%;max-width:640px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}h1 span{color:var(--acc2)}
.sub{color:var(--mute);margin:0 0 28px}
.bar{display:flex;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px}
.bar input{flex:1;min-width:0;background:none;border:0;color:var(--text);font:inherit;padding:10px 12px;outline:none}
button{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:10px 18px;font:600 15px system-ui;cursor:pointer}
button:hover{background:var(--acc2)}button:disabled{opacity:.5;cursor:default}
.ghost{background:none;color:var(--mute);padding:10px 12px}.ghost:hover{background:var(--line);color:var(--text)}
.msg{margin-top:14px;color:var(--mute);min-height:22px}.msg.err{color:var(--err)}
.card{display:none;margin-top:20px;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.media{display:flex;gap:14px;padding:14px}
.media img{width:160px;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:var(--line);flex-shrink:0}
.media h2{font-size:16px;margin:0 0 4px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.meta{color:var(--mute);font-size:13px}
.opts{border-top:1px solid var(--line);padding:14px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.seg{display:flex;background:var(--bg);border-radius:10px;padding:3px}
.seg label{padding:7px 16px;border-radius:8px;cursor:pointer;color:var(--mute);font-weight:600}
.seg input{display:none}.seg input:checked+label{background:var(--line);color:var(--text)}
select{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:9px 10px;font:inherit}
.opts button{margin-left:auto}
.sites{margin-top:28px;color:var(--mute);font-size:13px}
@media(max-width:520px){.media{flex-direction:column}.media img{width:100%}.opts button{margin-left:0;width:100%}}
</style></head><body><main>
<h1>Grab<span>.</span></h1>
<p class="sub">Paste a link, pick a format and quality, download.</p>
<form class="bar" id="f">
  <input id="url" placeholder="https://youtube.com/watch?v=…" autocomplete="off" autofocus>
  <button type="button" class="ghost" id="paste">Paste</button>
  <button id="go">Fetch</button>
</form>
<div class="msg" id="msg"></div>
<div class="card" id="card">
  <div class="media"><img id="thumb" alt=""><div><h2 id="title"></h2><div class="meta" id="meta"></div></div></div>
  <div class="opts">
    <div class="seg">
      <input type="radio" name="kind" id="k4" value="mp4" checked><label for="k4">MP4</label>
      <input type="radio" name="kind" id="k3" value="mp3"><label for="k3">MP3</label>
    </div>
    <select id="q"></select>
    <button id="dl">Download</button>
  </div>
</div>
<p class="sites">Works with YouTube, X/Twitter, Instagram, TikTok, Reddit, Facebook, Vimeo, SoundCloud, Twitch clips and more.
Spotify, Apple Music and Amazon Music are DRM-protected and not supported.</p>
</main>
<script>
const $=id=>document.getElementById(id);let cur=null;
const say=(t,err)=>{$('msg').textContent=t;$('msg').className='msg'+(err?' err':'')};
const fmt=s=>{if(!s)return'';s=Math.round(s);const h=s/3600|0,m=(s%3600)/60|0,x=String(s%60).padStart(2,'0');return h?`${h}:${String(m).padStart(2,'0')}:${x}`:`${m}:${x}`};
function fillQ(){
  const kind=document.querySelector('[name=kind]:checked').value,q=$('q');q.innerHTML='';
  const opts=kind==='mp3'?[['320','320 kbps'],['256','256 kbps'],['192','192 kbps'],['128','128 kbps']]
    :[['best','Best available'],...(cur.heights||[]).map(h=>[h,h>=2160?'4K (2160p)':h>=1440?'1440p':h+'p'])];
  opts.forEach(([v,t])=>q.add(new Option(t,v)));
}
$('paste').onclick=async()=>{try{$('url').value=await navigator.clipboard.readText();$('f').requestSubmit()}catch{$('url').focus()}};
$('f').onsubmit=async e=>{
  e.preventDefault();const url=$('url').value.trim();if(!url)return;
  $('go').disabled=true;$('card').style.display='none';say('Looking up link…');
  try{
    const r=await fetch('/api/info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    const d=await r.json();if(!r.ok)throw new Error(d.error||'Lookup failed');
    cur={...d,url};$('title').textContent=d.title;
    $('meta').textContent=[d.site,d.uploader,fmt(d.duration)].filter(Boolean).join(' · ');
    $('thumb').src=d.thumbnail||'';$('thumb').style.display=d.thumbnail?'':'none';
    if(!d.heights.length)$('k3').checked=true;
    $('k4').disabled=!d.heights.length;fillQ();$('card').style.display='block';say('');
  }catch(err){say(err.message,true)}finally{$('go').disabled=false}
};
document.querySelectorAll('[name=kind]').forEach(r=>r.onchange=fillQ);
$('dl').onclick=async()=>{
  const kind=document.querySelector('[name=kind]:checked').value,q=$('q').value;
  const u=`/api/download?url=${encodeURIComponent(cur.url)}&kind=${kind}&q=${q}`;
  $('dl').disabled=true;say('Preparing your file — this can take a minute for long videos…');
  try{
    const r=await fetch(u);if(!r.ok)throw new Error(await r.text());
    const name=decodeURIComponent((r.headers.get('Content-Disposition')||'').match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i)?.[1]||'download.'+kind);
    const blob=await r.blob(),a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);
    say('Done ✓ — saved '+name);
  }catch(err){say(err.message,true)}finally{$('dl').disabled=false}
};
</script></body></html>"""

if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        print("⚠  ffmpeg not found — MP3 conversion and HD video merging won't work until it's installed.")
    port = int(os.environ.get("PORT", 5000))
    print(f"Grab running → http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, threaded=True)
