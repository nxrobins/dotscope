import sys

with open(r'c:\Users\nxrob\.gemini\antigravity\brain\cca48e00-7a1d-444a-ae24-ddff111420c8\task.md', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('[/] 1. Implement UI Telemetry Bridge', '[x] 1. Implement UI Telemetry Bridge')
text = text.replace('[ ] 2. Fix Stale Graph Caching', '[x] 2. Fix Stale Graph Caching')
text = text.replace('[ ] 3. Point Engine at origin-dollar', '[/] 3. Point Engine at origin-dollar')

with open(r'c:\Users\nxrob\.gemini\antigravity\brain\cca48e00-7a1d-444a-ae24-ddff111420c8\task.md', 'w', encoding='utf-8') as f:
    f.write(text)
