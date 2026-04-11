with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('fn fs_edge_main')
if idx != -1:
    print(text[idx:idx+1000])
