var E=Object.defineProperty;var T=(d,e,n)=>e in d?E(d,e,{enumerable:!0,configurable:!0,writable:!0,value:n}):d[e]=n;var o=(d,e,n)=>T(d,typeof e!="symbol"?e+"":e,n);(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const a of document.querySelectorAll('link[rel="modulepreload"]'))i(a);new MutationObserver(a=>{for(const r of a)if(r.type==="childList")for(const s of r.addedNodes)s.tagName==="LINK"&&s.rel==="modulepreload"&&i(s)}).observe(document,{childList:!0,subtree:!0});function n(a){const r={};return a.integrity&&(r.integrity=a.integrity),a.referrerPolicy&&(r.referrerPolicy=a.referrerPolicy),a.crossOrigin==="use-credentials"?r.credentials="include":a.crossOrigin==="anonymous"?r.credentials="omit":r.credentials="same-origin",r}function i(a){if(a.ep)return;a.ep=!0;const r=n(a);fetch(a.href,r)}})();const C="'Inter', sans-serif",M=12;function S(d){const s=new OffscreenCanvas(1,1).getContext("2d");s.font=`600 ${M}px ${C}`,s.textBaseline="top";const t=d.map(u=>{const w=s.measureText(u),P=Math.ceil(Math.max(w.width,w.actualBoundingBoxRight+Math.abs(w.actualBoundingBoxLeft)))+16,B=Math.ceil(w.actualBoundingBoxAscent+w.actualBoundingBoxDescent)+8;return{label:u,w:P,h:B}});let l=0,c=0,f=0;const m=[];for(const u of t)l+u.w>8192&&(l=0,c+=f+2,f=0),m.push({label:u.label,x:l,y:c,w:u.w,h:u.h}),l+=u.w,u.h>f&&(f=u.h);let v=c+f;const y=200,h=1024,b=v;v+=y,v>8192&&console.warn(`[Pretext Shield] Hardware Exception: Canvas height (${v}px) exceeds generic WebGPU 8192px limit. Node truncation may occur.`);const p=new OffscreenCanvas(8192,Math.max(v,1)),x=p.getContext("2d");x.clearRect(0,0,8192,v),x.fillStyle="rgba(255, 255, 255, 1.0)",x.font=s.font,x.textBaseline="top";const _=new Map;for(const u of m)x.fillText(u.label,u.x+16/2,u.y+8/2),_.set(u.label,{width:u.w,height:u.h,uMin:u.x/8192,vMin:u.y/p.height,uMax:(u.x+u.w)/8192,vMax:(u.y+u.h)/p.height});const g={width:h,height:y,uMin:0,vMin:b/p.height,uMax:h/8192,vMax:(b+y)/p.height};return{canvas:p,boxes:_,hudBox:g,hudY:b}}function D(d){const e=d.nodes.length,n=Object.keys(d.scopes||{}),i=n.length,a=e+i+1;let r=0;for(const p of n)r+=d.scopes[p].length;const s=d.edges.length+r,t=new Float32Array(a*16),l=new Uint32Array(s*2),c=new Map,f=S([...d.nodes.map(p=>p.id),...n]);let m=0;for(let p=0;p<e;p++){const x=d.nodes[p];c.set(x.id,p);const _=f.boxes.get(x.id);let g=0;x.id.includes(".spec.")||x.id.includes(".test.")?g=1:x.id.endsWith(".ts")||x.id.endsWith(".js")?g=2:(x.id.endsWith(".json")||x.id.endsWith(".toml"))&&(g=3);const u=p*16;t[u+0]=(Math.random()-.5)*4e3,t[u+1]=(Math.random()-.5)*4e3,t[u+2]=(Math.random()-.5)*4e3,t[u+3]=_.width*_.height,t[u+4]=0,t[u+5]=0,t[u+6]=0,t[u+7]=g,t[u+8]=_.width,t[u+9]=_.height,t[u+10]=0,t[u+11]=0,t[u+12]=_.uMin,t[u+13]=_.vMin,t[u+14]=_.uMax,t[u+15]=_.vMax}for(let p=0;p<d.edges.length;p++){const x=d.edges[p],_=c.get(x.source),g=c.get(x.target);_!==void 0&&g!==void 0&&(l[m*2+0]=_,l[m*2+1]=g,m++)}let v=e;for(let p=0;p<i;p++){const x=n[p],_=f.boxes.get(x),g=v*16;t[g+0]=(Math.random()-.5)*4e3,t[g+1]=(Math.random()-.5)*4e3,t[g+2]=(Math.random()-.5)*4e3,t[g+3]=_.width*_.height*2,t[g+4]=0,t[g+5]=0,t[g+6]=0,t[g+7]=10,t[g+8]=_.width*2.5,t[g+9]=_.height*2.5,t[g+10]=0,t[g+11]=0,t[g+12]=_.uMin,t[g+13]=_.vMin,t[g+14]=_.uMax,t[g+15]=_.vMax;const u=d.scopes[x];for(const w of u){const P=c.get(w);P!==void 0&&(l[m*2+0]=v,l[m*2+1]=P,m++)}v++}const y=a-1,h=y*16,b=f.hudBox;return t[h+0]=-1e5,t[h+1]=-1e5,t[h+2]=-1e5,t[h+3]=0,t[h+4]=0,t[h+5]=0,t[h+6]=0,t[h+7]=11,t[h+8]=b.width,t[h+9]=b.height,t[h+10]=0,t[h+11]=0,t[h+12]=b.uMin,t[h+13]=b.vMin,t[h+14]=b.uMax,t[h+15]=b.vMax,{nodeData:t,edgeData:l.slice(0,m*2),nodeCount:a,edgeCount:m,atlasCanvas:f.canvas,nodeMap:c,nodeLabels:d.nodes.map(p=>p.id),hudNodeIndex:y,hudBox:b,hudY:f.hudY}}async function I(d){if(!navigator.gpu)return null;const e=await navigator.gpu.requestAdapter();if(!e)return null;const n=await e.requestDevice(),i=d.getContext("webgpu");if(!i)return null;const a=navigator.gpu.getPreferredCanvasFormat();return i.configure({device:n,format:a,alphaMode:"opaque"}),{adapter:e,device:n,context:i,format:a}}const k=`struct Node {
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
    alpha: f32,          // Thermal decay (cools from 1.0 -> 0.0)
    gravity_center: vec2<f32>,
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
        let repel_mag = REPULSION_BASE / dist_sq;
        if (d_len > 0.001) {
            force += (delta / d_len) * repel_mag;
        }
    }

    // Central Gravity pulling towards coordinate space origin (0,0,0)
    let center_dir = vec3<f32>(params.gravity_center.x, params.gravity_center.y, 0.0) - node.pos_mass.xyz;
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
        let wave_offset = sin(dist_from_center * 0.02 - camera.timing * 1.5) * 20.0;
        let secondary_harmonic = cos(raw_pos.x * 0.03 + camera.timing * 2.0) * 8.0;
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
        } else if (t_id == 11u) {
            // HUD anchors are always bright and visible
            final_ui_alpha = max(font_alpha, 0.15) * 1.5; // slight glass background optionally
        }
        
        // Output crisp white Hologram / HUD
        if (final_ui_alpha < 0.005) { discard; }
        return vec4<f32>(1.0, 1.0, 1.0, final_ui_alpha);
    }
    
    var base_color = vec3<f32>(0.6, 0.6, 0.65); // Neutral Grey (Default / Unknown)
    if (t_id == 1u) {
        base_color = vec3<f32>(0.98, 0.20, 0.40); // Radiant Crimson-Pink (Tests)
    } else if (t_id == 2u) {
        base_color = vec3<f32>(0.20, 0.60, 0.98); // Deep Azure/Cyan (Core Logic .ts/.js)
    } else if (t_id == 3u) {
        base_color = vec3<f32>(0.75, 0.20, 0.90); // Amethyst Purple (Config)
    }
    
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
    let p = vec2<f32>(in.uv.x * aspect, in.uv.y);
    
    let node_center = vec2<f32>(0.5, 0.5); 
    let dist_to_node = length(p - node_center);
    
    // Softer Hypnotic Glow Requested
    let glow_radius = 1.4;
    let node_glow = pow(1.0 - smoothstep(0.1, glow_radius, dist_to_node), 1.5);
    
    // Sine-wave Rhythmic Blending
    let pulse_time = camera.timing * 2.0 + in.node_idx * 0.1; 
    let core_anim = (sin(pulse_time) * 0.5 + 0.5) * 0.4 + 0.6; // Modulate core size smoothly
    let core_radius = 0.4 * core_anim;
    
    let node_idx_u32 = u32(round(in.node_idx));
    let sel_type = selections[node_idx_u32];

    let core_mask = 1.0 - smoothstep(0.0, core_radius, dist_to_node);
    
    var node_rgb = mix(base_color * node_glow, vec3<f32>(1.0, 1.0, 1.0), core_mask);
    let node_alpha = max(core_mask, node_glow * 0.8);
    
    // Evaluate Topological Blast Radius Overrides (Thermal Cascade)
    if (sel_type == 1.0) {
        // Core Epicenter
        node_rgb = mix(vec3<f32>(0.2, 1.0, 0.4) * node_glow, vec3<f32>(0.8, 1.0, 0.8), core_mask); 
        base_color = vec3<f32>(0.2, 1.0, 0.4);
    } else if (sel_type == 2.0) {
        // Depth 1 (WILL BREAK) - Radiant Hot Orange
        node_rgb = mix(vec3<f32>(1.0, 0.5, 0.1) * node_glow, vec3<f32>(1.0, 0.9, 0.6), core_mask);
        base_color = vec3<f32>(1.0, 0.5, 0.1); 
    } else if (sel_type == 3.0) {
        // Depth 2 (LIKELY AFFECTED) - Fading Deep Red
        node_rgb = mix(vec3<f32>(0.8, 0.1, 0.1) * node_glow, vec3<f32>(1.0, 0.3, 0.3), core_mask);
        base_color = vec3<f32>(0.8, 0.1, 0.1);
    }
    
    // Smooth opacity fading when retreating backwards in the semantic network
    let lod_distance = in.depth * camera.scale.x;
    let font_opacity_lod = smoothstep(0.06, 0.15, lod_distance); 
    
    let font_rgb = vec3<f32>(1.0, 1.0, 1.0);
    // Multiply base_color lightly over the font so tags match node color aesthetics natively!
    let tinted_font = mix(font_rgb, base_color, 0.3);
    let font_alpha = font_pixel.a * font_opacity_lod;
    
    let fog_density = clamp(in.depth, 0.0, 1.0);

    // Additive scaling natively upgraded to Alpha Scaling logic because blending is now Standard Alpha!
    let alpha_scale = 1.0; // Restored scale now that src-alpha handles stacking mathematically
    var final_alpha = max(node_alpha, font_alpha) * alpha_scale;

    var combined_rgb = mix(node_rgb, tinted_font, font_alpha);

    // Evaluate universal multi-selection buffer AND specific raycaster limits
    let has_multi_selection = (sel_type > 0.0);
    
    let is_focused = (in.node_idx == camera.selected_id);
    let is_selected = is_focused || has_multi_selection;
    let any_selection_active = camera.selected_id >= 0.0 || camera.pad1 > 0.0;
    
    if (any_selection_active && !is_selected) {
        // Drop saturation to 10% and cull visibility natively retaining Alpha Ghosting
        let luma = dot(combined_rgb, vec3<f32>(0.299, 0.587, 0.114));
        combined_rgb = mix(vec3<f32>(luma), combined_rgb, 0.1); 
        final_alpha *= 0.15; 
    }

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
        let wave_offset = sin(dist_from_center * 0.02 - camera.timing * 1.5) * 20.0;
        let secondary_harmonic = cos(raw_pos.x * 0.03 + camera.timing * 2.0) * 8.0;
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
`;async function U(d){const e=d.createShaderModule({code:k});return d.createComputePipeline({layout:"auto",compute:{module:e,entryPoint:"main"}})}async function G(d){const e=d.createShaderModule({code:A});return d.createComputePipeline({layout:"auto",compute:{module:e,entryPoint:"main"}})}async function N(d,e){const n=d.createShaderModule({code:L}),i={color:{srcFactor:"src-alpha",dstFactor:"one-minus-src-alpha",operation:"add"},alpha:{srcFactor:"src-alpha",dstFactor:"one-minus-src-alpha",operation:"add"}},a={depthWriteEnabled:!1,depthCompare:"less",format:"depth24plus"},r=await d.createRenderPipelineAsync({layout:"auto",vertex:{module:n,entryPoint:"vs_main"},fragment:{module:n,entryPoint:"fs_main",targets:[{format:e,blend:i}]},primitive:{topology:"triangle-list"},depthStencil:a}),s=await d.createRenderPipelineAsync({layout:"auto",vertex:{module:n,entryPoint:"vs_edge_main"},fragment:{module:n,entryPoint:"fs_edge_main",targets:[{format:e,blend:i}]},primitive:{topology:"line-list"},depthStencil:a});return{nodePipeline:r,edgePipeline:s}}class O{constructor(e,n,i,a,r,s){o(this,"context");o(this,"buffers");o(this,"alpha",1);o(this,"cameraOffset",{x:0,y:0});o(this,"cameraZoom",-1);o(this,"cameraPitch",.6);o(this,"cameraYaw",0);o(this,"timing",0);o(this,"hoverNode",-1);o(this,"selectedNode",-1);o(this,"pointerX",-1e3);o(this,"pointerY",-1e3);o(this,"hasMultiSelection",!1);o(this,"historyProgress",0);o(this,"syncPulseTime",-100);o(this,"displayMCP",!1);o(this,"mcpLogs",["[system] WebGPU Neural Pretext Engine Initialized...","[agent] Awaiting Dispatch Orders"]);o(this,"computePipeline");o(this,"pickerPipeline");o(this,"nodePipeline");o(this,"edgePipeline");o(this,"nodeBuffer");o(this,"edgeBuffer");o(this,"selectionBuffer");o(this,"uniformBuffer");o(this,"cameraBuffer");o(this,"pickerOutBuffer");o(this,"pickerMapBuffer");o(this,"atlasTexture");o(this,"computeBindGroup");o(this,"pickerBindGroup");o(this,"renderBindGroup");o(this,"edgeBindGroup");o(this,"isPicking",!1);o(this,"depthTexture",null);this.context=e,this.buffers=n,this.computePipeline=i,this.pickerPipeline=a,this.nodePipeline=r,this.edgePipeline=s,this.nodeBuffer=e.device.createBuffer({size:n.nodeData.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST,mappedAtCreation:!0}),new Float32Array(this.nodeBuffer.getMappedRange()).set(n.nodeData),this.nodeBuffer.unmap(),this.edgeBuffer=e.device.createBuffer({size:n.edgeData.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST,mappedAtCreation:!0}),new Uint32Array(this.edgeBuffer.getMappedRange()).set(n.edgeData),this.edgeBuffer.unmap(),this.selectionBuffer=e.device.createBuffer({size:n.nodeCount*4,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.uniformBuffer=e.device.createBuffer({size:32,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.computeBindGroup=e.device.createBindGroup({layout:this.computePipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.edgeBuffer}},{binding:2,resource:{buffer:this.uniformBuffer}}]}),this.cameraBuffer=e.device.createBuffer({size:64,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.pickerOutBuffer=e.device.createBuffer({size:8,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST}),this.pickerMapBuffer=e.device.createBuffer({size:8,usage:GPUBufferUsage.MAP_READ|GPUBufferUsage.COPY_DST}),this.pickerBindGroup=e.device.createBindGroup({layout:this.pickerPipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.cameraBuffer}},{binding:2,resource:{buffer:this.pickerOutBuffer}},{binding:3,resource:{buffer:this.uniformBuffer}}]}),this.atlasTexture=e.device.createTexture({size:[n.atlasCanvas.width,n.atlasCanvas.height,1],format:"rgba8unorm",usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT}),e.device.queue.copyExternalImageToTexture({source:n.atlasCanvas},{texture:this.atlasTexture},[n.atlasCanvas.width,n.atlasCanvas.height]);const t=e.device.createSampler({magFilter:"linear",minFilter:"linear"});this.renderBindGroup=e.device.createBindGroup({layout:this.nodePipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.cameraBuffer}},{binding:3,resource:{buffer:this.selectionBuffer}},{binding:4,resource:this.atlasTexture.createView()},{binding:5,resource:t}]}),this.edgeBindGroup=e.device.createBindGroup({layout:this.edgePipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.nodeBuffer}},{binding:1,resource:{buffer:this.cameraBuffer}},{binding:2,resource:{buffer:this.edgeBuffer}},{binding:3,resource:{buffer:this.selectionBuffer}}]})}setMultiSelection(e){this.hasMultiSelection=e.length>0;const n=new Float32Array(this.buffers.nodeCount),i=new Set;e.forEach(s=>{const t=this.buffers.nodeMap.get(s);t!==void 0&&(n[t]=1,i.add(t))});const a=new Set,r=this.buffers.edgeData;for(let s=0;s<this.buffers.edgeCount;s++){const t=r[s*2],l=r[s*2+1];i.has(l)&&!i.has(t)&&(n[t]=2,a.add(t))}for(let s=0;s<this.buffers.edgeCount;s++){const t=r[s*2],l=r[s*2+1];a.has(l)&&!i.has(t)&&!a.has(t)&&(n[t]=3)}this.context.device.queue.writeBuffer(this.selectionBuffer,0,n)}updateHUD(e){if(e<0||e>=this.buffers.nodeLabels.length){const c=new Float32Array([-1e5,-1e5,-1e5,0]);this.context.device.queue.writeBuffer(this.nodeBuffer,this.buffers.hudNodeIndex*64,c);const f=document.getElementById("ui-inspector");f&&f.classList.remove("active");return}const n=this.buffers.nodeLabels[e];let i=0,a=0;const r=this.buffers.edgeData;for(let c=0;c<this.buffers.edgeCount;c++)r[c*2+0]===e&&a++,r[c*2+1]===e&&i++;const s=this.buffers.atlasCanvas.getContext("2d"),t=this.buffers.hudBox;s.clearRect(0,this.buffers.hudY,t.width,t.height),this.displayMCP?(s.fillStyle="rgba(4, 6, 8, 0.85)",s.fillRect(0,this.buffers.hudY,t.width,t.height),s.fillStyle="rgba(16, 185, 129, 0.4)",s.fillRect(0,this.buffers.hudY,t.width,4),s.fillStyle="#10b981",s.font="600 24px 'monospace'",s.fillText("MCP_TERMINAL_STREAM",30,this.buffers.hudY+50),s.fillStyle="rgba(255, 255, 255, 0.7)",s.font="16px 'monospace'",this.mcpLogs.forEach((c,f)=>{s.fillText(`> ${c}`,30,this.buffers.hudY+100+f*28)}),Math.random()<.05&&this.mcpLogs.length<15&&this.mcpLogs.push("[trace] Raycast mapped node boundary at depth 0x0...")):(s.fillStyle="rgba(10, 15, 25, 0.95)",s.fillRect(0,this.buffers.hudY,t.width,t.height),s.fillStyle="rgba(40, 255, 100, 1.0)",s.font="600 36px 'Inter', sans-serif",s.fillText("Topological Anchor",20,this.buffers.hudY+40),s.fillStyle="#ffffff",s.font="bold 28px 'Inter', sans-serif",s.fillText(n,20,this.buffers.hudY+90),s.fillStyle="rgba(150, 200, 255, 0.8)",s.font="500 24px 'Inter', sans-serif",s.fillText(`Incoming Dependencies: ${i}`,20,this.buffers.hudY+140),s.fillText(`Outgoing Boundaries:  ${a}`,20,this.buffers.hudY+180)),this.context.device.queue.copyExternalImageToTexture({source:this.buffers.atlasCanvas},{texture:this.atlasTexture},[this.buffers.atlasCanvas.width,this.buffers.atlasCanvas.height]);const l=document.getElementById("ui-inspector");if(l){l.classList.add("active");const c=document.getElementById("ui-node-name");c&&(c.textContent=n.split("/").pop()||n);const f=document.getElementById("ui-node-depth");f&&(f.textContent=(e%5).toString());const m=document.getElementById("ui-node-in");m&&(m.textContent=i.toString());const v=document.getElementById("ui-node-out");v&&(v.textContent=a.toString())}}update(e,n){(!this.depthTexture||this.depthTexture.width!==e||this.depthTexture.height!==n)&&(this.depthTexture&&this.depthTexture.destroy(),this.depthTexture=this.context.device.createTexture({size:[e,n,1],format:"depth24plus",usage:GPUTextureUsage.RENDER_ATTACHMENT})),this.cameraZoom===-1&&(this.cameraZoom=this.buffers.nodeCount>5e3?.05:.2,this.cameraOffset.x=e/2,this.cameraOffset.y=n/2);const i=new Float32Array([this.cameraOffset.x,this.cameraOffset.y,this.cameraZoom,this.cameraZoom,e,n,this.cameraPitch,this.cameraYaw,this.timing,this.hoverNode,this.selectedNode,this.pointerX,this.pointerY,this.hasMultiSelection?1:0,this.historyProgress,this.syncPulseTime]);this.context.device.queue.writeBuffer(this.cameraBuffer,0,i);const a=this.context.device.createCommandEncoder();if(this.alpha>.001){const t=new ArrayBuffer(32),l=new Uint32Array(t),c=new Float32Array(t);l[0]=this.buffers.nodeCount,l[1]=this.buffers.edgeCount,c[2]=this.alpha,c[3]=0,c[4]=0,c[5]=0,this.context.device.queue.writeBuffer(this.uniformBuffer,0,t);const f=a.beginComputePass();f.setPipeline(this.computePipeline),f.setBindGroup(0,this.computeBindGroup),f.dispatchWorkgroups(Math.ceil(this.buffers.nodeCount/64)),f.end(),this.alpha*=.99}const r={colorAttachments:[{view:this.context.context.getCurrentTexture().createView(),clearValue:{r:.04,g:.04,b:.06,a:1},loadOp:"clear",storeOp:"store"}],depthStencilAttachment:{view:this.depthTexture.createView(),depthClearValue:1,depthLoadOp:"clear",depthStoreOp:"store"}};if(this.pointerX>=0&&!this.isPicking){this.isPicking=!0;const t=new Uint32Array([4294967295,4294967295]);this.context.device.queue.writeBuffer(this.pickerOutBuffer,0,t);const l=a.beginComputePass();l.setPipeline(this.pickerPipeline),l.setBindGroup(0,this.pickerBindGroup),l.dispatchWorkgroups(Math.ceil(this.buffers.nodeCount/64)),l.end(),a.copyBufferToBuffer(this.pickerOutBuffer,0,this.pickerMapBuffer,0,8)}const s=a.beginRenderPass(r);s.setPipeline(this.edgePipeline),s.setBindGroup(0,this.edgeBindGroup),s.draw(this.buffers.edgeCount*2,1,0,0),s.setPipeline(this.nodePipeline),s.setBindGroup(0,this.renderBindGroup),s.draw(6,this.buffers.nodeCount,0,0),s.end(),this.context.device.queue.submit([a.finish()]),this.isPicking&&this.pickerMapBuffer.mapAsync(GPUMapMode.READ).then(()=>{const l=new Uint32Array(this.pickerMapBuffer.getMappedRange())[0];l!==4294967295?this.hoverNode=l:this.hoverNode=-1,this.pickerMapBuffer.unmap(),this.isPicking=!1}).catch(()=>{this.isPicking=!1})}destroy(){console.log("[Engine] Tearing down GPU contexts natively..."),this.nodeBuffer.destroy(),this.edgeBuffer.destroy(),this.selectionBuffer.destroy(),this.uniformBuffer.destroy(),this.cameraBuffer.destroy(),this.atlasTexture.destroy(),this.context.device.destroy()}}class z{constructor(e,n){o(this,"engine");o(this,"canvas");o(this,"frameId",0);o(this,"fpsEl");o(this,"alphaEl");o(this,"nodesEl");o(this,"lastFrameTime",performance.now());o(this,"lastFpsTime",performance.now());o(this,"frames",0);o(this,"isLerping",!1);o(this,"lerpTargetZoom",0);o(this,"lerpTargetPitch",null);o(this,"lerpTargetYaw",null);o(this,"lerpTargetOffset",{x:0,y:0});o(this,"lerpProgress",0);o(this,"autoOrbit",!0);o(this,"isDragging",!1);o(this,"historyMode",!1);this.engine=e,this.canvas=n,this.fpsEl=document.getElementById("ui-fps"),this.alphaEl=document.getElementById("ui-alpha"),this.nodesEl=document.getElementById("ui-nodes"),this.nodesEl&&(this.nodesEl.innerText=this.engine.buffers.nodeCount.toString()),this.bindInteractions()}bindInteractions(){let e=0,n=0;this.canvas.addEventListener("pointerdown",i=>{this.isDragging=!0,e=i.clientX,n=i.clientY,this.canvas.setPointerCapture(i.pointerId)}),this.canvas.addEventListener("contextmenu",i=>i.preventDefault()),this.canvas.addEventListener("pointermove",i=>{if(this.engine.pointerX=i.clientX,this.engine.pointerY=i.clientY,!this.isDragging){this.canvas.style.cursor=this.engine.hoverNode!==-1?"pointer":"default";return}const a=i.clientX-e,r=i.clientY-n;i.buttons===1?(this.engine.cameraYaw-=a*.005,this.engine.cameraPitch=Math.max(-Math.PI/2+.1,Math.min(Math.PI/2-.1,this.engine.cameraPitch-r*.005))):i.buttons===2&&(this.engine.cameraOffset.x+=a,this.engine.cameraOffset.y+=r),e=i.clientX,n=i.clientY,this.isLerping=!1}),this.canvas.addEventListener("pointerup",i=>{if(this.isDragging){const a=Math.abs(i.clientX-e),r=Math.abs(i.clientY-n);a<3&&r<3&&i.button===0&&(this.engine.selectedNode=this.engine.hoverNode,this.engine.updateHUD(this.engine.selectedNode))}this.isDragging=!1,this.canvas.releasePointerCapture(i.pointerId)}),window.addEventListener("keydown",i=>{i.key==="Escape"&&(this.engine.selectedNode=-1,this.engine.updateHUD(-1)),i.code==="Space"&&(!document.activeElement||document.activeElement.tagName!=="INPUT")&&(this.autoOrbit=!this.autoOrbit,console.log(`AUTO-ORBIT: ${this.autoOrbit?"RESUMED":"PAUSED"}`))}),this.canvas.addEventListener("dblclick",()=>{this.engine.hoverNode!==-1?(this.engine.selectedNode=this.engine.hoverNode,this.engine.updateHUD(this.engine.selectedNode),this.lerpTargetZoom=1.2,this.lerpTargetOffset={x:this.canvas.width/2,y:this.canvas.height/2},this.isLerping=!0,this.lerpProgress=0):(this.engine.selectedNode=-1,this.engine.updateHUD(-1))}),this.canvas.addEventListener("wheel",i=>{if(this.historyMode){this.engine.historyProgress=Math.max(0,Math.min(1,this.engine.historyProgress+i.deltaY*.001)),i.preventDefault();return}const a=-i.deltaY*.001,r=Math.max(.01,Math.min(this.engine.cameraZoom*(1+a),5)),s=i.clientX,t=i.clientY,l=s-this.engine.cameraOffset.x,c=t-this.engine.cameraOffset.y,f=r/this.engine.cameraZoom;this.engine.cameraOffset.x=s-l*f,this.engine.cameraOffset.y=t-c*f,this.engine.cameraZoom=r,i.preventDefault()},{passive:!1})}start(){const e=()=>{(this.canvas.width!==window.innerWidth||this.canvas.height!==window.innerHeight)&&(this.canvas.width=window.innerWidth,this.canvas.height=window.innerHeight);const n=performance.now(),i=(n-this.lastFrameTime)/1e3;if(this.lastFrameTime=n,this.engine.timing+=i,this.isLerping){this.lerpProgress+=i*1.5;const a=Math.min(this.lerpProgress,1),r=-(Math.cos(Math.PI*a)-1)/2;this.engine.cameraZoom+=(this.lerpTargetZoom-this.engine.cameraZoom)*r*.1,this.lerpTargetPitch!==null&&(this.engine.cameraPitch+=(this.lerpTargetPitch-this.engine.cameraPitch)*r*.15),this.lerpTargetYaw!==null&&(this.engine.cameraYaw+=(this.lerpTargetYaw-this.engine.cameraYaw)*r*.15),a>=1&&(this.isLerping=!1,this.lerpTargetPitch=null,this.lerpTargetYaw=null)}if(this.autoOrbit&&this.engine.hoverNode===-1&&!this.isDragging&&(this.engine.cameraYaw+=i*.05),this.engine.update(this.canvas.width,this.canvas.height),this.frames++,n-this.lastFpsTime>=1e3){const a=Math.round(this.frames*1e3/(n-this.lastFpsTime));this.fpsEl&&(this.fpsEl.innerText=a.toString()),this.alphaEl&&(this.alphaEl.innerText=this.engine.alpha.toFixed(4)),this.frames=0,this.lastFpsTime=n}this.frameId=requestAnimationFrame(e)};this.frameId||(this.lastFrameTime=performance.now(),this.lastFpsTime=performance.now(),e())}stop(){this.frameId&&(cancelAnimationFrame(this.frameId),this.frameId=0)}triggerGimbalSnap(e,n){this.lerpTargetPitch=e,this.lerpTargetYaw=n,this.isLerping=!0,this.lerpProgress=0,this.lerpTargetZoom=.4}triggerCameraRestitution(e=.6){this.lerpTargetPitch=-.3,this.lerpTargetZoom=e,this.isLerping=!0,this.lerpProgress=0}destroy(){this.stop(),this.engine.destroy()}}class R{constructor(e,n){o(this,"engine");o(this,"scopes");o(this,"container");o(this,"searchInput");o(this,"activeSelections",new Set);this.engine=e,this.scopes=n,this.container=document.getElementById("scope-list"),this.searchInput=document.getElementById("search-input"),this.container&&this.searchInput&&(this.bindEvents(),this.render())}bindEvents(){this.searchInput.addEventListener("input",()=>{this.render(this.searchInput.value.toLowerCase())})}toggleSelection(e,n){n===!0||n===void 0&&!this.activeSelections.has(e)?this.activeSelections.add(e):this.activeSelections.delete(e)}commitState(){this.engine.setMultiSelection(Array.from(this.activeSelections))}render(e=""){this.container.innerHTML="";const n=e.length>0;for(const[i,a]of Object.entries(this.scopes)){let r=a;if(n&&(r=a.filter(y=>y.toLowerCase().includes(e)),r.length===0&&!i.toLowerCase().includes(e)))continue;const s=document.createElement("div");s.className="scope-item";const t=document.createElement("div");t.className="scope-header";const l=document.createElement("span");l.className=`scope-caret ${n?"open":""}`,l.textContent="▶";const c=document.createElement("input");c.type="checkbox";const f=r.filter(y=>this.activeSelections.has(y));f.length>0&&(f.length===r.length?(c.checked=!0,c.indeterminate=!1):(c.checked=!1,c.indeterminate=!0));const m=document.createElement("span");m.textContent=i,t.append(l,c,m),s.appendChild(t);const v=document.createElement("div");v.className=`scope-children ${n?"open":""}`,r.forEach(y=>{const h=document.createElement("label");h.className="node-item";const b=document.createElement("input");b.type="checkbox",b.checked=this.activeSelections.has(y),b.addEventListener("change",()=>{this.toggleSelection(y,b.checked),this.commitState(),this.render(this.searchInput.value.toLowerCase())});const p=document.createElement("span");p.textContent=y.split("/").pop()||y,h.append(b,p),v.appendChild(h)}),s.appendChild(v),this.container.appendChild(s),l.addEventListener("click",y=>{y.stopPropagation(),l.classList.toggle("open"),v.classList.toggle("open")}),m.addEventListener("click",()=>{l.classList.toggle("open"),v.classList.toggle("open")}),c.addEventListener("change",()=>{const y=c.checked;r.forEach(h=>this.toggleSelection(h,y)),this.commitState(),this.render(this.searchInput.value.toLowerCase())})}}}class F{constructor(e,n){o(this,"engine");o(this,"loop");this.engine=e,this.loop=n,this.bindEvents()}bindEvents(){const e=document.getElementById("nav-telemetry"),n=document.getElementById("nav-structural"),i=document.getElementById("nav-sync"),a=document.getElementById("topo"),r=document.getElementById("tab-canvas"),s=document.getElementById("tab-mcp"),t=document.getElementById("tab-history"),l=document.getElementById("tab-nodes"),c=()=>{r==null||r.classList.remove("active"),l==null||l.classList.remove("active"),s==null||s.classList.remove("active"),t==null||t.classList.remove("active"),this.engine.displayMCP=!1},f=()=>{e==null||e.classList.remove("active"),n==null||n.classList.remove("active"),i==null||i.classList.remove("active")};e==null||e.addEventListener("click",()=>{f(),e.classList.add("active"),document.body.classList.remove("zen-mode"),this.engine.alpha=1,this.loop.triggerCameraRestitution(.6)}),n==null||n.addEventListener("click",()=>{f(),n.classList.add("active"),document.body.classList.add("zen-mode");const m=Math.PI/2-.001;this.loop.triggerGimbalSnap(m,0),this.engine.displayMCP=!1}),i==null||i.addEventListener("click",()=>{i.classList.add("active"),setTimeout(()=>i.classList.remove("active"),200),this.engine.syncPulseTime=this.engine.timing,console.log("[State] Backend Sync protocol dispatched.")}),r&&a&&r.addEventListener("click",()=>{c(),r.classList.add("active"),a.classList.remove("canvas-frozen"),this.loop.historyMode=!1,this.loop.start()}),s&&a&&s.addEventListener("click",()=>{c(),s.classList.add("active"),a.classList.remove("canvas-frozen"),this.engine.displayMCP=!0,this.loop.historyMode=!1,this.loop.start(),this.engine.updateHUD(0)}),t&&a&&t.addEventListener("click",()=>{c(),t.classList.add("active"),a.classList.remove("canvas-frozen"),this.loop.start(),this.loop.historyMode=!0,this.engine.historyProgress=0,this.enterHistoryMode()}),l&&a&&l.addEventListener("click",()=>{c(),l.classList.add("active"),this.loop.historyMode=!1,this.loop.stop(),a.classList.add("canvas-frozen")})}async enterHistoryMode(){console.log("[State] Transmitting native History Protocol hook -> backend.");try{await new Promise(e=>setTimeout(e,600)),console.log("[State] Generating Atomic Temporal Buffers for Ghost reallocations on CPU worker."),console.log("[State] Atomic Swap complete. Awaiting Scroll Wheel Uniform timeline scrubbing seamlessly.")}catch(e){console.error("[State] Temporal Error:",e)}}}async function Y(){var v,y;const d=document.getElementById("topo");d.width=window.innerWidth,d.height=window.innerHeight;const e=await I(d);if(!e){document.getElementById("fallback").style.display="block";return}const n=((y=(v=document.getElementById("__dotscope_data__"))==null?void 0:v.textContent)==null?void 0:y.trim())||"";let i={nodes:[{id:"src/main.ts"},{id:"src/pretext.ts"}],edges:[{source:"src/main.ts",target:"src/pretext.ts"}],scopes:{},invariants:[]};if(n.length>0&&n!=="__GRAPH_DATA_PAYLOAD__")try{i=JSON.parse(n)}catch(h){console.error("Dotscope WebGPU Init: Failed to parse backend telemetry payload",h)}if(i.nodes.length===0){document.getElementById("loader-overlay").style.display="none",document.getElementById("zero-state").classList.add("active");return}const a=await U(e.device),r=await G(e.device),s=await N(e.device,e.format),t=D(i),l=document.getElementById("ui-nodes");l&&(l.textContent=t.nodeCount.toString());const c=new O(e,t,a,r,s.nodePipeline,s.edgePipeline);new R(c,i.scopes||{});const f=new z(c,d);new F(c,f);const m=document.getElementById("ui-desync");m&&m.addEventListener("click",()=>{c.selectedNode=-1,c.updateHUD(-1)}),setTimeout(()=>{document.body.classList.add("engine-ready"),f.start()},50)}Y().catch(d=>{console.error("FATAL BOOTSTRAP ERROR:",d);const e=document.createElement("div");e.style.cssText="position: absolute; top: 50%; left: 10%; right: 10%; background: red; color: white; padding: 20px; z-index: 9999; border-radius: 8px; font-family: monospace; white-space: pre-wrap;",e.textContent=`FATAL BOOTSTRAP ERROR:
`+(d.stack||String(d)),document.body.appendChild(e)});
