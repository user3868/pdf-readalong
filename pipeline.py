#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py —— PDF → 「原页 + 高亮跟读 + 大字字幕 + 逐句语音」视频
不依赖浏览器：文本坐标直接取自 PDF 文本层（PyMuPDF），所以原版排版不会丢。
"""
import asyncio
import json
import math
import os
import re
import subprocess
import time
import wave

import numpy as np
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

# ---------- 外部工具 ----------
FFMPEG = os.environ.get('FFMPEG') or r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
FFPROBE = os.environ.get('FFPROBE') or r'C:\ProgramData\chocolatey\bin\ffprobe.exe'
FONT_PATH = r'C:\Windows\Fonts\msyh.ttc'
FONT_BOLD = r'C:\Windows\Fonts\msyhbd.ttc'

# ---------- 画面参数 ----------
W, H = 1280, 720
IMG_H = 500                     # 上半屏：原页图像
SUB_TOP = IMG_H + 8             # 下半屏：字幕区
PAGE_SCALE = 2.0                # PDF 页渲染倍率
SUB_FONT = 37
MAX_PART_SECONDS = 570          # 单卷上限（留 30s 余量给 10 分钟）

_state = {}


# ============ 1) 解析 PDF → 朗读单元（带坐标） ============
def extract_units(pdf_path, out_dir, progress=None):
    """返回 {'pages': [图片路径], 'units': [ {page,text,rects,bbox,kind} ]}"""
    doc = fitz.open(pdf_path)
    os.makedirs(out_dir, exist_ok=True)
    pages, units = [], []
    n = doc.page_count
    for pno in range(n):
        page = doc[pno]
        pix = page.get_pixmap(matrix=fitz.Matrix(PAGE_SCALE, PAGE_SCALE))
        img_path = os.path.join(out_dir, 'page_%03d.png' % (pno + 1))
        pix.save(img_path)
        pages.append({'img': img_path, 'w': pix.width, 'h': pix.height})
        if progress:
            progress('解析 PDF：第 %d/%d 页' % (pno + 1, n), (pno + 1) / max(n, 1) * 30)

        # --- 表格区（有则单独处理，并从正文里剔掉） ---
        table_rects = []
        try:
            tabs = page.find_tables()
            for t in tabs.tables:
                rows = t.extract()
                if not rows:
                    continue
                head = [str(c or '').strip() for c in rows[0]]
                for r_i, row in enumerate(rows):
                    cells = [str(c or '').strip() for c in row]
                    if not any(cells):
                        continue
                    txt = '；'.join('%s：%s' % (head[i] if i < len(head) and head[i] else '第%d列' % (i + 1), c)
                                    for i, c in enumerate(cells) if c)
                    if len(txt) < 4:
                        continue
                    r_bbox = None
                    try:
                        r_bbox = t.rows[r_i].bbox
                    except Exception:
                        pass
                    if r_bbox:
                        units.append({'page': pno, 'text': txt, 'rects': [list(r_bbox)],
                                      'bbox': list(r_bbox), 'kind': 'table'})
                        table_rects.append(r_bbox)
        except Exception:
            pass

        # --- 正文 ---
        # 用 rawdict：带**每个字符**的 bbox → 高亮能精确到"这一句的字符范围"，而不是整行
        d = page.get_text('rawdict')
        # ★ 断句修复（2026-09-30）：PyMuPDF 常把每个折行返回成独立 block
        #   （实测：本机一份 3 页 PDF，第 1 页返回 12 个 block，每个 block 恰好一行 45 字）。
        #   若直接逐 block 切句，"一句话"会在词中间被切断（实测 45 条字幕里 15 条是半句，
        #   如「…听的人手上有」+「多少注意力。」）。
        #   修法：先按纵向间距把相邻的行 block 合并回段落，再切句。
        #   实测行内换行间距 5.2pt、段间距 ≥19.9pt、行高 13.2pt → 阈值取行高的 0.8 倍很稳。
        _raw = [b for b in d.get('blocks', []) if b.get('type') == 0]
        _raw.sort(key=lambda b: (round(b['bbox'][1], 1), b['bbox'][0]))
        _blocks = []
        for _b in _raw:
            if _blocks:
                _pv = _blocks[-1]
                _gap = _b['bbox'][1] - _pv['bbox'][3]
                _lh = max(1.0, _pv['bbox'][3] - _pv['bbox'][1])
                if 0 <= _gap < max(6.0, _lh * 0.8):
                    _pv['lines'] = list(_pv.get('lines', [])) + list(_b.get('lines', []))
                    _pv['bbox'] = [min(_pv['bbox'][0], _b['bbox'][0]), _pv['bbox'][1],
                                   max(_pv['bbox'][2], _b['bbox'][2]), _b['bbox'][3]]
                    continue
            _nb = dict(_b)
            _nb['lines'] = list(_b.get('lines', []))
            _blocks.append(_nb)
        for b in _blocks:
            if table_rects and _overlaps(b.get('bbox'), table_rects):
                continue
            lines = []
            for ln in b.get('lines', []):
                chars = []
                for sp in ln.get('spans', []):
                    for ch in sp.get('chars', []) or []:
                        if ch.get('c'):
                            chars.append(ch)
                if chars:
                    lines.append({'chars': chars})
            if not lines:
                continue
            full = ''
            for l in lines:
                l['start'] = len(full)
                full += ''.join(c['c'] for c in l['chars'])
            for m in re.finditer(r'[^。！？；\n]+[。！？；]?', full):
                raw = m.group(0)
                s = raw.strip()
                if len(s) < 2:
                    continue
                st = m.start() + (len(raw) - len(raw.lstrip()))
                en = st + len(s)
                # 逐字符取框 → 按行合并（精确到句，不吞邻句）
                rects = []
                for l in lines:
                    sel = []
                    for ci, c in enumerate(l['chars']):
                        g = l['start'] + ci
                        if st <= g < en:
                            sel.append(c['bbox'])
                    if sel:
                        rects.append([min(r[0] for r in sel), min(r[1] for r in sel),
                                      max(r[2] for r in sel), max(r[3] for r in sel)])
                if not rects:
                    continue
                x0 = min(r[0] for r in rects); y0 = min(r[1] for r in rects)
                x1 = max(r[2] for r in rects); y1 = max(r[3] for r in rects)
                units.append({'page': pno, 'text': s, 'rects': [list(r) for r in rects],
                              'bbox': [x0, y0, x1, y1], 'kind': 'text'})
    doc.close()
    return {'pages': pages, 'units': units}


def _overlaps(bb, rects):
    if not bb:
        return False
    for r in rects:
        if not (bb[2] < r[0] or bb[0] > r[2] or bb[3] < r[1] or bb[1] > r[3]):
            return True
    return False


# ============ 2) 逐句 TTS（带超时 + 重试） ============
async def _tts_one(text, mp3, voice, rate, timeout=25):
    import edge_tts
    await asyncio.wait_for(
        edge_tts.Communicate(text, voice, rate=rate, connect_timeout=12, receive_timeout=30).save(mp3),
        timeout=timeout)


def tts_sentence(text, mp3, voice, rate, retries=5):
    for i in range(retries):
        try:
            asyncio.run(_tts_one(text, mp3, voice, rate))
            if os.path.exists(mp3) and os.path.getsize(mp3) > 800:
                return True
        except Exception:
            pass
        time.sleep(1.5 + i)
    return False


def probe_dur(path):
    r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1', path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ---------- 句级静音裁剪：时间轴必须建立在"净语音"上 ----------
# 实测（2026-09-17）：edge-tts 每个句子的 mp3 自带 句首 0.13~0.16s + 句尾 0.42~0.50s 静音，
# 整片约 14% 是静音。若直接拿"文件时长"排字幕/高亮，会每句偏约 0.6s、个别处叠到 1~2s。
LEAD_KEEP = 0.07      # 保留的句首静音
TAIL_KEEP = 0.10      # 保留的句尾静音
SENT_GAP = 0.06       # 句间停顿的"目标"秒数（⚠️ 实际值必须用 pcm_dur 实测：
                      # mp3 编码器会把 0.06s 的静音文件撑到约 0.18s，若按目标值排时间轴必然累积漂移）


def speech_bounds(path, top_db=35.0, hop_ms=10):
    """按帧能量找语音起止（VAD），返回 (start_s, end_s, file_dur_s)"""
    wav = path + '.vad.wav'
    _run('%s -y -v error -i "%s" -ac 1 -ar 16000 -c:a pcm_s16le "%s"' % (FFMPEG, path, wav))
    try:
        with wave.open(wav, 'rb') as w:
            sr = w.getframerate()
            data = w.readframes(w.getnframes())
    finally:
        try:
            os.remove(wav)
        except Exception:
            pass
    y = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    dur = len(y) / float(sr)
    hop = max(1, int(sr * hop_ms / 1000.0))
    n = len(y) // hop
    if n < 3:
        return 0.0, dur, dur
    rms = np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    thr = rms.max() * (10 ** (-top_db / 20.0))
    idx = np.where(rms > thr)[0]
    if len(idx) == 0:
        return 0.0, dur, dur
    return idx[0] * hop / float(sr), (idx[-1] + 1) * hop / float(sr), dur


def trim_seg(src, dst, sr=24000):
    """把一句 mp3 裁成"净语音+少量首尾"，返回裁剪后时长（秒）"""
    a, b, d = speech_bounds(src)
    st = max(0.0, a - LEAD_KEEP)
    en = min(d, b + TAIL_KEEP)
    if en - st < 0.05:
        st, en = 0.0, d
    _run('%s -y -v error -ss %.3f -to %.3f -i "%s" -ac 1 -ar %d -b:a 48k "%s"'
         % (FFMPEG, st, en, src, sr, dst))
    return max(0.05, en - st)


def pcm_dur(path, sr=24000):
    """解码后的真实采样数 → 秒。⚠️ 不能用 ffprobe 的 mp3 时长：
    LAME 每段还带编码延迟/补帧，ffprobe 报的比实际解码短约 0.12s，17 段就累积 2s 漂移。"""
    r = subprocess.run('%s -v error -i "%s" -f s16le -ac 1 -ar %d -' % (FFMPEG, path, sr),
                       shell=True, capture_output=True)
    return len(r.stdout) // 2 / float(sr)


# ---------- PCM 层拼装：唯一能保证"时间轴 = 音频"的做法 ----------
# 实测（2026-09-17）：就算按"解码长度"算，逐段 mp3 拼接后仍比各段之和长（编码延迟逐段累积）。
# 所以：解码到 PCM → 按 VAD 裁首尾 → 插入精确长度的纯 PCM 停顿 → 整卷只编码一次。
SR_AUDIO = 24000


def decode_pcm(path, sr=SR_AUDIO):
    r = subprocess.run('%s -v error -i "%s" -f s16le -ac 1 -ar %d -' % (FFMPEG, path, sr),
                       shell=True, capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _bounds_pcm(y, sr, top_db=35.0, hop_ms=10, min_run=5):
    """找语音起止（VAD）。
    ⚠️ 只按"峰值-35dB"单阈值会被 TTS 开头的气声/杂音骗到 → 会留下约 1 秒假静音，
       导致"字幕亮了却没声音"。所以：阈值 = max(峰值-35dB, 语音主体电平-25dB)，
       并要求连续 min_run 帧（50ms）都超过阈值才算语音开始。"""
    hop = max(1, int(sr * hop_ms / 1000.0))
    n = len(y) // hop
    if n < 3:
        return 0.0, len(y) / float(sr)
    rms = np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    body = float(np.percentile(rms, 90))                     # 语音主体电平
    thr = max(rms.max() * (10 ** (-top_db / 20.0)), body * 10 ** (-25 / 20.0))
    hot = rms > thr
    if not hot.any():
        return 0.0, len(y) / float(sr)
    # 连续 min_run 帧视为语音
    runs = []
    i = 0
    while i < n:
        if hot[i]:
            j = i
            while j + 1 < n and hot[j + 1]:
                j += 1
            if j - i + 1 >= min_run:
                runs.append((i, j))
            i = j + 1
        else:
            i += 1
    if not runs:
        return 0.0, len(y) / float(sr)
    return runs[0][0] * hop / float(sr), (runs[-1][1] + 1) * hop / float(sr)


def trim_pcm(y, sr=SR_AUDIO, top_db=35.0):
    """按 VAD 裁掉首尾多余静音，返回 (裁剪后 PCM, 原语音起止)"""
    a, b = _bounds_pcm(y, sr, top_db)
    i0 = max(0, int((a - LEAD_KEEP) * sr))
    i1 = min(len(y), int((b + TAIL_KEEP) * sr))
    if i1 - i0 < int(0.05 * sr):
        i0, i1 = 0, len(y)
    return y[i0:i1], (a, b)


def write_wav(path, y, sr=SR_AUDIO):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def make_gap_silence(path, seconds=SENT_GAP, sr=24000):
    if not (os.path.exists(path) and os.path.getsize(path) > 100):
        _run('%s -y -v error -f lavfi -i anullsrc=r=%d:cl=mono -t %.3f -ac 1 -ar %d -b:a 48k "%s"'
             % (FFMPEG, sr, seconds, sr, path))
    return path


# ============ 3) 逐句渲染帧 ============
def _wrap(draw, text, font, maxw):
    lines, cur = [], ''
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


def target_top(unit, page):
    """这句话对应的窗口纵向位置（未插值）——平滑滚动逐帧插值用"""
    src_w, src_h = Image.open(page['img']).size
    q = W / src_w
    win_h = int(IMG_H / q)
    boxes = [[r[0] * PAGE_SCALE, r[1] * PAGE_SCALE, r[2] * PAGE_SCALE, r[3] * PAGE_SCALE]
             for r in unit['rects']]
    y0 = min(b[1] for b in boxes); y1 = max(b[3] for b in boxes)
    t = int((y0 + y1) / 2 - win_h / 2)
    return max(0, min(t, max(0, src_h - win_h)))


def pdf_union(unit):
    """这句话所有行框的并集（PDF 坐标），仅用于判断框是否移动过"""
    bx = [[r[0], r[1], r[2], r[3]] for r in unit['rects']]
    return [min(b[0] for b in bx), min(b[1] for b in bx), max(b[2] for b in bx), max(b[3] for b in bx)]


def pdf_boxes(unit):
    """这句话【每一行各自的框】，**单位与 render_frame 内的 boxes 一致**（源图像素 = PDF 坐标 × PAGE_SCALE）。

    ★ 2026-09-30 修复（两个 bug 一起）：
      ① 单位：原 `pdf_union` 返回的是 PDF 点（未乘 PAGE_SCALE），却被当作"源图像素"传给 render_frame，
         于是过渡期的框被画在"一半坐标"上 —— 视觉上就是"高亮闪到左上角、还变小/变扁"，
         而终帧（走的是已缩放的 boxes）位置正确 → 看起来就是"闪一下再归位"。
      ② 形状：原来插值的是"上一句并集 → 本句并集"，跨行句在过渡期只能画出一个大黄块（"框会扩大"）；
         改为逐行插值，全程保持多行形状。"""
    return [[r[0] * PAGE_SCALE, r[1] * PAGE_SCALE, r[2] * PAGE_SCALE, r[3] * PAGE_SCALE]
            for r in unit['rects']]


def _align_boxes(prev, cur):
    """把两句话的行框列表补到同样长度，便于逐行插值。
    短的一边用自己最后一个框补齐（视觉上就是"多出来的框从最后一个位置长出来"）。"""
    n = max(len(prev), len(cur))
    P = [prev[min(i, len(prev) - 1)] for i in range(n)]
    C = [cur[min(i, len(cur) - 1)] for i in range(n)]
    return P, C


def render_frame(unit, page, out_png, f_title, idx, total, srt_text,
                 top=None, hl_alpha=78, sub_alpha=255, box=None):
    src = Image.open(page['img']).convert('RGB')
    sw, sh = src.size
    q = W / sw                                     # 显示缩放
    win_h = int(IMG_H / q)
    # 高亮框（PDF 坐标 → 源图像素）
    boxes = [[r[0] * PAGE_SCALE, r[1] * PAGE_SCALE, r[2] * PAGE_SCALE, r[3] * PAGE_SCALE]
             for r in unit['rects']]
    if top is None:
        top = target_top(unit, page)
    top = int(top)
    top = max(0, min(top, max(0, sh - win_h)))
    crop = src.crop((0, top, sw, min(sh, top + win_h)))
    canvas = Image.new('RGB', (W, H), (16, 18, 24))
    # 图像区先铺"纸白"，页码不足一屏时不会露出黑底
    d0 = ImageDraw.Draw(canvas)
    d0.rectangle([0, 0, W, IMG_H], fill=(255, 255, 255))
    canvas.paste(crop.resize((W, int(crop.height * q)), Image.LANCZOS), (0, 0))
    d = ImageDraw.Draw(canvas, 'RGBA')
    # box 可以是【一组】矩形（逐行插值用）；为空则退回本句自身的每个行框
    draw_boxes = box if box else boxes
    for b in draw_boxes:
        x0 = int(b[0] * q) - 3; yy0 = int((b[1] - top) * q) - 3
        x1 = int(b[2] * q) + 3; yy1 = int((b[3] - top) * q) + 3
        if yy1 < 0 or yy0 > IMG_H:
            continue
        d.rectangle([x0, yy0, x1, yy1], fill=(255, 214, 0, int(hl_alpha)), outline=(255, 160, 0, 235), width=3)
    # 字幕
    sub_h = H - SUB_TOP - 26
    f = ImageFont.truetype(FONT_PATH, SUB_FONT)
    fl = _wrap(d, srt_text, f, W - 120)
    if len(fl) > 3:
        fl = fl[:3]
    lh = int(SUB_FONT * 1.38)
    ty = SUB_TOP + max(0, (sub_h - len(fl) * lh) // 2)
    for i, ln in enumerate(fl):
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2 + 2, ty + i * lh + 2), ln, font=f, fill=(0, 0, 0, int(sub_alpha * 0.8)))
        d.text(((W - tw) / 2, ty + i * lh), ln, font=f, fill=(255, 255, 255, int(sub_alpha)))
    # 顶部信息 + 进度
    fb = ImageFont.truetype(FONT_BOLD, 21)
    d.rectangle([0, 0, W, 6], fill=(90, 160, 255, 255))
    hdr = '%s ｜ 第 %d/%d 句 ｜ 第 %d 页' % (f_title, idx, total, unit['page'] + 1)
    d.text((20, 16), hdr, font=fb, fill=(255, 255, 255))
    bar = int((W - 40) * idx / max(total, 1))
    d.rectangle([20, 46, 20 + bar, 50], fill=(255, 214, 0, 235))
    canvas.save(out_png)


# ============ 4) 主流程 ============
def build(pdf_path, out_dir, voice='zh-CN-YunxiNeural', rate='+0%',
          max_seconds=MAX_PART_SECONDS, title=None, progress=None, proxy=''):
    def rep(msg, pct=None):
        if progress:
            progress(msg, pct)
        print('[pipeline]', msg, flush=True)

    if proxy:
        os.environ['HTTPS_PROXY'] = proxy
        os.environ['HTTP_PROXY'] = proxy

    os.makedirs(out_dir, exist_ok=True)
    title = title or os.path.splitext(os.path.basename(pdf_path))[0]
    rep('解析 PDF …', 2)
    data = extract_units(pdf_path, os.path.join(out_dir, 'pages'), progress=progress)
    units, pages = data['units'], data['pages']
    if not units:
        raise RuntimeError('这个 PDF 里没有提取到可朗读的文字（可能是扫描件，需要 OCR）')
    total_chars = sum(len(u['text']) for u in units)
    rep('提取到 %d 句 / %d 页 / %d 字' % (len(units), len(pages), total_chars), 32)

    # --- TTS + PCM 层拼装（时间轴 = 音频，误差为零）---
    seg_dir = os.path.join(out_dir, 'segs'); os.makedirs(seg_dir, exist_ok=True)
    gap_pcm = np.zeros(int(SENT_GAP * SR_AUDIO), dtype=np.float32)
    durs, segs = [], []
    for i, u in enumerate(units):
        mp3 = os.path.join(seg_dir, 's%05d.mp3' % i)
        if not (os.path.exists(mp3) and os.path.getsize(mp3) > 800):
            if not tts_sentence(u['text'], mp3, voice, rate):
                rep('⚠️ 第 %d 句合成失败，跳过' % (i + 1))
                durs.append(0.0); segs.append(None); continue
        # 解码 → VAD 裁首尾静音 → 存成"净语音"wav（每句只做一次，可复用）
        sw = os.path.join(seg_dir, 's%05d.trim.wav' % i)
        if not (os.path.exists(sw) and os.path.getsize(sw) > 2000):
            ys, _ = trim_pcm(decode_pcm(mp3))
            write_wav(sw, ys)
        n = os.path.getsize(sw) - 44                     # WAV 头 44 字节 → 样本数
        durs.append((n // 2) / float(SR_AUDIO) + SENT_GAP)
        segs.append(sw)
        if (i + 1) % 5 == 0 or i + 1 == len(units):
            rep('合成语音 %d/%d（已 %.1f 分钟）' % (i + 1, len(units), sum(durs) / 60),
                32 + 48 * (i + 1) / len(units))

    # --- 分卷 ---
    parts, cur, acc = [], [], 0.0
    for i, d in enumerate(durs):
        if cur and acc + d > max_seconds:
            parts.append(cur); cur, acc = [], 0.0
        cur.append(i); acc += d
    if cur:
        parts.append(cur)
    rep('共 %d 卷（总时长 %.1f 分钟）' % (len(parts), sum(durs) / 60), 82)

    # --- 逐卷渲染 + 合成 ---
    quiet = ' -hide_banner -loglevel error '
    results = []
    for pi, idxs in enumerate(parts, 1):
        fdir = os.path.join(out_dir, 'frames_%02d' % pi)
        os.makedirs(fdir, exist_ok=True)
        base = '%s_第%d卷' % (_safe(title), pi)
        files, srt = [], []
        t = 0.0
        seq = []            # [(png, 时长秒)]：一句话可能对应多张图（句内平滑滚动 + 淡入）
        prev_top, prev_page, prev_box, prev_lines, n_sent = None, None, None, None, 0
        for k, i in enumerate(idxs, 1):
            if segs[i] is None:
                continue
            n_sent += 1
            unit, page = units[i], pages[units[i]['page']]
            tgt, dur = target_top(unit, page), durs[i]
            same_page = (prev_page is None) or (unit['page'] == prev_page)
            cur_box = pdf_union(unit)
            box_moved = same_page and prev_box is not None and any(abs(a - b) >= 3 for a, b in zip(cur_box, prev_box))
            need_pan = (prev_top is not None) and same_page and abs(tgt - prev_top) >= 2
            need_move = need_pan or box_moved
            if need_move:
                T = min(0.5, max(0.22, 0.45 * dur))          # 过渡时长
                if T > dur - 0.15:
                    T = max(0.12, dur - 0.15)
                steps = max(3, int(round(T * 20)))           # 过渡期 20fps
                base_top = prev_top if prev_top is not None else tgt
                # ★ 逐行插值（2026-09-30 修复）：
                #   以前 base_box/cur_box 都取"并集"，过渡期永远只能画一个矩形；
                #   跨行句在终帧却变成多个精确行框 → 视觉上"闪一下、框扩大、再归位"。
                #   改为把上一句的每一行框插值到本句的每一行框，全程保持多行形状。
                base_lines = prev_lines if prev_lines is not None else pdf_boxes(unit)
                cur_lines = pdf_boxes(unit)
                P, C = _align_boxes(base_lines, cur_lines)
                for st in range(1, steps + 1):
                    fr = st / steps
                    ease = 0.5 - 0.5 * math.cos(math.pi * fr)      # ease-in-out
                    top_s = base_top + (tgt - base_top) * ease
                    bx_list = [[a + (b - a) * ease for a, b in zip(p, c)] for p, c in zip(P, C)]
                    png = os.path.join(fdir, 'f%05d_%02d.png' % (i, st))
                    render_frame(unit, page, png, title, k, len(idxs), unit['text'],
                                 top=top_s, box=bx_list,
                                 hl_alpha=int(78 * (0.30 + 0.70 * fr)),
                                 sub_alpha=int(255 * min(1.0, 0.35 + 0.65 * fr)))
                    seq.append((png, T / steps))
                rest = dur - T
                if rest > 0.02:
                    png = os.path.join(fdir, 'f%05d_end.png' % i)
                    render_frame(unit, page, png, title, k, len(idxs), unit['text'], top=tgt)
                    seq.append((png, rest))
            else:
                png = os.path.join(fdir, 'f%05d.png' % i)
                render_frame(unit, page, png, title, k, len(idxs), unit['text'], top=tgt)
                seq.append((png, dur))
            prev_top, prev_page, prev_box = tgt, unit['page'], cur_box
            prev_lines = pdf_boxes(unit)
            srt.append((t, t + dur, unit['text'])); t += dur
        files = [q_ for q_, _ in seq]
        lst = os.path.join(fdir, 'list.txt')
        # ⚠️ 每帧必须带 duration（否则 concat 后只剩 1 帧/图 → 成片不到 1 秒）；
        #    末尾再重复一次最后一个文件（concat demuxer 已知坑：末项时长会被忽略）
        with open(lst, 'w', encoding='utf-8') as fh:
            for png, dd in seq:
                # ⚠️ 必须绝对路径：ffmpeg concat 按「清单文件所在目录」解析相对路径
                fh.write("file '%s'\nduration %.3f\n"
                         % (os.path.abspath(png).replace('\\', '/'), dd))
            if seq:
                fh.write("file '%s'\n" % os.path.abspath(seq[-1][0]).replace('\\', '/'))
        # 音频：按计划精确拼出整卷 PCM（每句净语音 + 精确停顿，与上面帧时长逐一对应）
        total_n = int(round(sum(durs[i] for i in idxs) * SR_AUDIO))
        wav_buf = np.zeros(max(1, total_n), dtype=np.float32)
        pos = 0
        for i in idxs:
            if segs[i] is None:
                continue
            y = decode_pcm(segs[i])
            k = max(0, min(len(y), total_n - pos))
            wav_buf[pos:pos + k] = y[:k]; pos += k
            g = gap_pcm[:max(0, min(len(gap_pcm), total_n - pos))]
            wav_buf[pos:pos + len(g)] = g; pos += len(g)
        wav_path = os.path.join(out_dir, base + '.wav')
        write_wav(wav_path, wav_buf)
        # 纯音频（整卷只编码一次 → 不再有逐段编码延迟累积）
        smp3 = os.path.join(out_dir, base + '_纯音频.mp3')
        _run('%s -y -v error -i "%s" -ac 1 -ar %d -b:a 64k "%s"' % (FFMPEG, wav_path, SR_AUDIO, smp3))
        mp4 = os.path.join(out_dir, base + '.mp4')
        mp4 = os.path.abspath(mp4)
        cmd = ('%s -y -f concat -safe 0 -i "%s" -i "%s" -vf "fps=30,format=yuv420p" '
               '-c:v libx264 -preset veryfast -crf 27 -c:a aac -b:a 128k -shortest "%s"%s'
               % (FFMPEG, os.path.abspath(lst), wav_path, mp4, quiet))
        _run(cmd)
        sp = os.path.join(out_dir, base + '.srt')
        with open(sp, 'w', encoding='utf-8') as fh:
            for n, (a, b, tx) in enumerate(srt, 1):
                fh.write('%d\n%s --> %s\n%s\n\n' % (n, _ts(a), _ts(b), tx))
        results.append({'part': pi, 'video': mp4, 'srt': sp, 'audio': smp3,
                        'seconds': round(t, 1), 'sentences': n_sent})
        rep('第 %d/%d 卷完成（%.1f 分钟）' % (pi, len(parts), t / 60), 82 + 18 * pi / len(parts))

    summary = {'title': title, 'voice': voice, 'rate': rate,
               'units': len(units), 'pages': len(pages), 'chars': total_chars,
               'total_seconds': round(sum(durs), 1), 'parts': results}
    with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    rep('全部完成', 100)
    return summary


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]', '_', s)[:60]


def _run(cmd):
    """跑 ffmpeg 并检查退出码：失败就把 stderr 抛出来（别等到后面 FileNotFoundError 才发现）"""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('ffmpeg 失败（exit %s）：%s\n%s'
                           % (r.returncode, cmd[:220], (r.stderr or '')[-500:]))
    return r


def _ts(x):
    ms = int(round(x * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('-o', '--out', default='out')
    ap.add_argument('--voice', default='zh-CN-YunxiNeural')
    ap.add_argument('--rate', default='+0%')
    ap.add_argument('--max-seconds', type=int, default=MAX_PART_SECONDS)
    a = ap.parse_args()
    s = build(a.pdf, a.out, a.voice, a.rate, a.max_seconds)
    print(json.dumps({k: v for k, v in s.items() if k != 'parts'}, ensure_ascii=False))
