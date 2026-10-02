#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qc_sheets.py —— 把成片抽帧拼成带时间戳的联系表，供我自己逐屏检查"""
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

FFMPEG = r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
FONT = r'C:\Windows\Fonts\msyhbd.ttc'


def sheet(video, out_prefix, every=1.6, cols=5, rows=5, cell=(420, 300)):
    tmp = os.path.join(os.path.dirname(video), '_qc')
    os.makedirs(tmp, exist_ok=True)
    dur = float(subprocess.run([FFMPEG.replace('ffmpeg.exe', 'ffprobe.exe'), '-v', 'error',
                                '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', video],
                               capture_output=True, text=True).stdout.strip())
    n = int(math.ceil(dur / every))
    per = cols * rows
    sheets = []
    for si in range(math.ceil(n / per)):
        canvas = Image.new('RGB', (cols * cell[0], rows * cell[1]), (0, 0, 0))
        d = ImageDraw.Draw(canvas)
        f = ImageFont.truetype(FONT, 20)
        for k in range(per):
            idx = si * per + k
            if idx >= n:
                break
            t = idx * every
            p = os.path.join(tmp, 'q%05d.jpg' % idx)
            subprocess.run('%s -y -v error -ss %.2f -i "%s" -frames:v 1 -vf scale=%d:-1 "%s"'
                           % (FFMPEG, t, video, cell[0], p), shell=True, capture_output=True)
            if not os.path.exists(p):
                continue
            im = Image.open(p).convert('RGB')
            x = (k % cols) * cell[0]
            y = (k // cols) * cell[1]
            canvas.paste(im.crop((0, 0, min(cell[0], im.width), min(cell[1], im.height))), (x, y))
            d.rectangle([x + 2, y + 2, x + 132, y + 30], fill=(0, 0, 0))
            d.text((x + 8, y + 5), '%5.1fs' % t, font=f, fill=(255, 220, 0))
        out = '%s_%d.png' % (out_prefix, si + 1)
        canvas.save(out)
        sheets.append(out)
        print(out)
    return sheets


if __name__ == '__main__':
    v = sys.argv[1] if len(sys.argv) > 1 else '演示_全流程_实时原声版.mp4'
    sheet(os.path.abspath(v), os.path.join(os.path.dirname(os.path.abspath(v)), '_qc_sheet'),
          every=float(sys.argv[2]) if len(sys.argv) > 2 else 1.6)
