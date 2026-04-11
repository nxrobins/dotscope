import os
def s(p):
    for root, dirs, files in os.walk(p):
        for f in files:
            if not f.endswith('.py'): continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    lines = file.readlines()
                    for i, l in enumerate(lines):
                        if 'CheckCategory' in l:
                            print(f"{path}:{i+1}: {l.strip()}")
            except: pass
s(r'd:\dotscope\dotscope')
