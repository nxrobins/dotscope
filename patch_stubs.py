import sys

with open(r'd:\dotscope\assets\ui\index.html', 'r', encoding='utf-8') as f:
    text = f.read()

stubs = '''
  <!-- Headless DOM stubs for minified bundle compatibility -->
  <div style="display:none">
    <div id="ui-inspector"></div><div id="ui-desync"></div><div id="ui-node-depth"></div>
    <div id="search-input"></div><div id="nav-telemetry"></div><div id="scope-list"></div>
    <div id="ui-node-name"></div><div id="ui-edges"></div><div id="tab-history"></div>
    <div id="tab-canvas"></div><div id="nav-sync"></div><div id="tab-nodes"></div>
    <div id="tab-mcp"></div><div id="ui-fps"></div><div id="ui-node-in"></div>
    <div id="ui-nodes"></div><div id="nav-structural"></div>
  </div>
'''

if 'Headless DOM stubs' not in text:
    text = text.replace('<div id="fallback"', stubs + '\n  <div id="fallback"')
    
with open(r'd:\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)
    
print("Successfully patched index.html with DOM Stubs.")
