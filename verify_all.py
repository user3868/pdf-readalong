#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_all.py —— 交付前/写稿前的"重新核验"：把要写进文字稿的关键数字全部重测一遍
输出一张紧凑的核对表（每项附证据来源）
"""
import json
import os
import re
import subprocess
import sys
import wave

import numpy as np

FF = r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
FP = r'C:\ProgramData\chocolatey\bin\ffprobe.exe'
HERE = os.path.dirname(os.path.abspath(__file__))


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def dur(p):
    return float(sh('"%s" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "%s"' % (FP, p)))


def stream_durs(p):
    out = sh('"%s" -v error -show_entries stream=codec_type,duration -of csv=p=0 "%s"' % (FP, p))
    d = {}
    for ln in out.splitlines():
        a = ln.split(',')
        if len(a) == 2:
            try:
                d[a[0]] = float(a[1])
            except Exception:
                pass
    return d


def audio_mono(p, sr=24000):
    tmp = p + '._v.wav'
    sh('"%s" -y -v error -i "%s" -ac 1 -ar %d -c:a pcm_s16le "%s"' % (FF, p, sr, tmp))
    with wave.open(tmp, 'rb') as w:
        y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    os.remove(tmp)
    return y, sr


def lvl(y, sr, a, b):
    seg = y[int(a * sr):int(b * sr)]
    return float(np.sqrt((seg ** 2).mean() + 1e-12)) if len(seg) else 0.0


def main():
    print('=' * 78)
    print('重新核验清单（本脚本刚跑的数据，不是引用旧日志）')
    print('=' * 78)

    # 1) 产品成片：旧版 vs 新版 的三条时间线
    old = os.path.join(HERE, 'jobs', 'cd3d538229', '演示文档_第1卷.mp4')
    new = os.path.join(HERE, '_fixed_out', '演示文档_第1卷.mp4')
    for tag, p in (('旧版(修前)', old), ('新版(修后)', new)):
        if not os.path.exists(p):
            print('  ⚠️ 缺文件：%s' % p); continue
        s = stream_durs(p)
        srt = os.path.splitext(p)[0] + '.srt'
        end = 0.0
        if os.path.exists(srt):
            ms = re.findall(r'(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)',
                            open(srt, encoding='utf-8').read().replace('\r\n', '\n'))
            if ms:
                h, mi, ss, mss = map(int, ms[-1][4:8])
                end = h * 3600 + mi * 60 + ss + mss / 1000
        print('  【%s】视频 %.2fs ｜ 音频 %.2fs ｜ 字幕末条 %.2fs ｜ 视频-字幕 差 %.2fs'
              % (tag, s.get('video', 0), s.get('audio', 0), end, s.get('video', 0) - end))

    # 2) 演示片：直接从交付片里按"字幕窗口"量能量（素材声段应明显有声；纯解说段只有解说）
    demo = os.path.join(HERE, '演示_全流程_实时原声版.mp4')
    if os.path.exists(demo):
        y, sr = audio_mono(demo)
        print('  【演示片】时长 %.2fs' % (len(y) / sr))
        srt = os.path.splitext(demo)[0] + '.srt'
        raw = open(srt, encoding='utf-8').read().replace('\r\n', '\n')
        for blk in [b for b in raw.strip().split('\n\n') if b.strip()]:
            L = [x for x in blk.split('\n') if x.strip()]
            m = re.search(r'(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)', L[1])
            a = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
            b2 = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000
            txt = ' '.join(L[2:])
            tag = '素材声段' if ('试听' in txt or '直接播放' in txt) else ('快进段' if '正在生成' in txt else '解说段')
            print('     %-6s %6.2f→%6.2f ｜ 能量 %.4f ｜ %s' % (tag, a, b2, lvl(y, sr, max(0, a - 0.3), b2), txt[:22]))

    # 3) 文件清单（证据索引）
    print('\n证据文件：')
    for f in sorted(os.listdir(HERE)):
        if f.startswith('_') and os.path.isfile(os.path.join(HERE, f)):
            print('   %-42s %8.1f KB' % (f, os.path.getsize(os.path.join(HERE, f)) / 1024))
    print('=' * 78)


if __name__ == '__main__':
    main()
