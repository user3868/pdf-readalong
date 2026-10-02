#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_sync.py —— 量"字幕时间轴"与"真实语音"差几秒（全部从音频本身算，不下载大模型）

路线（用现成成品，不自研算法）：
 ① 能量分段（librosa）：把音轨切成"说话岛"——每句 TTS 之间天然有静音，所以岛≈句
 ② 逐岛用 FunASR paraformer-zh 转写成文字（已缓存，不触发大模型下载）
 ③ 解析 SRT，用文本相似度把"岛"与"字幕条"配对
 ④ 报偏移 = 岛起点(真实语音起点) − 字幕起点；正=字幕早了，负=字幕晚了
 ⑤ 附带：句子之间静音长度、字幕覆盖是否有空档/重叠

用法： python measure_sync.py 视频.mp4 [--report out.json] [--topdb 30]
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import wave

import numpy as np

FFMPEG = r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
SR = 16000


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('失败: %s\n%s' % (cmd[:200], (r.stderr or '')[-500:]))
    return r.stdout


def to_wav(src, dst, sr=SR):
    run('%s -y -v error -i "%s" -vn -ac 1 -ar %d -c:a pcm_s16le "%s"' % (FFMPEG, src, sr, dst))
    return dst


def read_wav(path):
    with wave.open(path, 'rb') as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    if w.getsampwidth() == 2:
        y = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        y = np.frombuffer(data, dtype=np.int32).astype(np.float32) / 2147483648.0
    return y, sr


def write_wav(path, y, sr):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def parse_srt(path):
    raw = open(path, encoding='utf-8-sig', errors='ignore').read().replace('\r\n', '\n').replace('\r', '\n')
    items = []
    for blk in re.split(r'\n\s*\n', raw.strip()):
        lines = [l for l in blk.split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', lines[1])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        st = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        en = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        items.append({'idx': len(items) + 1, 'start': st, 'end': en, 'text': ' '.join(lines[2:]).strip()})
    return items


def norm(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'[\s，。、；：！？,.;:!?"\'“”‘’()（）\[\]【】—-]', '', s)
    return s.strip()


def speech_islands(y, sr, top_db=30.0, min_len=0.30, min_gap=0.05, merge_gap=0.10):
    """能量分段：返回 [(start_s, end_s)]
    ⚠️ 不合并近邻会把多句并成一段（句间停顿很短时），合并太狠又会把一句切碎；
    merge_gap 要小于句间停顿、大于句内自然停顿。"""
    import librosa
    ivs = librosa.effects.split(y, top_db=top_db, frame_length=1024, hop_length=256)
    out = []
    for a, b in ivs:
        st, en = a / sr, b / sr
        if en - st < min_len:
            continue
        if out and st - out[-1][1] < min_gap:
            out[-1] = (out[-1][0], en)
        else:
            out.append((st, en))
    merged = []
    for st, en in out:
        if merged and st - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], en)
        else:
            merged.append((st, en))
    return merged


_bundle = {}


def asr_text(wav_path):
    """FunASR 单句转写（只加载一次）"""
    if 'model' not in _bundle:
        from funasr import AutoModel
        _bundle['model'] = AutoModel(model='paraformer-zh', device='cpu', disable_update=True)
    res = _bundle['model'].generate(input=wav_path, batch_size_s=30)
    return (res[0].get('text') or '').strip() if res else ''


def first_sound(y, sr, t0, win=2.5, floor=5e-4, sil_run=0.08):
    """找"真正的出声起点"：先跳过延续过来的上一句，再找第一段≥sil_run 的静音之后的声音。
    ⚠️ 若只用"窗口内第一个非静音采样"，窗口左边界会把上一句尾音算进来（会报 -0.25s 假值）。"""
    a = max(0, int((t0 - 0.3) * sr))
    b = min(len(y), int((t0 + win) * sr))
    if b <= a:
        return None
    above = np.abs(y[a:b]) > floor
    need = max(1, int(sil_run * sr))
    i = 0
    n = len(above)
    while i < n:
        if not above[i]:
            j = i
            while j < n and not above[j]:
                j += 1
            if j - i >= need:
                k = j
                while k < n and not above[k]:
                    k += 1
                if k < n:
                    return (a + k) / float(sr) - t0
            i = j
        else:
            i += 1
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--report', default=None)
    ap.add_argument('--topdb', type=float, default=30.0)
    ap.add_argument('--fast', action='store_true', help='跳过转写，只做"字幕→出声"的音频判定')
    a = ap.parse_args()

    v = os.path.abspath(a.video)
    srt = os.path.splitext(v)[0] + '.srt'
    if not os.path.exists(srt):
        raise SystemExit('找不到字幕：%s' % srt)

    wav = to_wav(v, v + '._sync.wav')
    y, sr = read_wav(wav)
    dur = len(y) / sr
    print('① 音频：%.2fs（16k 单声道）｜字幕：%s' % (dur, os.path.basename(srt)))

    isl = speech_islands(y, sr, a.topdb)
    total_speech = sum(b - a2 for a2, b in isl)
    print('② 能量分段：%d 段语音，语音总长 %.1fs，静音合计 %.1fs（占 %.0f%%）'
          % (len(isl), total_speech, dur - total_speech, 100 * (dur - total_speech) / dur))
    gaps = [isl[i + 1][0] - isl[i][1] for i in range(len(isl) - 1)]
    if gaps:
        print('   句间静音：中位 %.2fs ｜ 均值 %.2fs ｜ 最大 %.2fs'
              % (float(np.median(gaps)), float(np.mean(gaps)), float(np.max(gaps))))

    srt_items = parse_srt(srt)

    # ⑥ 硬指标：每条字幕亮起后，多久才听到第一个声音（逐采样判定，不用分段）
    rows = []
    for s in srt_items:
        d = first_sound(y, sr, s['start'])
        rows.append((s['start'], d))
    waits = [r[1] for r in rows if r[1] is not None]
    if waits:
        w = np.array(waits)
        print('\n⑥ 字幕亮起→出声（硬判定）：%d 条 ｜ 中位 %+.3fs ｜ 均值 %+.3fs ｜ 最大 %+.3fs ｜ >0.5s 的 %d 条'
              % (len(w), float(np.median(w)), w.mean(), w.max(), int((w > 0.5).sum())))
        print('   明细：%s' % ', '.join('%+.2f' % x for x in waits))
        worst = sorted([r for r in rows if r[1] is not None], key=lambda r: -r[1])[:3]
        for t0, dd in worst:
            print('   最晚的几条：字幕 %.2fs → 出声 +%.2fs' % (t0, dd))

    if a.fast:
        for f in (wav,):
            try:
                os.remove(f)
            except Exception:
                pass
        return

    # 逐岛转写
    tmp = v + '._one.wav'
    islands = []
    for i, (st, en) in enumerate(isl):
        seg = y[int((st - 0.05) * sr) if st > 0.05 else 0:int((en + 0.15) * sr)]
        write_wav(tmp, seg, sr)
        txt = asr_text(tmp)
        islands.append({'start': st, 'end': en, 'text': txt})
        print('   岛%02d %6.2f→%6.2f (%.2fs)  %s' % (i + 1, st, en, en - st, txt[:34]))

    srt_items = parse_srt(srt)
    used = set()
    pairs = []
    for it in islands:
        t = norm(it['text'])
        if len(t) < 3:
            continue
        best, bs = None, 0.0
        for j, s in enumerate(srt_items):
            if j in used:
                continue
            r = difflib.SequenceMatcher(None, t, norm(s['text'])).ratio()
            if r > bs:
                best, bs = j, r
        if best is not None and bs >= 0.5:
            used.add(best)
            s = srt_items[best]
            pairs.append({'island_start': round(it['start'], 3), 'island_end': round(it['end'], 3),
                          'asr': it['text'], 'srt_idx': s['idx'], 'srt_start': s['start'], 'srt_end': s['end'],
                          'srt': s['text'], 'off_start': round(it['start'] - s['start'], 3),
                          'off_end': round(it['end'] - s['end'], 3), 'sim': round(bs, 2)})

    print('\n③ 逐条偏移（偏移 = 真实语音起点 − 字幕起点；正=字幕早了，负=字幕晚了）')
    for p in pairs:
        print('   字幕%5.2f→%5.2f 真实%5.2f→%5.2f 偏%+5.2f/%+5.2fs 相似%.2f ｜%s'
              % (p['srt_start'], p['srt_end'], p['island_start'], p['island_end'],
                 p['off_start'], p['off_end'], p['sim'], p['asr'][:22]))

    if pairs:
        offs = np.array([p['off_start'] for p in pairs])
        ts = np.array([p['srt_start'] for p in pairs])
        slope = float(np.polyfit(ts, offs, 1)[0]) if len(pairs) > 2 else 0.0
        print('\n④ 汇总（起点偏移）配对 %d 条' % len(pairs))
        print('   均值 %+.3fs ｜ 中位 %+.3fs ｜ 最大 %+.3fs ｜ 最小 %+.3fs'
              % (offs.mean(), float(np.median(offs)), offs.max(), offs.min()))
        print('   漂移斜率 %+.4f s/s → %s' % (slope, '有累积漂移' if abs(slope) > 0.02 else '无累积漂移（固定偏移）'))
        print('   |偏移|>1s：%d 条 ｜ >2s：%d 条' % (int((np.abs(offs) > 1).sum()), int((np.abs(offs) > 2).sum())))

    # 字幕覆盖检查
    cov_gaps = []
    for i in range(len(srt_items) - 1):
        g = srt_items[i + 1]['start'] - srt_items[i]['end']
        if g > 0.05:
            cov_gaps.append(round(g, 3))
    print('\n⑤ 字幕连续性：条间空档 %d 处 ｜ 最大 %.3fs ｜ 字幕末条结束 %.2fs vs 音频 %.2fs'
          % (len(cov_gaps), max(cov_gaps) if cov_gaps else 0.0, srt_items[-1]['end'], dur))

    # ⑥ 直接指标：每条字幕亮起后，多久才听到声音（不依赖文本配对）
    wait = []
    for s in srt_items:
        cand = [i['start'] for i in islands if i['start'] >= s['start'] - 0.25]
        if cand:
            wait.append(round(min(cand) - s['start'], 3))
    if wait:
        w = np.array(wait)
        print('\n⑥ 字幕亮起→出声 的等待：配对 %d 条 ｜ 中位 %+.3fs ｜ 均值 %+.3fs ｜ 最大 %+.3fs ｜ >1s 的 %d 条'
              % (len(wait), float(np.median(w)), w.mean(), w.max(), int((w > 1).sum())))
        print('   明细：%s' % ', '.join('%+.2f' % x for x in wait))

    if a.report:
        with open(a.report, 'w', encoding='utf-8') as fh:
            json.dump({'video': v, 'duration': dur, 'islands': islands, 'srt': srt_items,
                       'pairs': pairs}, fh, ensure_ascii=False, indent=2)
        print('\n报告：%s' % a.report)
    for f in (wav, tmp):
        try:
            os.remove(f)
        except Exception:
            pass


if __name__ == '__main__':
    main()
