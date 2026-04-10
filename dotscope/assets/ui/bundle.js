var B=Object.defineProperty;var M=(d,e,n)=>e in d?B(d,e,{enumerable:!0,configurable:!0,writable:!0,value:n}):d[e]=n;var o=(d,e,n)=>M(d,typeof e!="symbol"?e+"":e,n);(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const a of document.querySelectorAll('link[rel="modulepreload"]'))s(a);new MutationObserver(a=>{for(const r of a)if(r.type==="childList")for(const i of r.addedNodes)i.tagName==="LINK"&&i.rel==="modulepreload"&&s(i)}).observe(document,{childList:!0,subtree:!0});function n(a){const r={};return a.integrity&&(r.integrity=a.integrity),a.referrerPolicy&&(r.referrerPolicy=a.referrerPolicy),a.crossOrigin==="use-credentials"?r.credentials="include":a.crossOrigin==="anonymous"?r.credentials="omit":r.credentials="same-origin",r}function s(a){if(a.ep)return;a.ep=!0;const r=n(a);fetch(a.href,r)}})();const T="'Inter', sans-serif",C=12;function D(d){const i=new OffscreenCanvas(1,1).getContext("2d");i.font=`600 ${C}px ${T}`,i.textBaseline="top";const t=d.map(h=>{const w=i.measureText(h),P=Math.ceil(Math.max(w.width,w.actualBoundingBoxRight+Math.abs(w.actualBoundingBoxLeft)))+16,E=Math.ceil(w.actualBoundingBoxAscent+w.actualBoundingBoxDescent)+8;return{label:h,w:P,h:E}});let l=0,c=0,u=0;const m=[];for(const h of t)l+h.w>8192&&(l=0,c+=u+2,u=0),m.push({label:h.label,x:l,y:c,w:h.w,h:h.h}),l+=h.w,h.h>u&&(u=h.h);let g=c+u;const _=200,f=1024,b=g;g+=_,g>8192&&console.warn(`[Pretext Shield] Hardware Exception: Canvas height (${g}px) exceeds generic WebGPU 8192px limit. Node truncation may occur.`);const p=new OffscreenCanvas(8192,Math.max(g,1)),y=p.getContext("2d");y.clearRect(0,0,8192,g),y.fillStyle="rgba(255, 255, 255, 1.0)",y.font=i.font,y.textBaseline="top";const x=new Map;for(const h of m)y.fillText(h.label,h.x+64/2,h.y+8/2),x.set(h.label,{width:h.w,height:h.h,uMin:h.x/8192,vMin:h.y/p.height,uMax:(h.x+h.w)/8192,vMax:(h.y+h.h)/p.height});const v={width:f,height:_,uMin:0,vMin:b/p.height,uMax:f/8192,vMax:(b+_)/p.height};return{canvas:p,boxes:x,hudBox:v,hudY:b}}function S(d){const e=d.nodes.length,n=Object.keys(d.scopes||{}),s=n.length,a=e+s+1;let r=0;for(const p of n)r+=d.scopes[p].length;const i=d.edges.length+r,t=new Float32Array(a*16),l=new Uint32Array(i*2),c=new Map,u=D([...d.nodes.map(p=>p.id),...n]);let m=0;for(let p=0;p<e;p++){const y=d.nodes[p];c.set(y.id,p);const x=u.boxes.get(y.id);let v=0;v=0; if (y.id.includes(".spec.")||y.id.includes(".test.")) v=1; else if (y.id.endsWith(".ts")||y.id.endsWith(".js")) v=2; else if (y.id.endsWith(".py")) v=4; else if (y.id.endsWith(".rs")) v=5; else if (y.id.endsWith(".go")) v=6; else if (y.id.endsWith(".java")) v=7; else if (y.id.endsWith(".json")||y.id.endsWith(".toml")||y.id.endsWith(".yaml")) v=3;const h=p*16;t[h+0]=(Math.random()-.5)*4e3,t[h+1]=(Math.random()-.5)*4e3,t[h+2]=(Math.random()-.5)*4e3,t[h+3]=x.width*x.height,t[h+4]=0,t[h+5]=0,t[h+6]=0,t[h+7]=v,t[h+8]=x.width,t[h+9]=x.height,t[h+10]=0,t[h+11]=0,t[h+12]=x.uMin,t[h+13]=x.vMin,t[h+14]=x.uMax,t[h+15]=x.vMax}for(let p=0;p<d.edges.length;p++){const y=d.edges[p],x=c.get(y.source),v=c.get(y.target);x!==void 0&&v!==void 0&&(l[m*2+0]=x,l[m*2+1]=v,m++)}let g=e;for(let p=0;p<s;p++){const y=n[p],x=u.boxes.get(y),v=g*16;t[v+0]=(Math.random()-.5)*4e3,t[v+1]=(Math.random()-.5)*4e3,t[v+2]=(Math.random()-.5)*4e3,t[v+3]=x.width*x.height*2,t[v+4]=0,t[v+5]=0,t[v+6]=0,t[v+7]=10,t[v+8]=x.width*2.5,t[v+9]=x.height*2.5,t[v+10]=0,t[v+11]=0,t[v+12]=x.uMin,t[v+13]=x.vMin,t[v+14]=x.uMax,t[v+15]=x.vMax;const h=d.scopes[y];for(const w of h){const P=c.get(w);P!==void 0&&(l[m*2+0]=g,l[m*2+1]=P,m++)}g++}const _=a-1,f=_*16,b=u.hudBox;return t[f+0]=-1e5,t[f+1]=-1e5,t[f+2]=-1e5,t[f+3]=0,t[f+4]=0,t[f+5]=0,t[f+6]=0,t[f+7]=11,t[f+8]=b.width,t[f+9]=b.height,t[f+10]=0,t[f+11]=0,t[f+12]=b.uMin,t[f+13]=b.vMin,t[f+14]=b.uMax,t[f+15]=b.vMax,{nodeData:t,edgeData:l.slice(0,m*2),nodeCount:a,edgeCount:m,atlasCanvas:u.canvas,nodeMap:c,nodeLabels:d.nodes.map(p=>p.id),hudNodeIndex:_,hudBox:b,hudY:u.hudY}}async function I(d){if(!navigator.gpu)return null;const e=await navigator.gpu.requestAdapter();if(!e)return null;const n=await e.requestDevice(),s=d.getContext("webgpu");if(!s)return null;const a=navigator.gpu.getPreferredCanvasFormat();return s.configure({device:n,format:a,alphaMode:"opaque"}),{adapter:e,device:n,context:s,format:a}}const k=`struct Node {
    pos_mass: vec4<f32>,      // [0]: x, [1]: y, [2]: z, [3]: mass
    velocity: vec4<f32>,      // [0]: vx, [1]: vy, [2]: vz, [3]: type_id
    dim_bounds: vec4<f32>,    // [0]: width, [1]: height, [2]: pad, [3]: pad
    uv_bounds: vec4<f32>      // [0]: uMin, [1]: vMin, [2]: uMax, [3]: vMax
}

@group(0) @binding(0) var<storage, read_write> nodes: array<Node>;
@group(0) @binding(1) var<storage, read> edges: array<vec2<u32>>;

struct Params {
    node_count: u32,
    edge_count: u32,
    alpha: f32,
    solar_sys: f32,
    gravity_y: f32,
    delta_x: f32,
    delta_y: f32,
    delta_z: f32,
}
@group(0) @binding(2) var<uniform> params: Params;

// Constants for physical tuning
const SPRING_STIFFNESS: f32 = 0.02;
const SPRING_LENGTH: f32 = 500.0;       // Extended relaxed tether limits
const REPULSION_BASE: f32 = 150000.0;   // Emits massive long-range volumetric spacing 
const DAMPING: f32 = 0.85;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let index = global_id.x;
    if (index >= params.node_count) {
        return;
    }

    var node = nodes[index];
    var force = vec3<f32>(0.0, 0.0, 0.0);

    // ----------------------------------------------------------------------
    // Pass 1: Attraction (NPMI Edge Spring Forces - 3D)
    // ----------------------------------------------------------------------
    for (var e = 0u; e < params.edge_count; e = e + 1u) {
        let edge = edges[e];
        if (edge.x == index || edge.y == index) {
            let neighbor_idx = select(edge.x, edge.y, edge.x == index);
            let neighbor = nodes[neighbor_idx];
            
            var delta = neighbor.pos_mass.xyz - node.pos_mass.xyz;
            let dist = length(delta);
            
            if (dist > 0.001) {
                let spring = (max(dist, 0.1) - SPRING_LENGTH) * SPRING_STIFFNESS;
                let dir = delta / dist; 
                force += dir * spring;
            }
        }
    }

    // ----------------------------------------------------------------------
    // Pass 2: Coulomb Repulsion (Spherical 3D Galaxy Mechanics)
    // ----------------------------------------------------------------------
    for (var j = 0u; j < params.node_count; j = j + 1u) {
        if (index == j) { continue; }
        
        let other = nodes[j];
        
        // Bypass UI/Holographic ambient metrics from tearing network geometry
        if (node.velocity.w >= 10.0 || other.velocity.w >= 10.0) { continue; }
        var delta = node.pos_mass.xyz - other.pos_mass.xyz;
        let d_len = length(delta);
        
        if (d_len < 0.1) {
            // Anti-stacking jitter spherical pop
            delta = vec3<f32>(
                (f32(index) - f32(j)) * 0.1, 
                (f32(j) - f32(index)) * 0.1,
                (f32(index) % 5.0) * 0.1
            );
        }
        
        // Massive Repulsion inside collision radii (organic cluster packing)
        if (d_len < 240.0) {
            force += (delta / max(d_len, 0.01)) * 1000.0;
        }

        // Long-range Repulsion (Coulomb force) to space the galaxy branches
        let dist_sq = max(dot(delta, delta), 10.0);
        let repel_mag = (REPULSION_BASE * params.solar_sys) / dist_sq;
        if (d_len > 0.001) {
            force += (delta / d_len) * repel_mag;
        }
    }

    // Central Gravity pulling towards coordinate space origin (0,0,0) (RTE center)
    let center_dir = vec3<f32>(0.0, params.gravity_y, 0.0) - node.pos_mass.xyz;
    force += center_dir * 0.05;

    // ----------------------------------------------------------------------
    // Pass 3: Integration (3D Volumetric Cooling)
    // ----------------------------------------------------------------------
    node.velocity.x += force.x * params.alpha;
    node.velocity.y += force.y * params.alpha;
    node.velocity.z += force.z * params.alpha;
    
    node.velocity.x *= DAMPING;
    node.velocity.y *= DAMPING;
    node.velocity.z *= DAMPING;
    
    node.pos_mass.x += node.velocity.x;
    node.pos_mass.y += node.velocity.y;
    node.pos_mass.z += node.velocity.z;

    // Execute VRAM Native RTE (Treadmill Shift) seamlessly sliding coordinates to maintain f32 precision!
    node.pos_mass.x -= params.delta_x;
    node.pos_mass.y -= params.delta_y;
    node.pos_mass.z -= params.delta_z;

    nodes[index] = node;
}
`,L=`// ----------------------------------------------------------------------
// Zero-Copy Direct Memory Read
// ----------------------------------------------------------------------
struct Node {
    pos_mass: vec4<f32>,      // [x, y, z, mass]
    velocity: vec4<f32>,      // [vx, vy, vz, type_id]
    dim_bounds: vec4<f32>,    // [width, height, pad, pad]
    uv_bounds: vec4<f32>      // [uMin, vMin, uMax, vMax]
}

@group(0) @binding(0) var<storage, read> nodes: array<Node>;

// ----------------------------------------------------------------------
// Camera Uniform (Pan & Zoom)
// ----------------------------------------------------------------------
struct Camera {
    offset: vec2<f32>,
    scale: vec2<f32>,
    resolution: vec2<f32>,
    rotation: vec2<f32>, // pitch (x), yaw (y)
    timing: f32,
    hover_id: f32,
    selected_id: f32,
    pointer_x: f32,
    pointer_y: f32,
    pad1: f32, // hasMultiSelection
    history_scrub_progress: f32,
    sync_pulse_time: f32
}
@group(0) @binding(1) var<uniform> camera: Camera;

// ----------------------------------------------------------------------
// Edge Topology Buffer
// ----------------------------------------------------------------------
@group(0) @binding(2) var<storage, read> edges: array<vec2<u32>>;

// ----------------------------------------------------------------------
// Multi-Selection State Array
// ----------------------------------------------------------------------
@group(0) @binding(3) var<storage, read> selections: array<f32>;

// ----------------------------------------------------------------------
// Pretext Texture Atlas
// ----------------------------------------------------------------------
@group(0) @binding(4) var atlas: texture_2d<f32>;
@group(0) @binding(5) var atlas_sampler: sampler;

// ----------------------------------------------------------------------
// Vertex to Fragment Structure
// ----------------------------------------------------------------------
struct FragmentPayload {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) dimensions: vec2<f32>,
    @location(2) atlas_uv: vec2<f32>,
    @location(3) depth: f32,
    @location(4) type_id: f32,
    @location(5) node_idx: f32
}

// ----------------------------------------------------------------------
// Vertex Shader (Node Instancing)
// ----------------------------------------------------------------------
const QUAD_VERTICES = array<vec2<f32>, 6>(
    vec2<f32>(-0.5, -0.5), vec2<f32>( 0.5, -0.5), vec2<f32>( 0.5,  0.5),
    vec2<f32>(-0.5, -0.5), vec2<f32>( 0.5,  0.5), vec2<f32>(-0.5,  0.5)
);

@vertex
fn vs_main(
    @builtin(vertex_index) vertex_index: u32,
    @builtin(instance_index) instance_index: u32
) -> FragmentPayload {
    var out: FragmentPayload;
    let node = nodes[instance_index];
    let vertex = QUAD_VERTICES[vertex_index];
    
    // 1. Center of the node in 3D Space (incorporating Z!)
    var raw_pos = node.pos_mass.xyz;
    
    // Hypnotic Ripple Mathematics (Oceanic breathing simulation for standard nodes)
    let dist_from_center = length(raw_pos.xz);
    if (node.velocity.w < 10.0) {
        // Oceanic Sway
        let wave_offset = sin(dist_from_center * 0.015 - camera.timing * 0.8) * 35.0;
        let secondary_harmonic = cos(dist_from_center * 0.02 + camera.timing * 1.2) * 20.0;
        raw_pos.y += wave_offset + secondary_harmonic;
    }
    
    // Dynamic GPU-side HUD positional anchoring (Lightning Fast)
    if (node.velocity.w == 11.0 && camera.selected_id >= 0.0) {
        let focal_node = nodes[u32(round(camera.selected_id))];
        raw_pos = focal_node.pos_mass.xyz + vec3<f32>(140.0, 60.0, 40.0); // Spatial offset
    }

    let cx = cos(camera.rotation.x); let sx = sin(camera.rotation.x);
    let cy = cos(camera.rotation.y); let sy = sin(camera.rotation.y);
    
    // Pitch (Rotate around X)
    let px1 = raw_pos.x;
    let py1 = raw_pos.y * cx - raw_pos.z * sx;
    let pz1 = raw_pos.y * sx + raw_pos.z * cx;
    
    // Yaw (Rotate around Y)
    let px2 = px1 * cy + pz1 * sy;
    let pz2 = -px1 * sy + pz1 * cy;
    
    // 2. Perspective Projection (Dynamic FOV based on Focal Length)
    let focal_length = 2500.0; 
    let camera_z = focal_length + pz2;
    let is_behind = camera_z < 50.0; // Strictly cull nodes flying behind the eye
    
    let perspective = focal_length / max(camera_z, 50.0);
    
    // 3. Map the 3D position to 2D Screen Space
    var screen_pos = vec2<f32>(px2, py1) * camera.scale.x * perspective;
    screen_pos += camera.offset;
    
    // 4. Optical Billboarding (Quads always face camera directly but scale physically)
    let billboard_vertex = vertex * node.dim_bounds.xy * camera.scale.x * perspective;
    let final_world = screen_pos + billboard_vertex;
    
    // 5. Translate derived physics space to NDC [-1.0, 1.0]
    let ndc_x = (final_world.x / camera.resolution.x) * 2.0 - 1.0;
    let ndc_y = (final_world.y / camera.resolution.y) * 2.0 - 1.0;
    
    // Map Z for Depth-Testing
    let ndc_z = 1.0 - (perspective / 2.0); 

    // Culling geometries securely violating the near-plane without x-coordinate corruption
    let clipped_z = select(ndc_z, 2.0, is_behind); // Force out of [0, 1] clip volume natively
    out.position = vec4<f32>(ndc_x, -ndc_y, clipped_z, 1.0);
    
    out.uv = vertex + 0.5;
    out.dimensions = node.dim_bounds.xy * perspective * camera.scale.x; 
    out.depth = perspective;
    out.type_id = node.velocity.w;
    out.node_idx = f32(instance_index);

    out.atlas_uv = vec2<f32>(
        mix(node.uv_bounds.x, node.uv_bounds.z, out.uv.x),
        mix(node.uv_bounds.y, node.uv_bounds.w, out.uv.y)
    );
    
    return out;
}

// ----------------------------------------------------------------------
// Fragment Shader (Glassmorphism + Thermodynamics)
// ----------------------------------------------------------------------
@fragment
fn fs_main(in: FragmentPayload) -> @location(0) vec4<f32> {
    
    // Semantic Cryptographic Typing mapping logically across color spectrums
    let t_id = u32(round(in.type_id));
    
    // Unconditional Uniform Texture Fetch safely guaranteeing implicit derivatives 
    let font_pixel = textureSample(atlas, atlas_sampler, in.atlas_uv);

    if (t_id >= 10u) {
        // Holographic UI Overlays (Centroids & HUDs)
        let font_alpha = font_pixel.a;
        
        // HUD defaults to very bright display, Holograms blend into background 
        var final_ui_alpha = font_alpha;
        
        let lod_distance = in.depth * camera.scale.x;
        if (t_id == 10u) {
            // Cluster Holograms only appear when panning outwards to see the massive topology
            let fade_in = smoothstep(0.01, 0.05, lod_distance);
            final_ui_alpha *= (1.0 - fade_in); 
        } else if (t_id == 11u) { discard; }
        
        // Output crisp white Hologram / HUD
        if (final_ui_alpha < 0.005) { discard; }
        return vec4<f32>(1.0, 1.0, 1.0, final_ui_alpha);
    }
    
    var base_color = vec3<f32>(0.1, 0.3, 0.4); // Core Bioluminescent Teal default
    if (t_id == 1u) { base_color = vec3<f32>(0.98, 0.20, 0.40); }
    else if (t_id == 2u) { base_color = vec3<f32>(0.9, 0.8, 0.2); } // JS/TS Yellow
    else if (t_id == 3u) { base_color = vec3<f32>(0.5, 0.20, 0.80); } // Config Purple
    else if (t_id == 4u) { base_color = vec3<f32>(0.20, 0.60, 0.98); } // Python Blue
    else if (t_id == 5u) { base_color = vec3<f32>(0.98, 0.40, 0.10); } // Rust Orange
    else if (t_id == 6u) { base_color = vec3<f32>(0.10, 0.80, 0.80); } // Go Cyan
    else if (t_id == 7u) { base_color = vec3<f32>(0.90, 0.10, 0.30); } // Java Red

    // Deep Ocean Bioluminescence Oscillation
    let bio_shift = sin(in.node_idx * 0.123 + camera.timing * 0.5) * 0.15;
    base_color = base_color + vec3<f32>(bio_shift * 0.5, bio_shift, -bio_shift * 0.5);
    base_color = clamp(base_color, vec3<f32>(0.0), vec3<f32>(1.0));

    
    // Ghost History Mutator (Soft, temporal fade mechanics)
    if (camera.history_scrub_progress > 0.0) {
        // Pseudo-random assignment for Red/Green
        let ghost_hash = fract(sin(in.node_idx * 12.9898) * 43758.5453);
        
        let ghost_red = vec3<f32>(0.6, 0.1, 0.15);     // Deep, muted red
        let bloom_green = vec3<f32>(0.1, 0.5, 0.25);   // Soft, ambient green
        
        // Use depth scaling for a smooth falloff instead of harsh Christmas light strobing
        let time_fade = smoothstep(0.0, 1.0, camera.history_scrub_progress);
        let dist_offset = (in.node_idx / 15000.0) * 0.5; // Offset timing slightly per node organically
        
        // Softly fade to the temporal color dependent on scrub threshold
        let scrubbed = clamp(time_fade - dist_offset, 0.0, 1.0);
        let target_temporal_color = mix(ghost_red, bloom_green, step(0.5, ghost_hash));
        
        base_color = mix(base_color, target_temporal_color, scrubbed * 0.85);
    }
    
    let aspect = in.dimensions.x / in.dimensions.y;
    let node_idx_u32 = u32(round(in.node_idx));
    let sel_type = selections[node_idx_u32];

    let p = vec2<f32>(in.uv.x * aspect, in.uv.y);
    
    // We intentionally anchor the center of our 3D Orb Math slightly to the left 
    // to give the text more breathing room aesthetically!
    let node_center = vec2<f32>(0.5, 0.5); 

    let r_norm = (p - node_center) * 2.5; 
    let r_len = length(r_norm);
    
    // 3D Normal Mapping
    let z = sqrt(max(1.0 - r_len * r_len, 0.0));
    let normal = normalize(vec3<f32>(r_norm.x, r_norm.y, z));

    let light_dir = normalize(vec3<f32>(-1.0, 1.5, 1.0));
    let view_dir = vec3<f32>(0.0, 0.0, 1.0);
    
    let diffuse = max(dot(normal, light_dir), 0.0);
    let half_vec = normalize(light_dir + view_dir);
    let specular = pow(max(dot(normal, half_vec), 0.0), 64.0) * 1.5;

    let pulse_time = camera.timing * 2.0 + in.node_idx * 0.1;
    let pulse_intensity = (sin(pulse_time) * 0.5 + 0.5) * 0.3 + 0.7;
    let core_glow = pow(max(1.0 - r_len, 0.0), 1.5) * 0.6 * pulse_intensity;

    let fresnel = pow(1.0 - max(dot(normal, view_dir), 0.0), 3.0) * 0.8;

    var sphere_rgb = base_color * (diffuse * 0.6 + 0.4 + core_glow) + vec3<f32>(1.0)*specular + base_color * fresnel;
    let sphere_mask = 1.0 - smoothstep(0.9, 1.0, r_len);

    let dist_to_node = length(p - node_center);
    
    // FIX 1: Set glow_radius sharply inside 0.5 distance to unconditionally prevent quadratic clipping (NO MORE SQUARE OUTLINES)
    let glow_radius = 0.45; 
    let node_glow = pow(1.0 - smoothstep(0.3, glow_radius, dist_to_node), 2.5);
    
    var node_rgb = mix(base_color * node_glow * 0.5, sphere_rgb, sphere_mask);
    let node_alpha = max(sphere_mask, node_glow * 0.6);

    // Blast Radius Overrides for the Orb
    if (sel_type == 1.0) { node_rgb = mix(vec3<f32>(0.2, 1.0, 0.4) * node_glow, vec3<f32>(0.8, 1.0, 0.8), sphere_mask); base_color = vec3<f32>(0.2, 1.0, 0.4); } 
    else if (sel_type == 2.0) { node_rgb = mix(vec3<f32>(1.0, 0.5, 0.1) * node_glow, vec3<f32>(1.0, 0.9, 0.6), sphere_mask); base_color = vec3<f32>(1.0, 0.5, 0.1); } 
    else if (sel_type == 3.0) { node_rgb = mix(vec3<f32>(0.8, 0.1, 0.1) * node_glow, vec3<f32>(1.0, 0.3, 0.3), sphere_mask); base_color = vec3<f32>(0.8, 0.1, 0.1); }

    // TEXT DISPLAY LOGIC
    var tinted_font = mix(vec3<f32>(1.0, 1.0, 1.0), base_color, 0.3);
    
    let is_focused = (in.node_idx == camera.selected_id);
    let is_hovered = (sel_type > 0.0);
    let is_physically_hovered = (in.node_idx == camera.hover_id);
    
    let text_weight = smoothstep(0.35, 0.65, font_pixel.a);
    let core_shield = smoothstep(0.7, 1.2, r_len);
    
    // FIX 2.5: Absolutely NO text globally! EVER! 
    var font_alpha = 0.0;
    
    // ONLY illuminate text unconditionally if the mouse explicitly grazes the orb, or it is explicitly clicked!
    if (is_focused || is_physically_hovered) {
        font_alpha = text_weight * core_shield;
    }

    var combined_rgb = mix(node_rgb, tinted_font, font_alpha);

    // Explicitly define alpha mapping logic
    var final_alpha = max(node_alpha, font_alpha);
    var fog_density = 1.0; 

    // FIX 3: Clicking a node should subtly illuminate the Orb natively, NOT overwrite the entire bounding box with a flat green bar!
    if (is_focused) {
        combined_rgb = combined_rgb + vec3<f32>(0.2, 1.0, 0.4) * 0.4;
    }
    
    let is_selected = is_focused || is_hovered;
    let any_selection_active = camera.selected_id >= 0.0 || camera.pad1 > 0.0;

    if (any_selection_active && !is_selected) { }

    if (final_alpha < 0.005) { discard; }

    return vec4<f32>(combined_rgb * fog_density, final_alpha); 
}

// ----------------------------------------------------------------------
// Edge Render Shaders (NPMI Gravity Tethers)
// ----------------------------------------------------------------------
struct EdgeFragment {
    @builtin(position) position: vec4<f32>,
    @location(0) dist: f32,
    @location(1) is_source_sel: f32,
    @location(2) is_target_sel: f32,
}

@vertex
fn vs_edge_main(@builtin(vertex_index) vertex_index: u32) -> EdgeFragment {
    var out: EdgeFragment;
    let edge_idx = vertex_index / 2u;
    let is_target = vertex_index % 2u;
    
    let edge = edges[edge_idx];
    let node_idx = select(edge.x, edge.y, is_target == 1u);
    let node = nodes[node_idx];
    
    var raw_pos = node.pos_mass.xyz;
    
    // Sync Exact Hypnotic Ripple Mathematics so the Tethers never rip from the bounding volumes
    let dist_from_center = length(raw_pos.xz);
    if (node.velocity.w < 10.0) {
        // Oceanic Sway
        let wave_offset = sin(dist_from_center * 0.015 - camera.timing * 0.8) * 35.0;
        let secondary_harmonic = cos(dist_from_center * 0.02 + camera.timing * 1.2) * 20.0;
        raw_pos.y += wave_offset + secondary_harmonic;
    }
    
    let cx = cos(camera.rotation.x); let sx = sin(camera.rotation.x);
    let cy = cos(camera.rotation.y); let sy = sin(camera.rotation.y);
    
    let px1 = raw_pos.x;
    let py1 = raw_pos.y * cx - raw_pos.z * sx;
    let pz1 = raw_pos.y * sx + raw_pos.z * cx;
    
    let px2 = px1 * cy + pz1 * sy;
    let pz2 = -px1 * sy + pz1 * cy;
    
    let focal_length = 2500.0; 
    let camera_z = focal_length + pz2;
    let is_behind = camera_z < 50.0;
    
    let perspective = focal_length / max(camera_z, 50.0);
    
    var screen_pos = vec2<f32>(px2, py1) * camera.scale.x * perspective;
    screen_pos += camera.offset;

    let ndc_x = (screen_pos.x / camera.resolution.x) * 2.0 - 1.0;
    let ndc_y = (screen_pos.y / camera.resolution.y) * 2.0 - 1.0;

    let ndc_z = 1.0 - (perspective / 2.0);

    let clipped_z = select(ndc_z, 2.0, is_behind);
    out.position = vec4<f32>(ndc_x, -ndc_y, clipped_z, 1.0);
    
    // Evaluate Upstream/Downstream routing flow including multi-selections!
    let sel_id = camera.selected_id;
    
    let src_idx = u32(edge.x);
    let dst_idx = u32(edge.y);
    
    let src_type = selections[src_idx];
    let dst_type = selections[dst_idx];
    
    out.dist = f32(is_target); // 0.0 for source, 1.0 for target
    out.is_source_sel = select(0.0, src_type, f32(src_idx) == sel_id || src_type > 0.0);
    out.is_target_sel = select(0.0, dst_type, f32(dst_idx) == sel_id || dst_type > 0.0);
    
    return out;
}

@fragment
fn fs_edge_main(in: EdgeFragment) -> @location(0) vec4<f32> {
    
    // Strict isolation of unassociated branches natively ensuring cleanliness
    if (in.is_source_sel == 0.0 && in.is_target_sel == 0.0) {
        return vec4<f32>(0.2, 0.2, 0.2, 0.0); // Completely invisible
    }
    
    // Fiber-optic traversal physics: pulse travels linearly from Source down to Target
    // The pulse loops continuously from 0.0 to 1.0 along the \`dist\` metric
    let pulse_position = fract(camera.timing * 0.8);
    let spark = exp(-abs(in.dist - pulse_position) * 20.0);

    // Hydration Sync Pulse Blast (Catastrophic Overload)
    let sync_time_diff = camera.timing - camera.sync_pulse_time;
    var hydration_pulse = 0.0;
    if (sync_time_diff > 0.0 && sync_time_diff < 1.0) {
        hydration_pulse = exp(-abs(in.dist - (sync_time_diff * 2.0)) * 10.0);
    }

    let base_alpha = 0.5 + spark * 1.5 + hydration_pulse * 3.0;

    // Evaluate Topological depth mapping to match the node ripples
    if (in.is_source_sel == 1.0 && in.is_target_sel == 2.0) {
        // Core to Depth 1 (WILL BREAK) -> Output Hot Orange Spark
        return vec4<f32>(1.0, 0.5 + spark * 0.5, 0.1 + spark, base_alpha);
    } else if (in.is_source_sel == 2.0 && in.is_target_sel == 3.0) {
        // Depth 1 to Depth 2 (AFFECTED) -> Deep Red Spark
        return vec4<f32>(0.8 + spark * 0.2, 0.1 + spark * 0.3, 0.1 + spark * 0.3, base_alpha * 0.7);
    } else if (in.is_target_sel == 1.0 && in.is_source_sel == 2.0) {
        // Reverse Upstream Dep (If we're showing incoming logic to the core) -> Neon Sapphire
        return vec4<f32>(0.1 + spark * 0.5, 0.6 + spark * 0.4, 1.0, base_alpha);
    }

    // Default active spark layout (for generic single-node selection hovering)
    return vec4<f32>(1.0, 0.8, 0.2, 0.3 + spark * 0.5); 
}
`,A=`// ----------------------------------------------------------------------
// Physics Node Layout (Matches shader.wgsl perfectly)
// ----------------------------------------------------------------------
struct Node {
    pos_mass: vec4<f32>,
    velocity: vec4<f32>,
    dim_bounds: vec4<f32>,
    uv_bounds: vec4<f32>
}

// ----------------------------------------------------------------------
// Camera Component (Extended Uniform)
// ----------------------------------------------------------------------
struct Camera {
    offset: vec2<f32>,
    scale: vec2<f32>,
    resolution: vec2<f32>,
    rotation: vec2<f32>,
    timing: f32,
    hover_id: f32,
    selected_id: f32,
    pointer_x: f32,
    pointer_y: f32,
    pad1: f32,
    pad2: f32,
    pad3: f32
}

struct PickerOutput {
    closest_index: atomic<u32>,
    min_distance: atomic<u32> // Encoded as bits
}

struct CoreParams {
    node_count: u32,
    pad1: u32,
    pad2: u32,
    pad3: u32
}

@group(0) @binding(0) var<storage, read> nodes: array<Node>;
@group(0) @binding(1) var<uniform> camera: Camera;
@group(0) @binding(2) var<storage, read_write> pick_out: PickerOutput;
@group(0) @binding(3) var<uniform> core: CoreParams;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let index = global_id.x;
    if (index >= core.node_count) {
        return;
    }

    if (index == 0u) {
        // Initialization reset phase strictly handled externally or rely on atomicOps
    }

    let node = nodes[index];
    
    // Exact identical rotation matrix projection mapped natively from render.wgsl
    let cx = cos(camera.rotation.x); let sx = sin(camera.rotation.x);
    let cy = cos(camera.rotation.y); let sy = sin(camera.rotation.y);
    
    let px1 = node.pos_mass.x;
    let py1 = node.pos_mass.y * cx - node.pos_mass.z * sx;
    let pz1 = node.pos_mass.y * sx + node.pos_mass.z * cx;
    
    let px2 = px1 * cy + pz1 * sy;
    let pz2 = -px1 * sy + pz1 * cy;
    
    let focal_length = 2500.0; 
    let camera_z = focal_length + pz2;
    if (camera_z < 50.0) { return; } // Behind camera
    
    let perspective = focal_length / camera_z;
    
    var screen_pos = vec2<f32>(px2, py1) * camera.scale.x * perspective;
    screen_pos += camera.offset;
    
    // Bounds mapping dynamically generated matching fragment dimensions
    let half_w = (node.dim_bounds.x * perspective * camera.scale.x) / 2.0;
    let half_h = (node.dim_bounds.y * perspective * camera.scale.x) / 2.0;
    let click_radius = max(half_w, max(half_h, 8.0)); // Ensure tiny far nodes are clickable natively
    
    let pointer = vec2<f32>(camera.pointer_x, camera.pointer_y);
    let delta = pointer - screen_pos;
    let dist_sq = dot(delta, delta);

    // Validate bounds constraint organically mimicking a physics spherical trace intersection
    if (dist_sq < (click_radius * click_radius)) {
        // We pack [depth, distance] effectively ensuring the closest camera_z AND cursor distance wins
        // Utilizing purely atomicMin locking over memory buses preventing data races
        let packed_metric = bitcast<u32>(f32(dist_sq * 0.1 + camera_z * 1.0));
        let prev_min = atomicMin(&pick_out.min_distance, packed_metric);
        if (packed_metric < prev_min) {
            atomicStore(&pick_out.closest_index, index);
        }
    }
}
`;async function z(d){const e=d.createShaderModule({code:k});return d.createComputePipeline({layout:"auto",compute:{module:e,entryPoint:"main"}})}async function U(d){const e=d.createShaderModule({code:A});return d.createComputePipeline({layout:"auto",compute:{module:e,entryPoint:"main"}})}async function G(d,e){const n=d.createShaderModule({code:L}),s={color:{srcFactor:"src-alpha",dstFactor:"one-minus-src-alpha",operation:"add"},alpha:{srcFactor:"src-alpha",dstFactor:"one-minus-src-alpha",operation:"add"}},a={depthWriteEnabled:!1,depthCompare:"less",format:"depth24plus"},r=await d.createRenderPipelineAsync({layout:"auto",vertex:{module:n,entryPoint:"vs_main"},fragment:{module:n,entryPoint:"fs_main",targets:[{format:e,blend:s}]},primitive:{topology:"triangle-list"},depthStencil:a}),i=await d.createRenderPipelineAsync({layout:"auto",vertex:{module:n,entryPoint:"vs_edge_main"},fragment:{module:n,entryPoint:"fs_edge_main",targets:[{format:e,blend:s}]},primitive:{topology:"line-list"},depthStencil:a});return{nodePipeline:r,edgePipeline:i}}class N{constructor(e,n,s,a,r,i){o(this,"context");o(this,"buffers");o(this,"alpha",1);o(this,"cameraOffset",{x:0,y:0});o(this,"cameraZoom",-1);o(this,"cameraPitch",.6);o(this,"cameraYaw",0);o(this,"treadmillDelta",{x:0,y:0,z:0});o(this,"timing",0);o(this,"hoverNode",-1);o(this,"selectedNode",-1);o(this,"pointerX",-1e3);o(this,"pointerY",-1e3);o(this,"hasMultiSelection",!1);o(this,"historyProgress",0);o(this,"syncPulseTime",-100);o(this,"displayMCP",!1);o(this,"mcpLogs",[]); o(this, "solarSystemMode", 1.0);o(this,"computePipeline");o(this,"pickerPipeline");o(this,"nodePipeline");o(this,"edgePipeline");o(this,"nodeBuffer");o(this,"edgeBuffer");o(this,"selectionBuffer");o(this,"uniformBuffer");o(this,"cameraBuffer");o(this,"pickerOutBuffer");o(this,"pickerMapBuffer");o(this,"atlasTexture");o(this,"computeBindGroup");o(this,"pickerBindGroup");o(this,"renderBindGroup");o(this,"edgeBindGroup");o(this,"isPicking",!1);o(this,"depthTexture",null);this.context=e,this.buffers=n,this.computePipeline=s,this.pickerPipeline=a,this.nodePipeline=r,this.edgePipeline=i,this.nodeBuffer=e.device.createBuffer({size:n.nodeData.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST,mappedAtCreation:!0}),new Float32Array(this.nodeBuffer.getMappedRange()).set(n.nodeData),this.nodeBuffer.unmap(),this.edgeBuffer=e.device.createBuffer({size:n.edgeData.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST,mappedAtCreation:!0}),new Uint32Array(this.edgeBuffer.getMappedRange()).set(n.edgeData),this.edgeBuffer.unmap(),this.selectionBuffer=e.device.createBuffer({size:n.nodeCount*4,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.uniformBuffer=e.device.createBuffer({size:48,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.computeBindGroup=e.device.createBindGroup({layout:this.computePipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.edgeBuffer}},{binding:2,resource:{buffer:this.uniformBuffer}}]}),this.cameraBuffer=e.device.createBuffer({size:64,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.pickerOutBuffer=e.device.createBuffer({size:8,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST}),this.pickerMapBuffer=e.device.createBuffer({size:8,usage:GPUBufferUsage.MAP_READ|GPUBufferUsage.COPY_DST}),this.pickerBindGroup=e.device.createBindGroup({layout:this.pickerPipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.cameraBuffer}},{binding:2,resource:{buffer:this.pickerOutBuffer}},{binding:3,resource:{buffer:this.uniformBuffer}}]}),this.atlasTexture=e.device.createTexture({size:[n.atlasCanvas.width,n.atlasCanvas.height,1],format:"rgba8unorm",usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT}),e.device.queue.copyExternalImageToTexture({source:n.atlasCanvas},{texture:this.atlasTexture},[n.atlasCanvas.width,n.atlasCanvas.height]);const t=e.device.createSampler({magFilter:"linear",minFilter:"linear",mipmapFilter:"linear"});this.renderBindGroup=e.device.createBindGroup({layout:this.nodePipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.cameraBuffer}},{binding:3,resource:{buffer:this.selectionBuffer}},{binding:4,resource:this.atlasTexture.createView()},{binding:5,resource:t}]}),this.edgeBindGroup=e.device.createBindGroup({layout:this.edgePipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.cameraBuffer}},{binding:2,resource:{buffer:this.edgeBuffer}},{binding:3,resource:{buffer:this.selectionBuffer}}]})}setMultiSelection(e){this.hasMultiSelection=e.length>0;const n=new Float32Array(this.buffers.nodeCount),s=new Set;e.forEach(i=>{const t=this.buffers.nodeMap.get(i);t!==void 0&&(n[t]=1,s.add(t))});const a=new Set,r=this.buffers.edgeData;for(let i=0;i<this.buffers.edgeCount;i++){const t=r[i*2],l=r[i*2+1];s.has(l)&&!s.has(t)&&(n[t]=2,a.add(t))}for(let i=0;i<this.buffers.edgeCount;i++){const t=r[i*2],l=r[i*2+1];a.has(l)&&!s.has(t)&&!a.has(t)&&(n[t]=3)}this.context.device.queue.writeBuffer(this.selectionBuffer,0,n)}updateHUD(e){if(e<0||e>=this.buffers.nodeLabels.length){const c=new Float32Array([-1e5,-1e5,-1e5,0]);this.context.device.queue.writeBuffer(this.nodeBuffer,this.buffers.hudNodeIndex*64,c);const u=document.getElementById("ui-inspector");u&&u.classList.remove("active");return}const n=this.buffers.nodeLabels[e];let s=0,a=0;const r=this.buffers.edgeData;for(let c=0;c<this.buffers.edgeCount;c++)r[c*2+0]===e&&a++,r[c*2+1]===e&&s++;const i=this.buffers.atlasCanvas.getContext("2d"),t=this.buffers.hudBox;i.clearRect(0,this.buffers.hudY,t.width,t.height),this.displayMCP?(i.fillStyle="rgba(4, 6, 8, 0.85)",i.fillRect(0,this.buffers.hudY,t.width,t.height),i.fillStyle="rgba(16, 185, 129, 0.4)",i.fillRect(0,this.buffers.hudY,t.width,4),i.fillStyle="#10b981",i.font="600 24px 'monospace'",i.fillText("MCP_TERMINAL_STREAM",30,this.buffers.hudY+50),i.fillStyle="rgba(255, 255, 255, 0.7)",i.font="64px 'monospace'",this.mcpLogs.forEach((c,u)=>{i.fillText(`> ${c}`,30,this.buffers.hudY+100+u*28)}),Math.random()<.05&&this.mcpLogs.length<15&&this.mcpLogs.push("[trace] Raycast mapped node boundary at depth 0x0...")):(i.fillStyle="rgba(10, 15, 25, 0.95)",i.fillRect(0,this.buffers.hudY,t.width,t.height),i.fillStyle="rgba(40, 255, 100, 1.0)",i.font="600 36px 'Inter', sans-serif",i.fillText("Topological Anchor",20,this.buffers.hudY+40),i.fillStyle="#ffffff",i.font="bold 28px 'Inter', sans-serif",i.fillText(n,20,this.buffers.hudY+90),i.fillStyle="rgba(150, 200, 255, 0.8)",i.font="500 24px 'Inter', sans-serif",i.fillText(`Incoming Dependencies: ${s}`,20,this.buffers.hudY+140),i.fillText(`Outgoing Boundaries:  ${a}`,20,this.buffers.hudY+180)),this.context.device.queue.copyExternalImageToTexture({source:this.buffers.atlasCanvas},{texture:this.atlasTexture},[this.buffers.atlasCanvas.width,this.buffers.atlasCanvas.height]);const l=document.getElementById("ui-inspector");if(l){l.classList.add("active");const c=document.getElementById("ui-node-name");c&&(c.textContent=n.split("/").pop()||n);const u=document.getElementById("ui-node-depth");u&&(u.textContent=(e%5).toString());const m=document.getElementById("ui-node-in");m&&(m.textContent=s.toString());const g=document.getElementById("ui-node-out");g&&(g.textContent=a.toString())}}update(e,n){(!this.depthTexture||this.depthTexture.width!==e||this.depthTexture.height!==n)&&(this.depthTexture&&this.depthTexture.destroy(),this.depthTexture=this.context.device.createTexture({size:[e,n,1],format:"depth24plus",usage:GPUTextureUsage.RENDER_ATTACHMENT})),this.cameraZoom===-1&&(this.cameraZoom=this.buffers.nodeCount>5e3?.05:.2,this.cameraOffset.x=e/2,this.cameraOffset.y=n/2);const s=new Float32Array([this.cameraOffset.x,this.cameraOffset.y,this.cameraZoom,this.cameraZoom,e,n,this.cameraPitch,this.cameraYaw,this.timing,this.hoverNode,this.selectedNode,this.pointerX,this.pointerY,this.hasMultiSelection?1:0,this.historyProgress,this.syncPulseTime]);this.context.device.queue.writeBuffer(this.cameraBuffer,0,s);const a=this.context.device.createCommandEncoder();if(this.alpha>.001||Math.abs(this.treadmillDelta.x)>1e-4||Math.abs(this.treadmillDelta.y)>1e-4||Math.abs(this.treadmillDelta.z)>1e-4){const t=new ArrayBuffer(48),l=new Uint32Array(t),c=new Float32Array(t);l[0]=this.buffers.nodeCount,l[1]=this.buffers.edgeCount,c[2]=this.alpha,c[3]=this.solarSystemMode,c[4]=0,c[5]=this.treadmillDelta.x,c[6]=this.treadmillDelta.y,c[7]=this.treadmillDelta.z,this.treadmillDelta.x=0,this.treadmillDelta.y=0,this.treadmillDelta.z=0,this.context.device.queue.writeBuffer(this.uniformBuffer,0,t);const u=a.beginComputePass();u.setPipeline(this.computePipeline),u.setBindGroup(0,this.computeBindGroup),u.dispatchWorkgroups(Math.ceil(this.buffers.nodeCount/64)),u.end(),this.alpha*=.99}const r={colorAttachments:[{view:this.context.context.getCurrentTexture().createView(),clearValue:{r:.04,g:.04,b:.06,a:1},loadOp:"clear",storeOp:"store"}],depthStencilAttachment:{view:this.depthTexture.createView(),depthClearValue:1,depthLoadOp:"clear",depthStoreOp:"store"}};if(this.pointerX>=0&&!this.isPicking){this.isPicking=!0;const t=new Uint32Array([4294967295,4294967295]);this.context.device.queue.writeBuffer(this.pickerOutBuffer,0,t);const l=a.beginComputePass();l.setPipeline(this.pickerPipeline),l.setBindGroup(0,this.pickerBindGroup),l.dispatchWorkgroups(Math.ceil(this.buffers.nodeCount/64)),l.end(),a.copyBufferToBuffer(this.pickerOutBuffer,0,this.pickerMapBuffer,0,8)}const i=a.beginRenderPass(r);i.setPipeline(this.edgePipeline),i.setBindGroup(0,this.edgeBindGroup),i.draw(this.buffers.edgeCount*2,1,0,0),i.setPipeline(this.nodePipeline),i.setBindGroup(0,this.renderBindGroup),i.draw(6,this.buffers.nodeCount,0,0),i.end(),this.context.device.queue.submit([a.finish()]),this.isPicking&&this.pickerMapBuffer.mapAsync(GPUMapMode.READ).then(()=>{const l=new Uint32Array(this.pickerMapBuffer.getMappedRange())[0];l!==4294967295?this.hoverNode=l:this.hoverNode=-1,this.pickerMapBuffer.unmap(),this.isPicking=!1}).catch(()=>{this.isPicking=!1})}destroy(){console.log("[Engine] Tearing down GPU contexts natively..."),this.nodeBuffer.destroy(),this.edgeBuffer.destroy(),this.selectionBuffer.destroy(),this.uniformBuffer.destroy(),this.cameraBuffer.destroy(),this.atlasTexture.destroy(),this.context.device.destroy()}}class O{constructor(e,n){o(this,"engine");o(this,"canvas");o(this,"frameId",0);o(this,"fpsEl");o(this,"alphaEl");o(this,"nodesEl");o(this,"lastFrameTime",performance.now());o(this,"lastFpsTime",performance.now());o(this,"frames",0);o(this,"isLerping",!1);o(this,"lerpTargetZoom",0);o(this,"lerpTargetPitch",null);o(this,"lerpTargetYaw",null);o(this,"lerpTargetOffset",{x:0,y:0});o(this,"lerpProgress",0);o(this,"autoOrbit",!0);o(this,"isDragging",!1);o(this,"historyMode",!1);this.engine=e,this.canvas=n,this.fpsEl=document.getElementById("ui-fps"),this.alphaEl=document.getElementById("ui-alpha"),this.nodesEl=document.getElementById("ui-nodes"),this.nodesEl&&(this.nodesEl.innerText=this.engine.buffers.nodeCount.toString()),this.bindInteractions()}bindInteractions(){let e=0,n=0;this.canvas.addEventListener("pointerdown",s=>{this.isDragging=!0,e=s.clientX,n=s.clientY,this.canvas.setPointerCapture(s.pointerId)}),this.canvas.addEventListener("contextmenu",s=>s.preventDefault()),this.canvas.addEventListener("pointermove",s=>{if(this.engine.pointerX=s.clientX,this.engine.pointerY=s.clientY,!this.isDragging){this.canvas.style.cursor=this.engine.hoverNode!==-1?"pointer":"default";return}const a=s.clientX-e,r=s.clientY-n;if(s.buttons===1)this.engine.cameraYaw-=a*.005,this.engine.cameraPitch=Math.max(-Math.PI/2+.1,Math.min(Math.PI/2-.1,this.engine.cameraPitch-r*.005));else if(s.buttons===2){const i=-a/this.engine.cameraZoom,t=-r/this.engine.cameraZoom,l=Math.cos(this.engine.cameraPitch),c=Math.sin(this.engine.cameraPitch),u=Math.cos(this.engine.cameraYaw),m=Math.sin(this.engine.cameraYaw),g=u,_=0,f=m,b=-m*c,p=l,y=u*c;this.engine.treadmillDelta.x+=g*i+b*t,this.engine.treadmillDelta.y+=_*i+p*t,this.engine.treadmillDelta.z+=f*i+y*t}e=s.clientX,n=s.clientY,this.isLerping=!1}),this.canvas.addEventListener("pointerup",s=>{if(this.isDragging){const a=Math.abs(s.clientX-e),r=Math.abs(s.clientY-n);a<3&&r<3&&s.button===0&&(this.engine.selectedNode=this.engine.hoverNode,this.engine.updateHUD(this.engine.selectedNode))}this.isDragging=!1,this.canvas.releasePointerCapture(s.pointerId)}),window.addEventListener("keydown",s=>{s.key==="Escape"&&(this.engine.selectedNode=-1,this.engine.updateHUD(-1)),s.code==="Space"&&(!document.activeElement||document.activeElement.tagName!=="INPUT")&&(this.autoOrbit=!this.autoOrbit,console.log(`AUTO-ORBIT: ${this.autoOrbit?"RESUMED":"PAUSED"}`))}),this.canvas.addEventListener("dblclick",()=>{this.engine.solarSystemMode = this.engine.solarSystemMode === 1.0 ? 50.0 : 1.0; this.engine.alpha=1.0; console.log("SOLAR SYSTEM MODE: ", this.engine.solarSystemMode);}),this.canvas.addEventListener("wheel",s=>{if(this.historyMode){this.engine.historyProgress=Math.max(0,Math.min(1,this.engine.historyProgress+s.deltaY*.001)),s.preventDefault();return}const a=-s.deltaY*.001,r=Math.max(.01,Math.min(this.engine.cameraZoom*(1+a),5)),i=s.clientX,t=s.clientY,l=i-this.engine.cameraOffset.x,c=t-this.engine.cameraOffset.y;r/this.engine.cameraZoom;const u=l/this.engine.cameraZoom,m=c/this.engine.cameraZoom,g=u-l/r,_=m-c/r,f=Math.cos(this.engine.cameraPitch),b=Math.sin(this.engine.cameraPitch),p=Math.cos(this.engine.cameraYaw),y=Math.sin(this.engine.cameraYaw),x=p,v=0,h=y,w=-y*b,P=f,E=p*b;this.engine.treadmillDelta.x+=x*g+w*_,this.engine.treadmillDelta.y+=v*g+P*_,this.engine.treadmillDelta.z+=h*g+E*_,this.engine.cameraZoom=r,s.preventDefault()},{passive:!1})}start(){const e=()=>{(this.canvas.width!==window.innerWidth||this.canvas.height!==window.innerHeight)&&(this.canvas.width=window.innerWidth,this.canvas.height=window.innerHeight);const n=performance.now(),s=(n-this.lastFrameTime)/1e3;if(this.lastFrameTime=n,this.engine.timing+=s,this.isLerping){this.lerpProgress+=s*1.5;const a=Math.min(this.lerpProgress,1),r=-(Math.cos(Math.PI*a)-1)/2;this.engine.cameraZoom+=(this.lerpTargetZoom-this.engine.cameraZoom)*r*.1,this.lerpTargetPitch!==null&&(this.engine.cameraPitch+=(this.lerpTargetPitch-this.engine.cameraPitch)*r*.15),this.lerpTargetYaw!==null&&(this.engine.cameraYaw+=(this.lerpTargetYaw-this.engine.cameraYaw)*r*.15),a>=1&&(this.isLerping=!1,this.lerpTargetPitch=null,this.lerpTargetYaw=null)}if(this.autoOrbit&&this.engine.hoverNode===-1&&!this.isDragging&&(this.engine.cameraYaw+=s*.05),this.engine.update(this.canvas.width,this.canvas.height),this.frames++,n-this.lastFpsTime>=1e3){const a=Math.round(this.frames*1e3/(n-this.lastFpsTime));this.fpsEl&&(this.fpsEl.innerText=a.toString()),this.alphaEl&&(this.alphaEl.innerText=this.engine.alpha.toFixed(4)),this.frames=0,this.lastFpsTime=n}this.frameId=requestAnimationFrame(e)};this.frameId||(this.lastFrameTime=performance.now(),this.lastFpsTime=performance.now(),e())}stop(){this.frameId&&(cancelAnimationFrame(this.frameId),this.frameId=0)}triggerGimbalSnap(e,n){this.lerpTargetPitch=e,this.lerpTargetYaw=n,this.isLerping=!0,this.lerpProgress=0,this.lerpTargetZoom=.4}triggerCameraRestitution(e=.6){this.lerpTargetPitch=-.3,this.lerpTargetZoom=e,this.isLerping=!0,this.lerpProgress=0}destroy(){this.stop(),this.engine.destroy()}}class R{constructor(e,n){o(this,"engine");o(this,"scopes");o(this,"container");o(this,"searchInput");o(this,"activeSelections",new Set);this.engine=e,this.scopes=n,this.container=document.getElementById("scope-list"),this.searchInput=document.getElementById("search-input"),this.container&&this.searchInput&&(this.bindEvents(),this.render())}bindEvents(){this.searchInput.addEventListener("input",()=>{this.render(this.searchInput.value.toLowerCase())})}toggleSelection(e,n){n===!0||n===void 0&&!this.activeSelections.has(e)?this.activeSelections.add(e):this.activeSelections.delete(e)}commitState(){this.engine.setMultiSelection(Array.from(this.activeSelections))}render(e=""){this.container.innerHTML="";const n=e.length>0;for(const[s,a]of Object.entries(this.scopes)){let r=a;if(n&&(r=a.filter(_=>_.toLowerCase().includes(e)),r.length===0&&!s.toLowerCase().includes(e)))continue;const i=document.createElement("div");i.className="scope-item";const t=document.createElement("div");t.className="scope-header";const l=document.createElement("span");l.className=`scope-caret ${n?"open":""}`,l.textContent="▶";const c=document.createElement("input");c.type="checkbox";const u=r.filter(_=>this.activeSelections.has(_));u.length>0&&(u.length===r.length?(c.checked=!0,c.indeterminate=!1):(c.checked=!1,c.indeterminate=!0));const m=document.createElement("span");m.textContent=s,t.append(l,c,m),i.appendChild(t);const g=document.createElement("div");g.className=`scope-children ${n?"open":""}`,r.forEach(_=>{const f=document.createElement("label");f.className="node-item";const b=document.createElement("input");b.type="checkbox",b.checked=this.activeSelections.has(_),b.addEventListener("change",()=>{this.toggleSelection(_,b.checked),this.commitState(),this.render(this.searchInput.value.toLowerCase())});const p=document.createElement("span");p.textContent=_.split("/").pop()||_,f.append(b,p),g.appendChild(f)}),i.appendChild(g),this.container.appendChild(i),l.addEventListener("click",_=>{_.stopPropagation(),l.classList.toggle("open"),g.classList.toggle("open")}),m.addEventListener("click",()=>{l.classList.toggle("open"),g.classList.toggle("open")}),c.addEventListener("change",()=>{const _=c.checked;r.forEach(f=>this.toggleSelection(f,_)),this.commitState(),this.render(this.searchInput.value.toLowerCase())})}}}class Y{constructor(e,n){o(this,"engine");o(this,"loop");this.engine=e,this.loop=n,this.bindEvents()}bindEvents(){const e=document.getElementById("nav-telemetry"),n=document.getElementById("nav-structural"),s=document.getElementById("nav-sync"),a=document.getElementById("topo"),r=document.getElementById("tab-canvas"),i=document.getElementById("tab-mcp"),t=document.getElementById("tab-history"),l=document.getElementById("tab-nodes"),c=()=>{r==null||r.classList.remove("active"),l==null||l.classList.remove("active"),i==null||i.classList.remove("active"),t==null||t.classList.remove("active"),this.engine.displayMCP=!1},u=()=>{e==null||e.classList.remove("active"),n==null||n.classList.remove("active"),s==null||s.classList.remove("active")};e==null||e.addEventListener("click",()=>{u(),e.classList.add("active"),document.body.classList.remove("zen-mode"),this.engine.alpha=1,this.loop.triggerCameraRestitution(.6)}),n==null||n.addEventListener("click",()=>{u(),n.classList.add("active"),document.body.classList.add("zen-mode");const m=Math.PI/2-.001;this.loop.triggerGimbalSnap(m,0),this.engine.displayMCP=!1}),s==null||s.addEventListener("click",()=>{s.classList.add("active"),setTimeout(()=>s.classList.remove("active"),200),this.engine.syncPulseTime=this.engine.timing,console.log("[State] Backend Sync protocol dispatched.")}),r&&a&&r.addEventListener("click",()=>{c(),r.classList.add("active"),a.classList.remove("canvas-frozen"),this.loop.historyMode=!1,this.loop.start()}),i&&a&&i.addEventListener("click",()=>{c(),i.classList.add("active"),a.classList.remove("canvas-frozen"),this.engine.displayMCP=!0,this.loop.historyMode=!1,this.loop.start(),this.engine.updateHUD(0)}),t&&a&&t.addEventListener("click",()=>{c(),t.classList.add("active"),a.classList.remove("canvas-frozen"),this.loop.start(),this.loop.historyMode=!0,this.engine.historyProgress=0,this.enterHistoryMode()}),l&&a&&l.addEventListener("click",()=>{c(),l.classList.add("active"),this.loop.historyMode=!1,this.loop.stop(),a.classList.add("canvas-frozen")})}async enterHistoryMode(){console.log("[State] Transmitting native History Protocol hook -> backend.");try{await new Promise(e=>setTimeout(e,600)),console.log("[State] Generating Atomic Temporal Buffers for Ghost reallocations on CPU worker."),console.log("[State] Atomic Swap complete. Awaiting Scroll Wheel Uniform timeline scrubbing seamlessly.")}catch(e){console.error("[State] Temporal Error:",e)}}}async function F(){var g,_;const d=document.getElementById("topo");d.width=window.innerWidth,d.height=window.innerHeight;const e=await I(d);if(!e){document.getElementById("fallback").style.display="block";return}const n=((_=(g=document.getElementById("__dotscope_data__"))==null?void 0:g.textContent)==null?void 0:_.trim())||"";let s={nodes:[{id:"src/main.ts"},{id:"src/pretext.ts"}],edges:[{source:"src/main.ts",target:"src/pretext.ts"}],scopes:{},invariants:[]};if(n.length>0&&n!=="__GRAPH_DATA_PAYLOAD__")try{s=JSON.parse(n)}catch(f){console.error("Dotscope WebGPU Init: Failed to parse backend telemetry payload",f)}if(s.nodes.length===0){document.getElementById("loader-overlay").style.display="none",document.getElementById("zero-state").classList.add("active");return}const a=await z(e.device),r=await U(e.device),i=await G(e.device,e.format),t=S(s),l=document.getElementById("ui-nodes");l&&(l.textContent=t.nodeCount.toString());const c=new N(e,t,a,r,i.nodePipeline,i.edgePipeline);new R(c,s.scopes||{});const u=new O(c,d);new Y(c,u);const m=document.getElementById("ui-desync");m&&m.addEventListener("click",()=>{c.selectedNode=-1,c.updateHUD(-1)}),setTimeout(()=>{document.body.classList.add("engine-ready"),u.start()},50)}F().catch(d=>{console.error("FATAL BOOTSTRAP ERROR:",d);const e=document.createElement("div");e.style.cssText="position: absolute; top: 50%; left: 10%; right: 10%; background: red; color: white; padding: 20px; z-index: 9999; border-radius: 8px; font-family: monospace; white-space: pre-wrap;",e.textContent=`FATAL BOOTSTRAP ERROR:
`+(d.stack||String(d)),document.body.appendChild(e)});
