import sys

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

bad = "const y=d.edges[p],x=c.get(y.source),v=c.get(y.target);"
good = "const y=d.edges[p],x=c.get(y.source.id||y.source),v=c.get(y.target.id||y.target);"

if bad in text:
    text = text.replace(bad, good)
    with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'w', encoding='utf-8') as f:
        f.write(text)
    with open(r'd:\dotscope\assets\ui\bundle.js', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Polyfill applied!")
else:
    print("Could not find the target line to polyfill.")
