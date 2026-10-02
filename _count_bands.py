# -*- coding: utf-8 -*-
"""按行统计橙色描边像素，数出每帧里有几条独立的高亮横带。
判据：修复前过渡帧只有 1 条（并集大矩形）；修复后跨行句应有 2 条（逐行）。"""
import sys, glob, os
import numpy as np
from PIL import Image

frames_dir = sys.argv[1]
pat = sys.argv[2] if len(sys.argv) > 2 else '*.png'
files = sorted(glob.glob(os.path.join(frames_dir, pat)))
print(f"检查 {len(files)} 帧：{os.path.basename(frames_dir)}/{pat}\n")

print(f"{'帧':<20} {'横带数':>6}  各带的行区间")
for f in files:
    im = np.asarray(Image.open(f).convert('RGB'))
    # 只看图像区，并排除顶部进度条所在的 y=40..56
    reg = im[6:500, :, :].astype(np.int16)
    r, g, b = reg[:, :, 0], reg[:, :, 1], reg[:, :, 2]
    mask = (r > 200) & (b < 120) & (g > 100) & (g < 220)
    # 屏蔽进度条带（原 y46..50 → 这里 y40..44）
    mask[38:50, :] = False
    rowcnt = mask.sum(axis=1)
    on = rowcnt > 3
    # 数连续的 on 段
    bands, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 2:
                bands.append((start + 6, i + 6))
            start = None
    if start is not None:
        bands.append((start + 6, len(on) + 6))
    name = os.path.basename(f)
    desc = '  '.join(f'y{a}..{b}' for a, b in bands) if bands else '（无）'
    print(f"{name:<20} {len(bands):>6}  {desc}")
