import sys

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

# WebGPU uniform buffer filling typically happens with writeBuffer or similar typed array setups.
import re
match = re.search(r'new Uint32Array\([^)]*\).*?new Float32Array\([^)]*\)', text)
if match: print(match.group(0)[:500])
matches = re.finditer(r'new ArrayBuffer\(.*?\)', text)
for m in matches:
    end = min(m.end() + 200, len(text))
    print(text[m.start():end])

