import os
def s(p):
    for root, dirs, files in os.walk(p):
        for f in files:
            if not f.endswith('.py'): continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    if 'backtest' in content and 'check' in content:
                        print(f"Match in {path}")
            except: pass
s(r'd:\dotscope\dotscope\cli')
