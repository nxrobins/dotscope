struct Node {
    pos_dim: vec4<f32>,       // [0]: x, [1]: y, [2]: width, [3]: height
    velocity_mass: vec4<f32>  // [0]: vx, [1]: vy, [2]: mass, [3]: thermal_decay (or padding)
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
const SPRING_STIFFNESS: f32 = 0.05;
const SPRING_LENGTH: f32 = 100.0;
const REPULSION_BASE: f32 = 5000.0;
const DAMPING: f32 = 0.9;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let index = global_id.x;
    if (index >= params.node_count) {
        return;
    }

    var node = nodes[index];
    var force = vec2<f32>(0.0, 0.0);

    // ----------------------------------------------------------------------
    // Pass 1: Attraction (NPMI Edge Spring Forces)
    // ----------------------------------------------------------------------
    // O(E) Edge Attraction - Since WebGPU does not have scatter/gather easily,
    // this simplistic kernel iterates all edges. For 15k nodes, spatial hashing 
    // is ideal, but O(E) on GPU is still infinitely faster than CPU. 
    for (var e = 0u; e < params.edge_count; e = e + 1u) {
        let edge = edges[e];
        if (edge.x == index || edge.y == index) {
            let neighbor_idx = select(edge.x, edge.y, edge.x == index);
            let neighbor = nodes[neighbor_idx];
            
            var delta = neighbor.pos_dim.xy - node.pos_dim.xy;
            let dist = max(length(delta), 0.1);
            
            // Edge constraint: Pull nodes together if further than ideal spring length
            let spring = (dist - SPRING_LENGTH) * SPRING_STIFFNESS;
            let dir = normalize(delta);
            force += dir * spring;
        }
    }

    // ----------------------------------------------------------------------
    // Pass 2: AABB Repulsion (The Pretext Shield)
    // ----------------------------------------------------------------------
    // Repel all other nodes using Rectangular Intersection rather than Radii
    for (var j = 0u; j < params.node_count; j = j + 1u) {
        if (index == j) { continue; }
        
        let other = nodes[j];
        var delta = node.pos_dim.xy - other.pos_dim.xy;
        
        let dx_abs = abs(delta.x);
        let dy_abs = abs(delta.y);
        
        let target_dist_x = (node.pos_dim.z + other.pos_dim.z) / 2.0;
        let target_dist_y = (node.pos_dim.w + other.pos_dim.w) / 2.0;
        
        // Anti-stacking jitter
        if (dx_abs < 0.1 && dy_abs < 0.1) {
            delta = vec2<f32>((f32(index) - f32(j)) * 0.1, (f32(index) - f32(j)) * 0.1);
        }

        // AABB Collision Detect
        if (dx_abs < target_dist_x && dy_abs < target_dist_y) {
            // Extreme Repulsion Spike: They are intersecting!
            // Push out based on the penetration depth
            let overlap_x = target_dist_x - dx_abs;
            let overlap_y = target_dist_y - dy_abs;
            
            // Push across the axis of least penetration
            if (overlap_x < overlap_y) {
                force.x += sign(delta.x) * overlap_x * 10.0;
            } else {
                force.y += sign(delta.y) * overlap_y * 10.0;
            }
        } else {
            // Mild Long-range Repulsion (Coulomb force) to space the graph nicely
            let dist_sq = max(dot(delta, delta), 10.0);
            let repel_mag = REPULSION_BASE / dist_sq;
            force += normalize(delta) * repel_mag;
        }
    }

    // Add Central Gravity towards (0,0) to keep graph grouped
    let center_dir = params.gravity_center - node.pos_dim.xy;
    force += center_dir * 0.05;

    // ----------------------------------------------------------------------
    // Pass 3: Integration (Thermal Cooling)
    // ----------------------------------------------------------------------
    // Add applied force to momentum
    node.velocity_mass.x += force.x * params.alpha;
    node.velocity_mass.y += force.y * params.alpha;
    
    // Apply friction to decay kinetic energy
    node.velocity_mass.x *= DAMPING;
    node.velocity_mass.y *= DAMPING;
    
    // Update structural position
    node.pos_dim.x += node.velocity_mass.x;
    node.pos_dim.y += node.velocity_mass.y;

    // Write-back out to memory layout
    nodes[index] = node;
}
