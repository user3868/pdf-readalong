#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成本次演示要用的 PDF：3 页、含标题/正文/表格，用来演示"长文档 → 跟读视频"。
文件名固定为 演示文档.pdf（record_demo.py 里写死了这个名）。
"""
import os

import pymupdf as fitz

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '演示文档.pdf')
FONT = 'china-s'

doc = fitz.open()

# ---------------- 第 1 页 ----------------
p = doc.new_page()
p.insert_textbox(fitz.Rect(50, 45, 545, 85), '长文档音频化：方法与取舍',
                 fontname=FONT, fontsize=19)
p.insert_textbox(fitz.Rect(50, 88, 545, 108), '一份给内容团队的做法说明',
                 fontname=FONT, fontsize=11)

body1 = (
    '把一份几十页的材料变成"能听的"，看起来只是加一段语音，实际要先回答一个问题：'
    '听的人手上有多少注意力。通勤、做家务、走路的时候，眼睛是占着的，能用的只有耳朵。'
    '所以音频化不是把文字念一遍，而是把"必须看着才能懂"的内容，重排成"闭着眼也能跟得上"的顺序。'
)
p.insert_textbox(fitz.Rect(50, 125, 545, 235), body1, fontname=FONT, fontsize=11, lineheight=1.6)

body2 = (
    '第一步是切句。切句不是按标点机械地砍，而是按"一口气能听完"的长度来切。'
    '一句太长，听的人记不住开头；一句太短，又会被切碎的停顿打断思路。'
    '实测下来，中文一句控制在二十到三十五个字，听着最省力。'
)
p.insert_textbox(fitz.Rect(50, 245, 545, 330), body2, fontname=FONT, fontsize=11, lineheight=1.6)

body3 = (
    '第二步是让耳朵知道现在念到哪了。声音本身给不出位置感，所以要配一个视觉锚点：'
    '原文就在屏幕上，念到哪一句，哪一句就被框起来。这样即使中途走神，抬眼一看就知道进度。'
)
p.insert_textbox(fitz.Rect(50, 340, 545, 430), body3, fontname=FONT, fontsize=11, lineheight=1.6)
p.insert_textbox(fitz.Rect(50, 440, 545, 460), '一、为什么要音频化', fontname=FONT, fontsize=13)
p.insert_textbox(fitz.Rect(50, 465, 545, 560),
                 '注意力是稀缺的。把内容从"必须看"改成"可以听"，等于把可用时间从屏幕前解锁到生活的其他时段。',
                 fontname=FONT, fontsize=11, lineheight=1.6)

# ---------------- 第 2 页：带表格 ----------------
p = doc.new_page()
p.insert_textbox(fitz.Rect(50, 45, 545, 80), '二、四种做法的取舍', fontname=FONT, fontsize=16)

rows = [
    ['做法', '上手成本', '适合的场景'],
    ['人工配音', '高', '品牌宣传、需要情绪表达'],
    ['通用 TTS 整段念', '低', '只听大意、不看原文'],
    ['逐句 TTS 配字幕', '中', '通勤听、需要跟读定位'],
    ['逐句 TTS 加高亮跟读', '中', '既要听、又要随时回到原文核对'],
]
# ★ 画成"真表格"：PyMuPDF 的 find_tables() 靠线条识别，
#   用文本框摆字会被当成普通正文（各列连成一串）。所以这里画网格线 + 单元格文字。
COLW = [150, 90, 255]
X0, Y0 = 50, 100
ROWH = 30
table_w = sum(COLW)
table_h = ROWH * len(rows)
# 竖线
for i in range(len(COLW) + 1):
    x = X0 + sum(COLW[:i])
    p.draw_line((x, Y0), (x, Y0 + table_h), color=(0.55, 0.55, 0.6), width=0.7)
# 横线
for j in range(len(rows) + 1):
    y = Y0 + ROWH * j
    p.draw_line((X0, y), (X0 + table_w, y), color=(0.55, 0.55, 0.6), width=0.7)
# 单元格文字
for r_i, row in enumerate(rows):
    cx = X0
    for c_i, cell in enumerate(row):
        p.insert_textbox(fitz.Rect(cx + 5, Y0 + ROWH * r_i + 7, cx + COLW[c_i] - 5, Y0 + ROWH * (r_i + 1) - 3),
                         cell, fontname=FONT, fontsize=10.5)
        cx += COLW[c_i]

y = Y0 + table_h

p.insert_textbox(fitz.Rect(50, y + 20, 545, y + 110),
                 '前三行的差别其实不在音质，而在"走神之后能不能接回来"。'
                 '整段念的音频，一旦走神就得从头再听；带高亮跟读的那种，抬眼看一下框在哪，就能接着听。'
                 '这就是它多出来的那点成本买的东西。',
                 fontname=FONT, fontsize=11, lineheight=1.6)

# ---------------- 第 3 页 ----------------
p = doc.new_page()
p.insert_textbox(fitz.Rect(50, 45, 545, 80), '三、落地时最容易踩的三个坑', fontname=FONT, fontsize=16)

for i, (h, t) in enumerate([
    ('第一个坑：句首句尾的静音',
     '语音合成出来的每一句，开头和结尾都自带一小段空白。如果按文件长度直接排时间轴，'
     '这些空白会越积越多，念到后面字幕就对不上了。正确做法是先解码成波形，掐掉首尾静音，再按真实长度拼。'),
    ('第二个坑：高亮只框到行',
     '如果高亮按"整行"来框，同一行里上一句的尾巴也会被一起框进去，看着就像框错了。'
     '要按字符的位置算出每一句真正覆盖的范围，框才准。'),
    ('第三个坑：句子中间的卡顿',
     '一句话只画一张图，听觉上连贯，视觉上却是"停住、突然跳一下"。'
     '要在一句之内做缓入缓出的过渡，把一次大的跳动拆成很多次小的位移，看起来才是平滑滚动。'),
]):
    yy = 95 + i * 150
    p.insert_textbox(fitz.Rect(50, yy, 545, yy + 28), h, fontname=FONT, fontsize=12)
    p.insert_textbox(fitz.Rect(50, yy + 32, 545, yy + 135), t, fontname=FONT, fontsize=11, lineheight=1.6)

doc.save(OUT)
print('已生成:', OUT, '｜页数', doc.page_count)
