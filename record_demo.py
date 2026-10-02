#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
record_demo.py（v2）—— 录"用户使用全流程"演示片，**声音是实时录下来的真实播放声**

关键改动（用户要求：不能事后拼接声音，必须是真实操作时放出来的声音）
 · WASAPI 回环录音（pyaudiowpatch）：把系统输出（= 浏览器真实播放声）全程录下来
 · 试听段：点「试听」后**等真实声音播完**（检测到声音结束）才继续
 · 播放段：点播放 → 让它播原声（1×，不快进）→ **真点暂停按钮**结束这一段
 · 时间轴：所有标记都用 time.time() 打点，与录音同一个时钟 → 可精确对齐
输出：_demo_src/frames/*.jpg（带时间戳）、_demo_src/sysrec.wav、_demo_src/timeline.json
"""
import asyncio
import base64
import json
import os
import subprocess
import threading
import time
import wave

import numpy as np
import pyaudiowpatch as pa
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '_demo_src')
FRAMES = os.path.join(OUT, 'frames')
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
PROF = os.path.join(os.environ.get('TEMP', 'C:/Windows/Temp'), '_demo_prof_v2')
PORT = 9366
URL = 'http://127.0.0.1:8756/'
W_BROWSER = 1280
PDF = os.path.join(HERE, '演示文档.pdf')
SAMPLE = '打标签这件事，核心是把模糊的业务概念，变成可重复的判断。所以真正难的不是标注本身，而是先把定义说清楚。'


# ---------------- 系统真实播放声录制（WASAPI 回环） ----------------
class SysRec:
    def __init__(self, path):
        self.path = path
        self.p = pa.PyAudio()
        dev = self.p.get_default_wasapi_loopback()
        self.rate = int(dev['defaultSampleRate'])
        self.ch = int(dev['maxInputChannels'])
        self.stream = self.p.open(format=pa.paInt16, channels=self.ch, rate=self.rate,
                                  input=True, input_device_index=dev['index'],
                                  frames_per_buffer=1024)
        self.frames = []
        self.lock = threading.Lock()
        self.stop = False
        self.t0 = None
        self.dev_name = dev['name']

    def start(self):
        """开始录制前先读 2 帧丢掉（避开设备启动的噪声/空窗）"""
        for _ in range(2):
            self.stream.read(1024, exception_on_overflow=False)
        self.t0 = time.time()
        threading.Thread(target=self._run, daemon=True).start()
        return self.t0

    def _run(self):
        while not self.stop:
            try:
                b = self.stream.read(1024, exception_on_overflow=False)
            except Exception:
                break
            with self.lock:
                self.frames.append(b)

    def level(self, last_seconds=0.3):
        """最近 last_seconds 的平均音量（用来判断"声音播完了没有"）"""
        n = max(1, int(last_seconds * self.rate / 1024))
        with self.lock:
            tail = self.frames[-n:]
        if not tail:
            return 0.0
        y = np.frombuffer(b''.join(tail), dtype=np.int16).astype(np.float32) / 32768.0
        if self.ch > 1:
            y = y.reshape(-1, self.ch).mean(axis=1)
        return float(np.sqrt((y ** 2).mean() + 1e-12))

    def finish(self):
        self.stop = True
        time.sleep(0.3)
        try:
            self.stream.stop_stream(); self.stream.close(); self.p.terminate()
        except Exception:
            pass
        with self.lock:
            raw = b''.join(self.frames)
        with wave.open(self.path, 'wb') as w:
            w.setnchannels(self.ch); w.setsampwidth(2); w.setframerate(self.rate)
            w.writeframes(raw)
        dur = (len(raw) // 2 // self.ch) / float(self.rate)
        return self.t0, dur


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.i = 0
        self.waiting = {}
        self.n = 0
        self.frames = []          # [(ts, 文件名)] —— 与步骤标记分开存
        self.mouse = []           # [(t_start 相对秒, x, y, 类型, 尺寸)] —— 用来在成片里画真实光标

    async def log_mouse(self, kind, x, y, scale=1.0):
        self.mouse.append([round(time.time() - self.t0, 4), round(x, 1), round(y, 1), kind, scale])

    async def cmd(self, method, **params):
        self.i += 1
        i = self.i
        fut = asyncio.get_event_loop().create_future()
        self.waiting[i] = fut
        await self.ws.send(json.dumps({'id': i, 'method': method, 'params': params}))
        return await asyncio.wait_for(fut, timeout=40)

    async def reader(self, ws):
        async for raw in ws:
            m = json.loads(raw)
            if 'id' in m:
                f = self.waiting.pop(m['id'], None)
                if f and not f.done():
                    f.set_result(m)
            elif m.get('method') == 'Page.screencastFrame':
                p = m['params']
                ts = time.time()
                name = 'f%05d.jpg' % self.n
                with open(os.path.join(FRAMES, name), 'wb') as fh:
                    fh.write(base64.b64decode(p['data']))
                self.n += 1
                self.frames.append((ts, name))
                await ws.send(json.dumps({'id': 900000 + self.n, 'method': 'Page.screencastFrameAck',
                                          'params': {'sessionId': p['sessionId']}}))

    async def ev(self, expr):
        r = await self.cmd('Runtime.evaluate', expression=expr, returnByValue=True)
        return ((r.get('result') or {}).get('result') or {}).get('value')

    async def click_sel(self, sel, pre=0.0):
        box = await self.ev("(function(){var e=document.querySelector('%s');if(!e)return null;"
                            "var r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()" % sel)
        if not box:
            return False
        await self.cmd('Input.dispatchMouseEvent', type='mouseMoved', x=box[0], y=box[1])
        await self.log_mouse('move', box[0], box[1])
        await asyncio.sleep(0.12)
        await self.cmd('Input.dispatchMouseEvent', type='mousePressed', x=box[0], y=box[1],
                       button='left', clickCount=1)
        await self.log_mouse('down', box[0], box[1])
        await asyncio.sleep(0.06)
        await self.cmd('Input.dispatchMouseEvent', type='mouseReleased', x=box[0], y=box[1],
                       button='left', clickCount=1)
        await self.log_mouse('up', box[0], box[1])
        return True

    async def click_xy(self, x, y):
        await self.cmd('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y)
        await self.log_mouse('move', x, y)
        await asyncio.sleep(0.1)
        await self.cmd('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button='left', clickCount=1)
        await self.log_mouse('down', x, y)
        await asyncio.sleep(0.06)
        await self.cmd('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button='left', clickCount=1)
        await self.log_mouse('up', x, y)


async def main():
    os.makedirs(FRAMES, exist_ok=True)
    for f in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, f))
    marks = []
    sysrec = SysRec(os.path.join(OUT, 'sysrec.wav'))
    proc = subprocess.Popen([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                             '--no-first-run', '--autoplay-policy=no-user-gesture-required',
                             '--window-size=%d,820' % W_BROWSER, '--remote-debugging-port=%d' % PORT,
                             '--user-data-dir=' + PROF, 'about:blank'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(40):
        await asyncio.sleep(1)
        try:
            r = subprocess.run('curl -s http://127.0.0.1:%d/json/list' % PORT, shell=True,
                               capture_output=True, text=True)
            for t in json.loads(r.stdout):
                if t.get('type') == 'page':
                    ws_url = t['webSocketDebuggerUrl']
            if ws_url:
                break
        except Exception:
            pass
    assert ws_url, '拿不到调试地址'
    print('浏览器就绪，开始录真实系统声音 + 逐帧录屏')

    async with websockets.connect(ws_url, max_size=80 * 1024 * 1024) as ws:
        c = CDP(ws)
        rd = asyncio.create_task(c.reader(ws))
        await c.cmd('Page.enable')
        await c.cmd('Runtime.enable')
        await c.cmd('DOM.enable')
        # ★ 界面放大 25%：视口 1024x640、设备像素比 1.25 → 录到 1280 宽，手机上也看得清
        await c.cmd('Emulation.setDeviceMetricsOverride', width=1024, height=640,
                    deviceScaleFactor=1.25, mobile=False)
        await c.cmd('Page.startScreencast', format='jpeg', quality=85, maxWidth=W_BROWSER,
                    maxHeight=1000, everyNthFrame=1)
        sysrec.start()                      # ★ 先开始录系统声音
        t_start = time.time()
        c.t0 = t_start

        def mark(name, speed, caption):
            marks.append({'name': name, 't0': time.time() - t_start, 'speed': speed, 'caption': caption})
            print('[mark] %-12s speed=%.2f  %s' % (name, speed, caption))

        async def wait_sound_end(max_wait=30.0, quiet_needed=0.7, thresh=0.012):
            """等到"声音放完"：先听到声音，再连续 quiet_needed 秒安静 → 判定结束"""
            waited, loud, quiet_since = 0.0, False, None
            while waited < max_wait:
                await asyncio.sleep(0.15); waited += 0.15
                lv = sysrec.level(0.3)
                if lv > thresh:
                    loud, quiet_since = True, None
                elif loud:
                    quiet_since = quiet_since or time.time()
                    if time.time() - quiet_since >= quiet_needed:
                        return waited, lv
            return waited, sysrec.level(0.3)

        # 1) 打开网页
        await c.cmd('Page.navigate', url=URL)
        await asyncio.sleep(4.5)      # ★ 先等页面渲染完成再打标记：否则开场是加载中的模糊帧
        mark('open', 1.0, '第 1 步：打开网页。本机可以打开，同一 WiFi 的手机也能打开。')
        await asyncio.sleep(1.6)

        # 2) 选 PDF
        mark('pick_file', 1.0, '第 2 步：选一份 PDF。点一下选择，或者直接把文件拖进来。')
        await c.click_sel('#drop')
        await asyncio.sleep(0.6)
        root = (await c.cmd('DOM.getDocument'))['result']['root']['nodeId']
        node = (await c.cmd('DOM.querySelector', nodeId=root, selector='#file'))['result']['nodeId']
        await c.cmd('DOM.setFileInputFiles', files=[PDF], nodeId=node)
        await asyncio.sleep(1.6)

        # 3) 选音色
        mark('pick_voice', 1.0, '第 3 步：选音色。下拉里有十个内置的中文音色。')
        await c.click_sel('#voice')
        await asyncio.sleep(0.5)
        await c.ev("(function(){var s=document.querySelector('#voice');s.value='zh-CN-XiaoxiaoNeural';"
                   "s.dispatchEvent(new Event('change',{bubbles:true}));return s.value})()")
        await asyncio.sleep(1.8)

        # 4) 试听（★ 等真实声音播完）
        mark('preview', 1.0, '第 4 步：点试听。先听一句样例，觉得合适再开始生成。')
        await c.click_sel('#prev', 0.8)
        wait, lv = await wait_sound_end(max_wait=30)
        print('   试听真实声音结束：等待 %.1fs（末音量 %.3f）' % (wait, lv))
        await asyncio.sleep(0.8)

        # 5) 调语速
        mark('rate', 1.0, '第 5 步：拖语速滑块。这里从正百分之十二，调到正百分之二十。')
        sb = await c.ev("(function(){var e=document.querySelector('#rate');if(!e)return null;"
                        "var r=e.getBoundingClientRect();return [r.x+r.width*0.72, r.y+r.height/2]})()")
        if sb:
            await c.click_xy(int(sb[0]), int(sb[1]))
        await asyncio.sleep(1.8)

        # 6) 开始生成
        mark('start', 1.0, '第 6 步：点开始生成。接下来是机器干活，这一段会快进。')
        await c.click_sel('#go')
        await asyncio.sleep(2.0)

        # 7) 等待生成（快进段）
        mark('generating', 14.0, '正在生成：解析 PDF，逐句合成语音，逐句画高亮帧，最后合成视频。')
        t_gen0 = time.time()
        while True:
            st = await c.ev("(function(){var e=document.querySelector('#stage');return e?e.textContent:''})()")
            if st and '完成' in st:
                break
            if time.time() - t_gen0 > 600:
                break
            await asyncio.sleep(1.2)
        print('   生成耗时 %.1f 秒' % (time.time() - t_gen0))
        await asyncio.sleep(1.0)
        mark('gen_done', 1.0, '生成完成，结果就在下面。')
        await asyncio.sleep(2.2)

        # 8) 播放效果（★ 播原声，1×，然后真点暂停）
        mark('play', 1.0, '第 7 步：页面里直接播放。上半屏是 PDF 原页，黄框跟着念；下半屏是大字字幕。')
        rect = await c.ev("(function(){var v=document.querySelector('video');if(!v)return null;"
                          "v.scrollIntoView({block:'center',behavior:'smooth'});v.muted=false;v.play();"
                          "var r=v.getBoundingClientRect();"
                          "return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]})()")
        await asyncio.sleep(0.8)
        await c.cmd('Input.dispatchMouseEvent', type='mouseMoved',
                    x=rect[0] + 40, y=rect[1] + 30) if rect else None
        await asyncio.sleep(12.0)           # 真实播放 12 秒原声
        # ★ 真点页面上的"■ 停止播放"按钮（无头 Chrome 不渲染原生播放器控件，所以产品里加了这个按钮）
        await c.click_sel('#stopv1')
        await asyncio.sleep(0.6)
        paused = await c.ev("document.querySelector('video').paused")
        print('   点「停止播放」后 paused=%s' % paused)
        if paused is not True:
            await c.ev("document.querySelector('video').pause()")
            print('   已用 JS 兜底暂停')
        await asyncio.sleep(1.2)

        # 9) 下载
        mark('download', 1.0, '第 8 步：下载。视频、纯音频、字幕都在这里；长文档会自动分卷。')
        await c.ev('window.scrollTo({top:document.body.scrollHeight,behavior:"smooth"})')
        await asyncio.sleep(1.6)
        # ★ 真实鼠标移动到下载链接上（不要用 JS 模拟 hover：画面上要有光标才像真的）
        rects = await c.ev("(function(){return [].slice.call(document.querySelectorAll('a[download]'))"
                           ".map(function(a){var r=a.getBoundingClientRect();"
                           "return [Math.round(r.x+r.width/2),Math.round(r.y+r.height/2)]})})()")
        for x, y in (rects or [])[:3]:
            await c.cmd('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y)
            await c.log_mouse('move', x, y)
            await asyncio.sleep(0.7)

        # 10) 收尾
        mark('end', 1.0, '全流程结束：从上传到出片，全程不用碰命令行。')
        await asyncio.sleep(2.5)

        try:
            await c.cmd('Page.stopScreencast')
        except Exception:
            pass
        rd.cancel()
    t0_rec, dur = sysrec.finish()
    subprocess.run('taskkill /F /T /PID %d' % proc.pid, shell=True, capture_output=True)
    timeline = {'t_start': t_start, 'sysrec_t0': t0_rec, 'sysrec_dur': dur,
                'sysrec_offset': t0_rec - t_start, 'marks': marks, 'mouse': c.mouse,
                'frames': [[round(t - t_start, 4), n] for t, n in c.frames]}
    with open(os.path.join(OUT, 'timeline.json'), 'w', encoding='utf-8') as fh:
        json.dump(timeline, fh, ensure_ascii=False, indent=2)
    print('  时间轴已存 timeline.json（%d 帧 / %d 标记）｜系统录音 %.2f 秒（起点偏移 %+.2fs）'
          % (len(timeline['frames']), len(marks), dur, timeline['sysrec_offset']))


if __name__ == '__main__':
    asyncio.run(main())
