import sys
with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()
import re
idx = text.find('fs_edge_main')
if idx != -1:
    print(text[max(0, idx-500):idx+500])
