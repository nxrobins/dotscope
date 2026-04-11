import sys
import re

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

matches = re.finditer(r'getElementById\(([\'\"].*?[\'\"])\)', text)
ids = set([m.group(1) for m in matches])
print('EXPECTED IDS IN BUNDLE:', ids)

