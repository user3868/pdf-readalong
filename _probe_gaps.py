# -*- coding: utf-8 -*-
"""量每一行 block 的 bbox，算出"行内间距"与"段间距"，用来定合并阈值"""
from pathlib import Path
import pymupdf

pdf = Path(__file__).resolve().parent / "assets" / "演示文档.pdf"
doc = pymupdf.open(pdf)
p = doc[0]
d = p.get_text("rawdict")
blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]
print("block  y0     y1     h     字符数  文本片段")
prev = None
for i, b in enumerate(blocks):
    x0, y0, x1, y1 = b["bbox"]
    txt = "".join(ch["c"] for ln in b.get("lines", [])
                  for sp in ln.get("spans", []) for ch in (sp.get("chars") or []) if ch.get("c"))
    gap_s = (y0 - prev) if prev is not None else 0
    print(f"  [{i:2d}] {y0:6.1f} {y1:6.1f} {y1-y0:5.1f}  {len(txt):4d}   {txt[:26]}")
    if prev is not None:
        print(f"        └ 与上一行底部的间距 = {y0 - prev:.1f}")
    prev = y1
