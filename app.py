#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py —— 「上传 PDF → 高亮跟读视频」网页服务
启动： 双击 启动.bat   或   python app.py
默认端口 8756；绑定 0.0.0.0，同一 WiFi 的手机也能打开。
"""
import asyncio
import json
import os
import shutil
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
import uvicorn

import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'jobs')
os.makedirs(WORK, exist_ok=True)
PORT = 8756

app = FastAPI(title='PDF → 高亮跟读视频')
JOBS = {}

# 常用中文音色（可在界面里切换；★ 为推荐）
VOICES = [
    ('zh-CN-YunxiNeural', '云希 · 男声 · 年轻自然 ★'),
    ('zh-CN-XiaoxiaoNeural', '晓晓 · 女声 · 亲和 ★'),
    ('zh-CN-YunyangNeural', '云扬 · 男声 · 播报感'),
    ('zh-CN-YunjianNeural', '云健 · 男声 · 沉稳'),
    ('zh-CN-YunxiaNeural', '云夏 · 男声 · 少年'),
    ('zh-CN-XiaoyiNeural', '晓伊 · 女声 · 活泼'),
    ('zh-CN-liaoning-XiaobeiNeural', '晓北 · 女声 · 东北口音'),
    ('zh-CN-shaanxi-XiaoniNeural', '晓妮 · 女声 · 陕西口音'),
    ('zh-HK-HiuMaanNeural', '曉曼 · 女声 · 粤语'),
    ('zh-TW-HsiaoChenNeural', '曉臻 · 女声 · 台湾'),
]

SAMPLE = '打标签这件事，核心是把模糊的业务概念，变成可重复的判断。所以真正难的不是标注本身，而是先把定义说清楚。'


def _voices_list():
    got = []
    try:
        import edge_tts
        al = asyncio.run(edge_tts.list_voices())
        zh = [v for v in al if str(v.get('Locale', '')).startswith('zh')]
        for v in zh:
            got.append({'id': v['ShortName'], 'label': '%s · %s' % (
                v['ShortName'].split('-')[-1].replace('Neural', ''),
                v.get('Gender', '') + ' ' + v.get('Locale', ''))})
    except Exception:
        pass
    return got


CURATED = [{'id': i, 'label': l} for i, l in VOICES]


@app.get('/', response_class=HTMLResponse)
def index():
    # 音色直接由服务端渲染进页面：不依赖前端异步请求（避免打开瞬间下拉是空的）
    opts = ''.join('<option value="%s">%s</option>' % (i, l) for i, l in VOICES)
    return HTMLResponse(HTML.replace('<!--VOICES-->', opts))


@app.get('/api/voices')
def api_voices():
    extra = [v for v in _voices_list() if v['id'] not in {c['id'] for c in CURATED}]
    return JSONResponse({'recommended': CURATED, 'all': CURATED + extra, 'sample': SAMPLE})


@app.post('/api/preview')
async def api_preview(payload: dict):
    voice = payload.get('voice', 'zh-CN-YunxiNeural')
    rate = payload.get('rate', '+0%')
    text = (payload.get('text') or SAMPLE)[:180]
    import edge_tts
    tmp = os.path.join(WORK, '_preview_%s.mp3' % uuid.uuid4().hex[:8])
    try:
        await asyncio.wait_for(
            edge_tts.Communicate(text, voice, rate=rate, connect_timeout=12, receive_timeout=30).save(tmp),
            timeout=30)
        data = open(tmp, 'rb').read()
        os.remove(tmp)
        return Response(content=data, media_type='audio/mpeg')
    except Exception as e:
        return JSONResponse({'error': '试听失败：%s' % e}, status_code=500)


@app.post('/api/upload')
async def api_upload(file: UploadFile = File(...), voice: str = Form('zh-CN-YunxiNeural'),
                     rate: str = Form('+0%'), max_minutes: float = Form(9.5)):
    jid = uuid.uuid4().hex[:10]
    jd = os.path.join(WORK, jid)
    os.makedirs(jd, exist_ok=True)
    name = os.path.basename(file.filename or 'upload.pdf')
    src = os.path.join(jd, name)
    with open(src, 'wb') as fh:
        shutil.copyfileobj(file.file, fh)
    JOBS[jid] = {'id': jid, 'file': name, 'voice': voice, 'rate': rate,
                 'stage': '排队中', 'percent': 1, 'done': False, 'error': None,
                 'result': None, 'started': time.time()}

    def prog(msg, pct=None):
        JOBS[jid]['stage'] = msg
        if pct is not None:
            JOBS[jid]['percent'] = max(1, min(99, int(pct)))

    def run():
        try:
            s = pipeline.build(src, jd, voice=voice, rate=rate,
                               max_seconds=max_minutes * 60,
                               title=os.path.splitext(name)[0], progress=prog)
            JOBS[jid]['result'] = s
            JOBS[jid]['done'] = True
            JOBS[jid]['percent'] = 100
            JOBS[jid]['stage'] = '完成'
        except Exception as e:
            JOBS[jid]['error'] = '%s: %s' % (type(e).__name__, e)
            JOBS[jid]['stage'] = '失败'

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({'job': jid})


@app.get('/api/jobs/{jid}')
def api_job(jid: str):
    j = JOBS.get(jid)
    if not j:
        return JSONResponse({'error': 'no such job'}, status_code=404)
    out = {k: j[k] for k in ('id', 'file', 'stage', 'percent', 'done', 'error')}
    if j.get('result'):
        out['parts'] = [{'part': p['part'], 'seconds': p['seconds'], 'sentences': p['sentences'],
                         'video': '/files/%s/%s' % (jid, os.path.basename(p['video'])),
                         'srt': '/files/%s/%s' % (jid, os.path.basename(p['srt'])),
                         'audio': '/files/%s/%s' % (jid, os.path.basename(p['audio']))}
                        for p in j['result']['parts']]
        out['total_minutes'] = round(j['result']['total_seconds'] / 60, 1)
        out['units'] = j['result']['units']
    return JSONResponse(out)


@app.get('/files/{jid}/{fname}')
def api_file(jid: str, fname: str):
    p = os.path.join(WORK, jid, os.path.basename(fname))
    if not os.path.exists(p):
        return JSONResponse({'error': 'not found'}, status_code=404)
    return FileResponse(p)


HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDF → 高亮跟读视频</title>
<style>
:root{--bg:#0f1116;--card:#171a22;--line:#262b36;--fg:#e9edf5;--mut:#98a2b3;--acc:#5aa0ff;--yel:#ffd600}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:18px 16px 60px}
h1{font-size:21px;margin:6px 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
.drop{border:2px dashed #37404f;border-radius:12px;padding:26px 14px;text-align:center;color:var(--mut);cursor:pointer}
.drop.on{border-color:var(--acc);color:var(--fg);background:#14203a}
.drop b{color:var(--fg)}
label{display:block;font-size:13px;color:var(--mut);margin:12px 0 6px}
select,input[type=text]{width:100%;padding:11px 12px;border-radius:10px;background:#0e1219;border:1px solid var(--line);color:var(--fg);font-size:15px}
input[type=range]{width:100%}
.row{display:flex;gap:10px;align-items:center}
button{background:var(--acc);color:#04121f;border:0;border-radius:10px;padding:12px 16px;font-size:15px;font-weight:700;cursor:pointer}
button.ghost{background:#222939;color:var(--fg);font-weight:500}
button:disabled{opacity:.5;cursor:not-allowed}
.bar{height:10px;background:#0e1219;border-radius:6px;overflow:hidden;margin-top:10px}
.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--acc),var(--yel));transition:width .4s}
.stage{color:var(--mut);font-size:13px;margin-top:8px}
video{width:100%;border-radius:12px;background:#000;margin-top:8px}
a.dl{display:inline-block;margin:8px 10px 0 0;color:var(--acc);text-decoration:none;font-size:14px}
.pill{display:inline-block;background:#1d2433;color:var(--mut);border-radius:999px;padding:3px 10px;font-size:12px;margin-right:6px}
.tip{color:var(--mut);font-size:12.5px;margin-top:10px}
</style></head><body><div class="wrap">
<h1>📄 → 🎬 上传 PDF，出一个「高亮跟读」视频</h1>
<div class="sub">画面 = 原页排版；念到哪，黄框就框到哪；下方大字字幕，不看屏幕也能听。</div>

<div class="card">
  <div class="drop" id="drop"><b>点击选择 PDF</b>，或把文件拖进来<div class="tip" id="fname"></div></div>
  <input type="file" id="file" accept="application/pdf,.pdf" style="display:none">
  <label>音色（可先试听再决定）</label>
  <div class="row"><select id="voice"><!--VOICES--></select><button class="ghost" id="prev" style="white-space:nowrap">▶ 试听</button></div>
  <audio id="au" style="width:100%;margin-top:8px;display:none" controls></audio>
  <label>语速 <span id="rv" style="color:var(--fg)">+12%</span></label>
  <input type="range" id="rate" min="-30" max="40" step="2" value="12">
  <label>每卷最长（分钟）</label>
  <input type="text" id="maxmin" value="9.5">
  <div style="margin-top:14px"><button id="go" disabled>开始生成</button></div>
  <div class="bar"><i id="pbar"></i></div>
  <div class="stage" id="stage">等待上传…</div>
</div>

<div class="card" id="out" style="display:none">
  <div id="meta"></div>
  <div id="vids"></div>
</div>
<div class="tip">提示：视频在本机生成，长文档会比较慢（每句都要单独合成语音）。关闭网页不影响后台生成，回来刷一下即可。</div>
</div>
<script>
const $=s=>document.querySelector(s);
let voices=[], cur=null, timer=null;
fetch('/api/voices').then(r=>r.json()).then(d=>{
  voices=d.all;
  const keep=$('#voice').value;
  $('#voice').innerHTML=voices.map(v=>`<option value="${v.id}">${v.label}</option>`).join('');  // 服务端已渲染一版，这里补全
  if(keep)$('#voice').value=keep;
  window.SAMPLE=d.sample;
}).catch(()=>{window.SAMPLE='打标签这件事，核心是把模糊的业务概念，变成可重复的判断。'});
$('#drop').onclick=()=>$('#file').click();
$('#drop').ondragover=e=>{e.preventDefault();$('#drop').classList.add('on')};
$('#drop').ondragleave=()=>$('#drop').classList.remove('on');
$('#drop').ondrop=e=>{e.preventDefault();$('#drop').classList.remove('on');if(e.dataTransfer.files[0])pick(e.dataTransfer.files[0])};
$('#file').onchange=e=>{if(e.target.files[0])pick(e.target.files[0])};
function pick(f){cur=f;$('#fname').textContent='已选择：'+f.name+'（'+(f.size/1048576).toFixed(1)+' MB）';$('#go').disabled=false;}
const rv=()=>{const v=+$('#rate').value;$('#rv').textContent=(v>=0?'+':'')+v+'%';return (v>=0?'+':'')+v+'%';};
$('#rate').oninput=rv;
$('#prev').onclick=async()=>{
  const b=$('#prev');b.disabled=true;b.textContent='合成中…';
  try{
    const r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({voice:$('#voice').value,rate:rv(),text:window.SAMPLE})});
    if(!r.ok){throw new Error((await r.json()).error||'失败')}
    const bl=await r.blob();
    const a=$('#au');a.style.display='block';a.src=URL.createObjectURL(bl);a.play();
  }catch(e){alert('试听失败：'+e.message)}
  b.disabled=false;b.textContent='▶ 试听';
};
$('#go').onclick=async()=>{
  if(!cur)return;
  $('#go').disabled=true;$('#out').style.display='none';
  const fd=new FormData();fd.append('file',cur);fd.append('voice',$('#voice').value);
  fd.append('rate',rv());fd.append('max_minutes',$('#maxmin').value||'9.5');
  const r=await fetch('/api/upload',{method:'POST',body:fd});
  const d=await r.json();
  if(d.error){alert(d.error);$('#go').disabled=false;return}
  poll(d.job);
};
function poll(jid){
  clearInterval(timer);
  timer=setInterval(async()=>{
    const j=await (await fetch('/api/jobs/'+jid)).json();
    $('#pbar').style.width=(j.percent||0)+'%';
    $('#stage').textContent=(j.stage||'')+'  '+(j.percent||0)+'%';
    if(j.error){clearInterval(timer);$('#stage').textContent='❌ '+j.error;$('#go').disabled=false;return}
    if(j.done){
      clearInterval(timer);$('#go').disabled=false;
      $('#out').style.display='block';
      $('#meta').innerHTML=`<div><span class="pill">${j.units} 句</span><span class="pill">共 ${j.total_minutes} 分钟</span><span class="pill">${j.parts.length} 卷</span></div>`;
      $('#vids').innerHTML=j.parts.map(p=>`
        <div style="margin-top:14px">
          <b>第 ${p.part} 卷 · ${(p.seconds/60).toFixed(1)} 分钟 · ${p.sentences} 句</b>
          <video controls preload="metadata" src="${p.video}"></video>
          <div style="margin-top:8px">
            <button class="ghost" id="stopv${p.part}" onclick="(function(b){var v=b.parentNode.parentNode.querySelector('video');v.pause();b.textContent='■ 已停止播放'}(this))">■ 停止播放</button>
            <button class="ghost" onclick="(function(b){var v=b.parentNode.parentNode.querySelector('video');v.currentTime=0;v.play();b.previousElementSibling.textContent='■ 停止播放'}(this))">▶ 从头再听</button>
          </div>
          <a class="dl" href="${p.video}" download>⬇ 下载视频</a>
          <a class="dl" href="${p.audio}" download>⬇ 纯音频</a>
          <a class="dl" href="${p.srt}" download>⬇ 字幕</a>
        </div>`).join('');
      $('#stage').textContent='✅ 完成';
    }
  },1500);
}
rv();
</script></body></html>"""

if __name__ == '__main__':
    print('=' * 56)
    print('  PDF → 高亮跟读视频   打开： http://127.0.0.1:%d' % PORT)
    print('  同一 WiFi 的手机可用本机 IP 访问（见下面 LAN 地址）')
    print('=' * 56)
    uvicorn.run(app, host='0.0.0.0', port=PORT, log_level='warning')
