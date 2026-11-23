import os
from bson.binary import Binary
import certifi
from flask import Blueprint, Response, jsonify, render_template_string, request
from pymongo import MongoClient
from synth import PRESETS, insert_at_timestamp, samples_to_wav_bytes, stretch_samples, wav_bytes_to_samples

# Define as a Blueprint mounted at /studio
music_bp = Blueprint("music", __name__, url_prefix="/studio")

MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(
    MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000
)
tracks_col = client["music_studio_db"]["audio_tracks"]


def send_wav(data):
  res = Response(data, mimetype="audio/wav")
  res.headers.update({
      "Content-Length": str(len(data)),
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-cache",
  })
  return res


# Note: All fetch/stream URLs inside HTML now use /studio/...
HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://jsdelivr.net"></script>
<style>
body{font-family:sans-serif;background:#121212;color:#eee;max-width:600px;margin:auto;padding:14px}
.card{background:#1e1e1e;padding:12px;border-radius:8px;margin-bottom:12px}
.row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #2c2c2c;gap:6px}
button{background:#1db954;color:#000;border:none;padding:6px 9px;border-radius:5px;font-weight:bold;font-size:12px}
button.sec{background:#333;color:#fff} button.on{background:#ff9800;color:#000}
input,select{padding:7px;border-radius:5px;border:1px solid #444;background:#222;color:#fff;margin-top:4px}
audio{width:100%;margin-top:8px}
canvas{width:100%;height:95px;background:#0a0a0a;border-radius:6px;margin-top:8px;border:1px solid #2a2a2a;display:block}
</style></head><body>
<div style="display:flex;justify-content:space-between;align-items:center">
  <h3 style="color:#1db954">MongoDB Music Studio</h3>
  <a href="/" style="color:#aaa;font-size:13px">⬅ Back Home</a>
</div>
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong id="np">Ready</strong>
    <div>
      <button class="sec" onclick="visMode=(visMode+1)%2;this.innerText=visMode?'〰 Wave':'📊 Bars'">📊 Bars</button>
      <button id="lbtn" class="sec" onclick="toggleLoop()">🔁 OFF</button>
    </div>
  </div>
  <canvas id="vis" width="540" height="95"></canvas>
  <audio id="p" controls playsinline crossorigin="anonymous"></audio>
  <div style="margin-top:6px;font-size:12px">Stretch: <input type="range" min="0.5" max="1.5" step="0.05" value="1" oninput="p.playbackRate=this.value;sv.innerText=this.value+'x'"> <b id="sv">1x</b></div>
</div>
<div class="card"><b>Tracks</b>
  {% for t in tracks %}<div class="row">
    <label style="flex:1"><input type="checkbox" class="cb" value="{{t.name}}"> {{t.name}} <small style="color:#888">({{t.type}})</small></label>
    <div>
      <button onclick="playOne('{{t.name}}')">▶</button>
      <button class="sec" onclick="q.push('{{t.name}}');sq.innerText=q.join(' ➔ ')">+Ser</button>
      <button class="sec" onclick="exportMp3('{{t.name}}')">⬇MP3</button>
    </div>
  </div>{% endfor %}
</div>
<div class="card"><b>Paste / Insert in Timeline</b><br>
  Base: <select id="tb">{% for t in tracks %}<option value="{{t.name}}">{{t.name}}</option>{% endfor %}</select>
  Clip: <select id="tc">{% for t in tracks %}<option value="{{t.name}}">{{t.name}}</option>{% endfor %}</select><br>
  At (sec): <input type="number" id="ts" value="1.5" step="0.1" style="width:65px">
  <select id="tm"><option value="insert">Insert (Push)</option><option value="overlay">Overlay (Mix)</option></select>
  <input type="text" id="tn" placeholder="New track name" style="width:120px">
  <button onclick="splice()">Paste & Save</button>
</div>
<div class="card"><b>Stretch & Mix</b><br>
  <select id="ss">{% for t in tracks %}<option value="{{t.name}}">{{t.name}}</option>{% endfor %}</select>
  <select id="sf"><option value="1.25">1.25x</option><option value="1.5" selected>1.5x</option></select>
  <button onclick="post('/studio/stretch',{source:ss.value,factor:sf.value})">Stretch</button><br>
  <input type="text" id="mn" placeholder="Mix checked tracks name"> <button onclick="mix()">Mix & Save</button>
</div>
<div class="card"><b>Series</b><p id="sq" style="color:#aaa;font-size:12px">Empty</p>
  <button onclick="playSer(false)">▶ Once</button> <button class="on" onclick="playSer(true)">🔁 Loop</button> <button class="sec" onclick="q=[];sq.innerText='Empty'">Clear</button>
</div>
<script>
let q=[],lp=false,ctx,analyser,dataArr,visMode=0;
const cvs=document.getElementById('vis'),c=cvs.getContext('2d');
function initVis(){if(ctx)return;ctx=new(window.AudioContext||window.webkitAudioContext)();analyser=ctx.createAnalyser();analyser.fftSize=128;ctx.createMediaElementSource(p).connect(analyser);analyser.connect(ctx.destination);dataArr=new Uint8Array(analyser.frequencyBinCount);draw();}
function draw(){requestAnimationFrame(draw);c.fillStyle='#0a0a0a';c.fillRect(0,0,cvs.width,cvs.height);if(visMode===0){analyser.getByteFrequencyData(dataArr);let bw=(cvs.width/dataArr.length)*1.4;dataArr.forEach((v,i)=>{let h=(v/255)*cvs.height;c.fillStyle=`hsl(${135-(v/255)*80},80%,50%)`;c.fillRect(i*(bw+2),cvs.height-h,bw,h);});}else{analyser.getByteTimeDomainData(dataArr);c.strokeStyle='#1db954';c.lineWidth=2;c.beginPath();dataArr.forEach((v,i)=>{let x=i*(cvs.width/dataArr.length),y=(v/128)*(cvs.height/2);i===0?c.moveTo(x,y):c.lineTo(x,y);});c.stroke();}}
function toggleLoop(){lp=!lp;p.loop=lp;lbtn.innerText=lp?'🔁 ON':'🔁 OFF';lbtn.className=lp?'on':'sec';}
function playOne(n){initVis();if(ctx.state==='suspended')ctx.resume();np.innerText='Playing: '+n;p.src='/studio/stream/'+encodeURIComponent(n)+'?t='+Date.now();p.play();}
function playSer(l){if(!q.length)return alert('Add tracks');initVis();if(ctx.state==='suspended')ctx.resume();if(lp!==l)toggleLoop();np.innerText='Series: '+q.join(' ➔ ');p.src='/studio/series?t='+encodeURIComponent(q.join(','))+'&d='+Date.now();p.play();}
async function post(u,b){let r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});if(r.ok)location.reload();}
function mix(){let c=[...document.querySelectorAll('.cb:checked')].map(x=>x.value);if(c.length<2||!mn.value)return alert('Pick 2+ & name');post('/studio/mix',{tracks:c,name:mn.value});}
function splice(){if(!tn.value)return alert('Enter new track name');post('/studio/splice',{base:tb.value,clip:tc.value,sec:ts.value,mode:tm.value,name:tn.value});}
async function exportMp3(name){
  np.innerText='Encoding MP3: '+name+'...';
  const buf=await(await fetch('/studio/stream/'+encodeURIComponent(name))).arrayBuffer();
  const samples=new Int16Array(buf,44);
  const enc=new lamejs.Mp3Encoder(1,44100,128),mp3=[];
  for(let i=0;i<samples.length;i+=1152){let b=enc.encodeBuffer(samples.subarray(i,i+1152));if(b.length)mp3.push(b);}
  let end=enc.flush();if(end.length)mp3.push(end);
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(mp3,{type:'audio/mp3'}));a.download=name+'.mp3';a.click();
  np.innerText='Downloaded '+name+'.mp3';
}
</script></body></html>"""


@music_bp.route("/")
def index():
  for k, fn in PRESETS.items():
    if not tracks_col.find_one({"name": k}, {"_id": 1}):
      tracks_col.insert_one(
          {"name": k, "audio_data": Binary(fn()), "type": "preset"}
      )
  return render_template_string(
      HTML, tracks=list(tracks_col.find({}, {"name": 1, "type": 1, "_id": 0}))
  )


@music_bp.route("/stream/<name>")
def stream(name):
  d = tracks_col.find_one({"name": name})
  return send_wav(bytes(d["audio_data"])) if d else ("Not found", 404)


@music_bp.route("/series")
def series():
  out = []
  for n in request.args.get("t", "").split(","):
    d = tracks_col.find_one({"name": n.strip()})
    if d:
      out.extend(wav_bytes_to_samples(d["audio_data"]))
  return send_wav(samples_to_wav_bytes(out)) if out else ("Empty", 404)


@music_bp.route("/splice", methods=["POST"])
def splice():
  b = request.json
  base = wav_bytes_to_samples(
      tracks_col.find_one({"name": b["base"]})["audio_data"]
  )
  clip = wav_bytes_to_samples(
      tracks_col.find_one({"name": b["clip"]})["audio_data"]
  )
  res = insert_at_timestamp(base, clip, float(b["sec"]), b["mode"])
  tracks_col.update_one(
      {"name": b["name"]},
      {
          "$set": {
              "name": b["name"],
              "audio_data": Binary(samples_to_wav_bytes(res)),
              "type": "spliced",
          }
      },
      upsert=True,
  )
  return jsonify({"ok": True})


@music_bp.route("/stretch", methods=["POST"])
def stretch():
  b = request.json
  d = tracks_col.find_one({"name": b["source"]})
  f = float(b["factor"])
  res = stretch_samples(wav_bytes_to_samples(d["audio_data"]), f)
  name = f"{b['source']}_x{f}".replace(".", "_")
  tracks_col.update_one(
      {"name": name},
      {
          "$set": {
              "name": name,
              "audio_data": Binary(samples_to_wav_bytes(res)),
              "type": "stretched",
          }
      },
      upsert=True,
  )
  return jsonify({"ok": True})


@music_bp.route("/mix", methods=["POST"])
def mix():
  b = request.json
  lists = [
      wav_bytes_to_samples(tracks_col.find_one({"name": n})["audio_data"])
      for n in b["tracks"]
  ]
  m = [
      int(sum(s[i] for s in lists if i < len(s)) * 0.65)
      for i in range(max(len(s) for s in lists))
  ]
  tracks_col.update_one(
      {"name": b["name"]},
      {
          "$set": {
              "name": b["name"],
              "audio_data": Binary(samples_to_wav_bytes(m)),
              "type": "mix",
          }
      },
      upsert=True,
  )
  return jsonify({"ok": True})
