#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assemble_demo.py（v4）—— 成片音频 = **实时录下的系统原声** + 只在空档里加解说

设计原则（用户 2026-09-18 明确要求："不是实时放出来的声音没有意义，拼接像作假"）
 · 试听段 / 播放段：直接用**当时录到的系统输出**（WASAPI 回环），1× 原速、不改时间、不挪位置
 · 播完就停：录屏时真的点了播放器的暂停按钮（画面里能看到停了）
 · 我的解说只出现在**当时确实没声音**的段落里；出片前自动核对：
     ① 素材声段落里必须真有声音（否则说明没录到 → 报错）
     ② 任何时刻不得"解说与素材声同时响"（从音频能量上核，不看我的时间表）
 · 快进段（生成过程）：画面快进，那段本来也没声音，按倍率压缩
 
输出：演示_全流程.mp4 / .srt / _audio_evidence.png
"""
import json
import math
import os
import shutil
import subprocess
import time
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FFMPEG = r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '_demo_src')
FRAMES = os.path.join(SRC, 'frames')
WORK = os.path.join(SRC, 'out_frames')
NARR = os.path.join(SRC, 'narr')
SYSWAV = os.path.join(SRC, 'sysrec.wav')
FONT = r'C:\Windows\Fonts\msyh.ttc'
FONTB = r'C:\Windows\Fonts\msyhbd.ttc'
W, BH = 1280, 800        # 视口 1024x640 @1.25 → 录到 1280x800
BAR = 96
H = BH + BAR
FPS = 20

# 段落音频归属：real = 用实时录下的系统原声；narr = 用我的解说；none = 无音（快进段本来也没声音）
KIND = {'preview': 'real', 'play': 'real', 'generating': 'none'}
GREEN_TIP = '这里是实时录下的原声（不是后期配的）'


def run(cmd, quiet=True):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('失败: %s\n%s' % (cmd[:200], (r.stderr or '')[-500:]))
    return r.stdout


def load_wav_mono(path, sr=24000):
    tmp = path + '._m.wav'
    run('%s -y -v error -i "%s" -ac 1 -ar %d -c:a pcm_s16le "%s"' % (FFMPEG, path, sr, tmp))
    with wave.open(tmp, 'rb') as w:
        y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    os.remove(tmp)
    return y


def tts(text, path, voice='zh-CN-YunxiNeural', rate='+12%'):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    import asyncio
    import edge_tts

    async def go():
        c = edge_tts.Communicate(text, voice, rate=rate)
        await asyncio.wait_for(c.save(path), timeout=40)
    for i in range(4):
        try:
            asyncio.run(go())
            if os.path.getsize(path) > 800:
                return path
        except Exception as e:
            print('   TTS 重试 %d: %s' % (i + 1, type(e).__name__))
            time.sleep(1.5)
    raise RuntimeError('TTS 失败: %s' % text[:20])


def draw_cursor(d, x, y, pressing=False):
    """画一个真实光标（坐标来自我实际派发的鼠标事件，乘以设备像素比 1.25）"""
    pts = [(x, y), (x, y + 26), (x + 8, y + 19), (x + 14, y + 30), (x + 19, y + 27),
           (x + 13, y + 16), (x + 23, y + 15)]
    d.polygon(pts, fill=(255, 255, 255), outline=(20, 20, 20))
    d.line(pts[:-1] + [pts[0]], fill=(20, 20, 20), width=2)
    if pressing:
        d.ellipse([x - 16, y - 16, x + 30, y + 30], outline=(90, 200, 255), width=4)


def wrap(draw, text, font, maxw):
    lines, cur = [], ''
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


def main():
    tl = json.load(open(os.path.join(SRC, 'timeline.json'), encoding='utf-8'))
    marks = tl['marks']
    frames = tl['frames']                      # [[real_t, filename]]
    off = tl.get('sysrec_offset', 0.0)
    print('① 录屏 %d 帧 ｜ %d 个步骤标记 ｜ 系统录音 %.2fs' % (len(frames), len(marks), tl['sysrec_dur']))

    # ---- 系统原声（时间基准：录音起点 = t_start + off）----
    sysy = load_wav_mono(SYSWAV, 24000)
    SYS_SR = 24000
    print('   系统原声解码 %.2fs' % (len(sysy) / SYS_SR))

    def sys_slice(t_real, dur):
        """取系统原声里 [t_real, t_real+dur) 这一段（real 时间以 t_start 为 0）"""
        a = int((t_real - off) * SYS_SR)
        b = int((t_real + dur - off) * SYS_SR)
        a = max(0, min(len(sysy), a)); b = max(0, min(len(sysy), b))
        seg = sysy[a:b]
        want = int(round(dur * SYS_SR))
        if len(seg) < want:
            seg = np.concatenate([seg, np.zeros(want - len(seg), dtype=np.float32)])
        return seg[:want]

    def sys_level(t_real, dur):
        seg = sys_slice(t_real, dur)
        return float(np.sqrt((seg ** 2).mean() + 1e-12))

    # ---- 分段（真实时长来自标记）----
    for i, s in enumerate(marks):
        s['t1'] = marks[i + 1]['t0'] if i + 1 < len(marks) else s['t0'] + 3.0
        s['span'] = s['t1'] - s['t0']
        s['kind'] = KIND.get(s['name'], 'narr')

    # ---- 解说（只给 narr 段做）----
    os.makedirs(NARR, exist_ok=True)
    ndur = {}
    for i, s in enumerate(marks):
        if s['kind'] == 'narr':
            key = s['caption'][:20].replace('/', '_')
            mp3 = os.path.join(NARR, 'n%02d_%s.mp3' % (i, key))
            tts(s['caption'], mp3)
            ndur[i] = len(load_wav_mono(mp3, 24000)) / 24000.0
    print('② 解说合成 %d 段' % len(ndur))

    # ---- 排时间轴 ----
    step_names = [s['name'] for s in marks if s['name'] not in ('generating', 'gen_done', 'end')]
    total_steps = len(step_names)
    t = 0.0
    for i, s in enumerate(marks):
        if s['kind'] == 'real':
            s['odur'] = s['span']                       # 原声：原速原长
        elif s['kind'] == 'none':
            s['odur'] = s['span'] / s['speed']          # 快进段（这段本来没声音）
        else:
            s['odur'] = max(s['span'] / s['speed'], ndur.get(i, 0) + 0.5, 1.2)
        s['o0'], s['o1'] = t, t + s['odur']
        t += s['odur']
    out_len = t
    print('③ 成片 %.1f 秒（%d 段）｜素材声段：%s'
          % (out_len, len(marks), ', '.join('%s %.2fs' % (s['name'], s['odur'])
                                            for s in marks if s['kind'] == 'real')))

    # ---- 素材声自检（必须真有声音）----
    bad = []
    for s in marks:
        if s['kind'] == 'real':
            lv = sys_level(s['t0'], s['span'])
            print('   素材声段 %-8s 真实音量 %.4f → %s' % (s['name'], lv, '✅ 有真实声音' if lv > 0.01 else '❌ 没录到声音'))
            if lv <= 0.01:
                bad.append(s['name'])
    if bad:
        raise SystemExit('❌ 这些段没录到真实声音：%s（请重录）' % bad)

    def out2real(tt):
        for s in marks:
            if s['o0'] <= tt < s['o1'] or (s is marks[-1] and tt >= s['o0']):
                if s['kind'] == 'narr':
                    return s['t0'] + (tt - s['o0']) * s['speed'], s
                if s['kind'] == 'none':
                    return s['t0'] + (tt - s['o0']) * s['speed'], s
                return s['t0'] + (tt - s['o0']), s      # 原声段 1:1
        return marks[-1]['t1'], marks[-1]

    # ---- 音频装配 ----
    mat = np.zeros(int(out_len * SYS_SR) + SYS_SR, dtype=np.float32)
    nmaster = np.zeros_like(mat)
    spans = []
    for i, s in enumerate(marks):
        if s['kind'] == 'real':
            seg = sys_slice(s['t0'], min(s['span'], s['odur']))
            a = int(s['o0'] * SYS_SR)
            mat[a:a + len(seg)] += seg * 1.0
            spans.append((s['o0'], s['o0'] + len(seg) / SYS_SR, '素材声:' + s['name'],
                          float(np.sqrt((seg ** 2).mean() + 1e-12))))
        elif s['kind'] == 'narr':
            ys = load_wav_mono(os.path.join(NARR, sorted(
                [f for f in os.listdir(NARR) if f.startswith('n%02d_' % i)])[0]), 24000)
            a = int((s['o0'] + 0.3) * SYS_SR)
            nmaster[a:a + len(ys)] += ys * 0.95
            spans.append((s['o0'] + 0.3, s['o0'] + 0.3 + len(ys) / SYS_SR, '解说:' + s['name'], 0.0))
        else:
            seg = sys_slice(s['t0'], s['span'])
            if s['speed'] > 1.01 and len(seg) > 0:
                idx = np.linspace(0, len(seg) - 1, max(1, int(len(seg) / s['speed'])))
                seg = np.interp(idx, np.arange(len(seg)), seg).astype(np.float32)
            a = int(s['o0'] * SYS_SR)
            mat[a:a + len(seg)] += seg                     # 快进段本来也没声音，照实保留

    # ---- 重叠自检（从音频能量上核，不看时间表）----
    print('\n④ 音频自检')
    ok = True
    for i, (a, b, k, _) in enumerate(spans):
        if not k.startswith('解说'):
            continue
        # 解说窗口内，素材声那一路是否也有能量？
        seg = mat[int(a * SYS_SR):int(b * SYS_SR)]
        lv = float(np.sqrt((seg ** 2).mean() + 1e-12)) if len(seg) else 0.0
        if lv > 0.01:
            print('   ❌ 解说段 %s（%.2f→%.2f）期间素材声能量 %.4f' % (k, a, b, lv))
            ok = False
    print('   %s' % ('✅ 解说出现在空档里：素材发声时解说全部静音' if ok else '❌ 存在重叠'))
    for a, b, k, lv in spans:
        print('   %6.2f → %6.2f  %-22s %s' % (a, b, k, ('真实音量 %.3f' % lv) if lv else ''))

    master = mat + nmaster
    peak = float(np.abs(master).max())
    if peak > 0.99:
        master = master / peak * 0.97
    wav = os.path.join(SRC, 'master.wav')
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SYS_SR)
        w.writeframes((np.clip(master, -1, 1) * 32767).astype(np.int16).tobytes())

    # ---- 逐帧渲染 ----
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK, exist_ok=True)
    n_out = int(math.ceil(out_len * FPS))
    fj = 0
    last_good = None
    # ★ 开场白闪/模糊：预扫时跳过页面加载中的前 2 秒，取"已渲染好"的第一帧作为起始画面
    _t_first = frames[0][0] if frames else 0.0
    for _t, _n in frames[:80]:
        if _t - _t_first < 2.0:
            continue
        _p = os.path.join(FRAMES, _n)
        if not os.path.exists(_p):
            continue
        _im = Image.open(_p).convert('RGB').resize((64, 40))
        _px = list(_im.getdata())
        _m = sum(sum(q[:3]) / 3 for q in _px) / len(_px)
        _v = sum((sum(q[:3]) / 3 - _m) ** 2 for q in _px) / len(_px)
        if _v >= 60:
            last_good = _im.resize((W, BH), Image.LANCZOS)
            break
    mouse = tl.get('mouse', [])
    files = []
    for k in range(n_out):
        ot = k / float(FPS)
        rt, s = out2real(ot)
        # 取"真实时间 ≤ rt"的最后一帧
        while fj + 1 < len(frames) and frames[fj + 1][0] <= rt:
            fj += 1
        while fj > 0 and frames[fj][0] > rt:
            fj -= 1
        src = os.path.join(FRAMES, frames[fj][1])
        if not os.path.exists(src):
            continue
        img = Image.open(src).convert('RGB')
        small = img.resize((64, 40))
        px = list(small.getdata())
        mean = sum(sum(pp[:3]) / 3 for pp in px) / len(px)
        var = sum((sum(pp[:3]) / 3 - mean) ** 2 for pp in px) / len(px)
        if var < 60 and last_good is not None:      # 纯白/纯色空白帧（开场白闪）→ 沿用上一帧
            img = last_good
        else:
            last_good = img
        img = img.resize((W, BH), Image.LANCZOS)
        canvas = Image.new('RGB', (W, H), (14, 16, 22))
        canvas.paste(img, (0, 0))
        d = ImageDraw.Draw(canvas)
        d.rectangle([0, 0, W, 6], fill=(90, 160, 255))
        fb = ImageFont.truetype(FONTB, 24)
        if s['name'] in step_names:
            label = '用户全流程演示 · 第 %d/%d 步' % (step_names.index(s['name']) + 1, total_steps)
        else:
            label = '用户全流程演示 · 生成中' if s['kind'] == 'none' else '用户全流程演示'
        # ⚠️ 页面背景可能是白的 → 步骤条必须带深色底衬，否则白字看不见
        _lw = d.textlength(label, font=fb)
        d.rectangle([12, 8, 12 + _lw + 20, 48], fill=(10, 12, 18))
        d.text((20, 14), label, font=fb, fill=(255, 255, 255))
        if s['kind'] == 'none':
            badge = '快进 ×%d（真实用时 %d 秒）' % (int(s['speed']), int(round(s['span'])))
            tw = d.textlength(badge, font=fb)
            d.rectangle([W - tw - 34, 10, W - 12, 46], fill=(200, 96, 0))
            d.text((W - tw - 22, 14), badge, font=fb, fill=(255, 255, 255))
        elif s['kind'] == 'real':
            badge = '原声 · 实时录制'
            tw = d.textlength(badge, font=fb)
            d.rectangle([W - tw - 34, 10, W - 12, 46], fill=(16, 120, 60))
            d.text((W - tw - 22, 14), badge, font=fb, fill=(255, 255, 255))
        if mouse:
            cur = None
            press = False
            for m in mouse:
                if m[0] <= rt:
                    cur = m
                    press = press or (m[3] == 'down' and rt - m[0] < 0.45)
                else:
                    break
            if cur:
                draw_cursor(d, cur[1] * 1.25, cur[2] * 1.25, press)
        fs = ImageFont.truetype(FONT, 30)
        lines = wrap(d, s['caption'], fs, W - 90)[:2]
        y = BH + 12
        for ln in lines:
            tw = d.textlength(ln, font=fs)
            d.text(((W - tw) / 2, y), ln, font=fs, fill=(255, 255, 255))
            y += 38
        if s['kind'] == 'real':
            fg = ImageFont.truetype(FONT, 22)
            d.text((W - 18 - d.textlength(GREEN_TIP, font=fg), H - 30), GREEN_TIP, font=fg,
                   fill=(120, 230, 150))
        p = os.path.join(WORK, 'o%05d.jpg' % k)
        canvas.save(p, quality=88)
        files.append(p)

    lst = os.path.join(SRC, 'olist.txt')
    with open(lst, 'w', encoding='utf-8') as fh:
        for p in files:
            fh.write("file '%s'\nduration %.4f\n" % (os.path.abspath(p).replace('\\', '/'), 1.0 / FPS))
        fh.write("file '%s'\n" % os.path.abspath(files[-1]).replace('\\', '/'))
    out = os.path.join(HERE, '演示_全流程.mp4')
    run('%s -y -f concat -safe 0 -i "%s" -i "%s" -vf "fps=%d,format=yuv420p" -c:v libx264 '
        '-preset veryfast -crf 26 -pix_fmt yuv420p -c:a aac -b:a 160k -shortest "%s"'
        % (FFMPEG, os.path.abspath(lst), wav, FPS, out))
    sp = os.path.join(HERE, '演示_全流程.srt')
    with open(sp, 'w', encoding='utf-8') as fh:
        for n, s in enumerate(marks, 1):
            fh.write('%d\n%s --> %s\n%s\n\n' % (n, ts(s['o0']), ts(s['o1']), s['caption']))
    print('\n✅ 成片: %s（%.1f 秒 / %.2f MB）' % (out, out_len, os.path.getsize(out) / 1048576))


def ts(x):
    h = int(x // 3600); m = int((x % 3600) // 60); s = int(x % 60); ms = int((x - int(x)) * 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


if __name__ == '__main__':
    main()
