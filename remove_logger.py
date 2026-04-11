import sys

with open(r'd:\dotscope\dotscope\assets\ui\index.html', 'r', encoding='utf-8') as f:
    text = f.read()

import re
text = re.sub(r'<script>\s*setInterval\(\(\) => \{\s*if\(window\.__DEBUG_M_DUMP\).*?</script>', '', text, flags=re.DOTALL)

with open(r'd:\dotscope\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)
with open(r'd:\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)
