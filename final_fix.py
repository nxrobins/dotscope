import sys

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Fix line visibility unconditionally
bad_link = 'return vec4<f32>(0.2, 0.3, 0.5, 0.15); // Ambient bioluminescent constellation'
good_link = 'return vec4<f32>(0.4, 0.8, 1.0, 1.0); // OPAQUE CYAN LASERS'
text = text.replace(bad_link, good_link)

# 2. Re-inject clustering physics!
clustering_anchor = 'let dist_sq = max(dot(delta, delta), 10.0);'
clustering_physics = '''
        if (abs(node.velocity.w - other.velocity.w) < 0.1 && node.velocity.w != 0.0 && params.solar_sys < 5.0) {
            // Cohesive Scope Gravity 
            if (d_len > 100.0) {
                force += (delta / d_len) * -150.0;
            }
        }
'''
if 'Scope Gravity' not in text:
    text = text.replace(clustering_anchor, clustering_physics + '\n        ' + clustering_anchor)

with open(r'd:\dotscope\dotscope\assets\ui\bundle.js', 'w', encoding='utf-8') as f:
    f.write(text)
with open(r'd:\dotscope\assets\ui\bundle.js', 'w', encoding='utf-8') as f:
    f.write(text)
    
print("Injected OPAQUE lines and clustering gravity loop!")
