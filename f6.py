import sys

with open(r'd:\dotscope\dotscope\assets\ui\index.html', 'r', encoding='utf-8') as f:
    text = f.read()

import re
# Hide the sidebar elements
text = re.sub(r'#sidebar\s*\{', '#sidebar { display: none !important;', text)
text = re.sub(r'#right-sidebar\s*\{', '#right-sidebar { display: none !important;', text)
text = re.sub(r'#nav-bar\s*\{', '#nav-bar { display: none !important;', text)

with open(r'd:\dotscope\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)
with open(r'd:\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)
