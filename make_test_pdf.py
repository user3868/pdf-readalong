#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一个测试 PDF（含标题/正文/表格），用于端到端验证"""
import os

import pymupdf as fitz

doc = fitz.open()
page = doc.new_page()
FONT = 'china-s'          # 内置简体中文字体
y = 60
def line(txt, size=11, bold=False, dy=None):
    global y
    page.insert_textbox(fitz.Rect(50, y, 545, y + 300), txt,
                        fontname='china-s', fontsize=size, lineheight=1.5)
    # 粗略估算高度
    h = int(len(txt) / 30 + 1) * (size * 1.6) + 6
    y += (dy if dy is not None else h)

page.insert_textbox(fitz.Rect(50, 50, 545, 90), '打标签方法论 · 测试文档',
                    fontname='china-s', fontsize=18)
y = 95
line('数据标注的核心难点，是把模糊的业务概念变成可重复的判断。模型可以承担候选生成、规则执行、难例筛选和质量检查；人的工作则集中在定义、校准、例外与独立验收这几件事情上。')
line('不同领域不能按自动化率简单排队。判断评论态度、审阅合同特权、勾画病灶和记录机器人动作，所需知识、标签来源和错误代价都不同。医疗标注往往需要多读者独立读片，然后由第三方裁决分歧；法律取证强调的是可辩护性，也就是流程能不能向法院解释清楚。')
line('一致性指标告诉我们标注者之间是否可比，但它不等于正确率。当一致性系数低于零点六六七时，通常说明定义本身需要重写，而不是继续加标注人力。')
page = doc.new_page()
page.insert_textbox(fitz.Rect(50, 50, 545, 90), '二、小团队的落地做法', fontname='china-s', fontsize=15)
page.insert_textbox(fitz.Rect(50, 95, 545, 400),
    '先写一份两到四页的标注手册，把每个标签的定义、对象、正反例和困难例写清楚。'
    '然后留出独立的评测集，不要展示模型建议，也不要用它反复调提示词。'
    '生产批次可以让模型先预标注，再由人工随机盲审百分之二十，歧义、缺上下文和罕见类别单独加审。'
    '最后，一致性、正确性和分歧要分别报告，不要把有意义的不同意见裁决掉。',
    fontname='china-s', fontsize=11, lineheight=1.6)
doc.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), '测试文档.pdf'))
print('已生成 测试文档.pdf，页数', doc.page_count)
