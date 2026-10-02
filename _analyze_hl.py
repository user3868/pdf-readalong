# -*- coding: utf-8 -*-
"""逐帧检测高亮框的像素位置与尺寸，找出异常帧（闪到左上角 / 异常扩大）"""
import sys, glob, os
import numpy as np
from PIL import Image

frames_dir = sys.argv[1]
files = sorted(glob.glob(os.path.join(frames_dir, '*.png')))
print(f"帧数: {len(files)}")

rows = []
for f in files:
    im = np.asarray(Image.open(f).convert('RGB'))
    # 只在上半屏（图像区 0..500）里找"高亮黄"：
    # 半透明黄底 覆盖在纸白上 → 偏 (255,240,120) 一类；橙框 → (255,160,0)
    top = im[:500, :, :].astype(np.int16)
    r, g, b = top[:, :, 0], top[:, :, 1], top[:, :, 2]
    # 橙色描边最容易识别：R 高、B 很低、G 中等
    mask = (r > 200) & (b < 110) & (g > 110) & (g < 215)
    ys, xs = np.nonzero(mask)
    name = os.path.basename(f)
    if len(xs) == 0:
        rows.append((name, None, None, None, None, None, 0))
    else:
        rows.append((name, int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()),
                     int(len(xs)), 1))

# 打印可疑帧：框贴到左边缘 / 面积异常 / 缺失
print("\n=== 可疑帧（框贴左上角、缺失、或面积突变）===")
areas = [ (r[3]-r[1])*(r[4]-r[2]) if r[6] else 0 for r in rows ]
med = sorted([a for a in areas if a > 0])
med = med[len(med)//2] if med else 0
print(f"  面积中位数 = {med}")
bad = []
for r in rows:
    name, x0, y0, x1, y1, px, ok = r
    if not ok:
        bad.append((name, '未检出高亮框'))
        continue
    area = (x1 - x0) * (y1 - y0)
    if x0 <= 6 or y0 <= 6:
        bad.append((name, f'贴边 x0={x0} y0={y0}  box=({x0},{y0},{x1},{y1})'))
    elif med and (area > med * 2.2 or area < med * 0.35):
        bad.append((name, f'面积异常 {area} vs 中位 {med}  box=({x0},{y0},{x1},{y1})'))

print(f"  可疑帧数: {len(bad)}")
for n, why in bad[:30]:
    print(f"    {n}: {why}")

# 输出时间序列，便于看趋势
print("\n=== 前 40 帧的框位置 ===")
for r in rows[:40]:
    name, x0, y0, x1, y1, px, ok = r
    if ok:
        print(f"  {name}  x[{x0:4d},{x1:4d}] y[{y0:4d},{y1:4d}]  w={x1-x0:4d} h={y1-y0:4d}")
    else:
        print(f"  {name}  —— 无框")
