"""一次性隐私扫描：检查 workflow.json 里有没有不该出现的路径/用户名/主题词。"""
import json
import re
import sys

path = r'D:\IT\AI_vido\ComfyUI\life_inspiration_wan22_t2v.json'
with open(path, 'r', encoding='utf-8') as f:
    raw = f.read()

checks = [
    (r'[A-Z]:\\[^\"\s]+', 'Windows 绝对路径'),
    (r'/Users/\w+/[^\"\s]+', 'macOS 路径'),
    (r'/home/\w+/[^\"\s]+', 'Linux home 路径'),
    (r'[A-Z]:', 'Windows 盘符'),
    (r'chahax', 'GitHub 用户名'),
    (r'life_inspiration', '项目主题关键词（英文）'),
    (r'\u4eba\u751f\u6fc0\u52b1', '项目主题关键词（中文）'),
    (r'IT\\AI_vido', '本地机器路径段'),
    (r'\u90ed\u6df1', '作者姓名（猜）'),
]

print(f"文件: {path}")
print(f"大小: {len(raw)} bytes")
print('=' * 60)
issues = 0
for pat, desc in checks:
    matches = re.findall(pat, raw, re.IGNORECASE)
    if matches:
        issues += 1
        print(f'\u2717 [{desc}] \u547d\u4e2d {len(matches)} \u5904:')
        for m in matches[:5]:
            print(f'    {m[:100]}')
    else:
        print(f'\u2713 [{desc}] 0 \u547d\u4e2d')

print('=' * 60)
if issues == 0:
    print('\u2705 \u672a\u53d1\u73b0\u9690\u79c1\u95ee\u9898\uff0c\u53ef\u4ee5\u76f4\u63a5\u4f7f\u7528')
else:
    print(f'\u26a0\ufe0f  \u53d1\u73b0 {issues} \u7c7b\u9690\u79c1\u5b57\u6bb5\uff0c\u9700\u8981\u8131\u654f')
