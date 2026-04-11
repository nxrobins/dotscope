import sys

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

bad_line = 'return vec4<f32>(0.2, 0.2, 0.2, 0.0); // Completely invisible'
good_line = 'return vec4<f32>(0.2, 0.3, 0.5, 0.15); // Ambient bioluminescent constellation'

if bad_line in text:
    text = text.replace(bad_line, good_line)
    with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'w', encoding='utf-8') as f:
        f.write(text)
    with open(r'd:\dotscope\assets\ui\bundle.js', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched ambient links!")
else:
    print("Failed to find bad line")
