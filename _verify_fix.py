# -*- coding: utf-8 -*-
"""快速验证断句修复：只跑 extract_units，检查还有没有"词中间被切断"的句子"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
import pipeline

r = pipeline.extract_units(os.path.join(HERE, 'assets', '演示文档.pdf'), '_unitcheck')
units = r['units']
print(f"共提取 {len(units)} 个朗读单元\n")

END = "。！？；"
titles = []
ok, suspect = [], []
for u in units:
    t = u['text']
    k = u.get('kind')
    if k == 'table':
        continue
    if t and t[-1] in END:
        ok.append(t)
    else:
        suspect.append(t)

print(f"以句末标点结尾: {len(ok)}")
print(f"其它(标题/半句): {len(suspect)}\n")
print("--- 其它清单（标题应当在此，半句不应该）---")
for t in suspect:
    print(f"  「{t}」")

print("\n--- 完整句节选（检查是否已合成长句）---")
for t in ok[:8]:
    print(f"  「{t[:60]}{'…' if len(t)>60 else ''}」")

# 关键判据：随机抽取若干句，检查是否在"词中间"结束（后一个字不是标点即算可疑）
print("\n--- 判定 ---")
# 真正的半句特征：结尾不是标点，且长度 > 12（标题通常短）
real_bad = [t for t in suspect if len(t) > 12]
print(f"  长度>12 且不以标点结尾的（真半句）= {len(real_bad)}")
for t in real_bad:
    print(f"    ✗ 「{t}」")
if not real_bad:
    print("    ✓ 无真半句，修复生效")
