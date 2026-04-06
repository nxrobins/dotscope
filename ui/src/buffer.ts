/**
 * WebGPU Buffer Marshalling
 * 
 * Maps raw unstructured DOTSCOPE graph JSON into strict `std140` memory-aligned
 * TypedArrays guaranteeing maximum bandwidth to the WGSL compute shader.
 */

import { generateTextureAtlas } from "./pretext";

export interface GraphPayload {
    nodes: { id: string }[];
    edges: { source: string, target: string }[];
    scopes: any;
    invariants: any[];
}

export interface WGSLBuffers {
    nodeData: Float32Array;
    edgeData: Uint32Array;
    nodeCount: number;
    edgeCount: number;
    atlasCanvas: OffscreenCanvas;
}

export function buildPhysicsBuffers(payload: GraphPayload): WGSLBuffers {
    const numNodes = payload.nodes.length;
    const numEdges = payload.edges.length;
    
    // ----------------------------------------------------------------------
    // 1. Node Buffer (vec4<f32> * 3 per Node = 48 bytes)
    // Layout: 
    //   pos_dim:       [ x, y, width, height ]
    //   velocity_mass: [ vx, vy, mass, padding ]
    //   uv_bounds:     [ uMin, vMin, uMax, vMax ]
    // ----------------------------------------------------------------------
    const nodeData = new Float32Array(numNodes * 12);
    
    // Create a fast lookup map for edges
    const idToIndex = new Map<string, number>();
    
    // Execute massive 2D Grid packing 
    const atlas = generateTextureAtlas(payload.nodes.map(n => n.id));

    for (let i = 0; i < numNodes; i++) {
        const node = payload.nodes[i];
        idToIndex.set(node.id, i);
        
        // Fetch strictly-mapped OffscreenCanvas bounds
        const box = atlas.boxes.get(node.id)!;
        
        const offset = i * 12;
        
        // pos_dim: vec4<f32>
        nodeData[offset + 0] = (Math.random() - 0.5) * 1000;  // X
        nodeData[offset + 1] = (Math.random() - 0.5) * 1000;  // Y
        nodeData[offset + 2] = box.width;                     // Pretext Width
        nodeData[offset + 3] = box.height;                    // Pretext Height
        
        // velocity_mass: vec4<f32>
        nodeData[offset + 4] = 0.0;                           // VX 
        nodeData[offset + 5] = 0.0;                           // VY
        nodeData[offset + 6] = box.width * box.height;        // Mass (Area bounds)
        nodeData[offset + 7] = 0.0;                           // Pad/Thermal state
        
        // uv_bounds: vec4<f32>
        nodeData[offset + 8]  = box.uMin;
        nodeData[offset + 9]  = box.vMin;
        nodeData[offset + 10] = box.uMax;
        nodeData[offset + 11] = box.vMax;
    }
    
    // ----------------------------------------------------------------------
    // 2. Edge Buffer (vec2<u32> Alignment)
    // Layout: [ source_index, target_index ] per edge.
    // Maps memory-heavy string IDs into lightweight GPU pointer indices.
    // ----------------------------------------------------------------------
    const edgeData = new Uint32Array(numEdges * 2);
    
    for (let i = 0; i < numEdges; i++) {
        const edge = payload.edges[i];
        const sourceIdx = idToIndex.get(edge.source);
        const targetIdx = idToIndex.get(edge.target);
        
        const offset = i * 2;
        if (sourceIdx !== undefined && targetIdx !== undefined) {
            edgeData[offset + 0] = sourceIdx;
            edgeData[offset + 1] = targetIdx;
        }
    }
    
    return {
        nodeData,
        edgeData,
        nodeCount: numNodes,
        edgeCount: numEdges,
        atlasCanvas: atlas.canvas
    };
}
