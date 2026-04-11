import sys

with open(r'd:\dotscope\assets\ui\index.html', 'r', encoding='utf-8') as f:
    text = f.read()

injection = '''
  <div id="live-telemetry-hud" style="position: absolute; bottom: 40px; left: 40px; display: flex; flex-direction: column; gap: 12px; z-index: 1000; pointer-events: none; width: 340px;">
  </div>
  <script>
    // Live Telemetry HUD Bridge
    const hudContainer = document.getElementById('live-telemetry-hud');
    
    function createActivityNode(item) {
      const el = document.createElement('div');
      // Mimic UI cluster
      el.style.display = 'flex';
      el.style.flexDirection = 'column';
      el.style.gap = '8px';
      el.style.padding = '14px 18px';
      el.style.borderRadius = '8px';
      el.style.borderLeft = '3px solid #10b981';
      el.style.background = 'rgba(10, 10, 20, 0.7)';
      el.style.backdropFilter = 'blur(16px)';
      el.style.borderTop = '1px solid rgba(255,255,255,0.05)';
      el.style.borderRight = '1px solid rgba(255,255,255,0.05)';
      el.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
      el.style.color = '#fff';
      el.style.fontFamily = 'monospace';
      el.style.fontSize = '11px';
      el.style.boxShadow = '0 8px 30px rgba(0,0,0,0.5)';
      
      const msStr = new Date(item.ts).toISOString().split('T')[1].replace('Z', '');
      el.innerHTML = 
        <div style="display:flex; justify-content:space-between; color: #10b981; font-weight: 600; letter-spacing: 1px;">
          <span>[]</span>
          <span style="opacity:0.6; font-size:10px;"></span>
        </div>
        <div style="color: rgba(255,255,255,0.8); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;">
          
        </div>
      ;
      return el;
    }

    async function pollTelemetry() {
      try {
        const res = await fetch('/api/activity');
        if (!res.ok) return;
        const data = await res.json();
        
        const recent = data.slice(-5); // Keep exactly last 5 calls
        hudContainer.innerHTML = ''; 
        recent.forEach(item => {
          hudContainer.appendChild(createActivityNode(item));
        });
        
      } catch(e) { }
    }

    // Ping mission control every 1 second
    setInterval(pollTelemetry, 1000);
    pollTelemetry();
  </script>
</body>'''

text = text.replace('</body>', injection)

with open(r'd:\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)
with open(r'd:\dotscope\dotscope\assets\ui\index.html', 'w', encoding='utf-8') as f:
    f.write(text)

print("HUD injected into DOM.")
