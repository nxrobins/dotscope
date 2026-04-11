import sys

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('edge_count')
if idx != -1:
    print(text[max(0, idx-50):idx+50])
