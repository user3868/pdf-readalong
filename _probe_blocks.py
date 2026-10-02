# -*- coding: utf-8 -*-
"""证实根因：PDF 的 rawdict 到底把每段文字切成几个 block？"""
from pathlib import Path
import pymupdf

pdf = Path(__file__).resolve().parent / "assets" / "演示文档.pdf"
doc = pymupdf.open(pdf)
for pno in range(doc.page_count):
    p = doc[pno]
    d = p.get_text("rawdict")
    blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]
    print(f"\n=== 第 {pno+1} 页：{len(blocks)} 个 block ===")
    for i, b in enumerate(blocks):
        txt = ""
        nlines = 0
        for ln in b.get("lines", []):
            nlines += 1
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []) or []:
                    if ch.get("c"):
                        txt += ch["c"]
        print(f"  block[{i}] 行数={nlines} 字符数={len(txt)}")
        print(f"     「{txt[:70]}{'…' if len(txt) > 70 else ''}」")
