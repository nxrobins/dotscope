import sys
with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()
import re
idx = text.find('// Fiber-optic traversal physics')
if idx != -1:
    print(text[max(0, idx):idx+1500])
