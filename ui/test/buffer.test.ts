import { describe, it, expect, vi } from 'vitest';
import { buildPhysicsBuffers, GraphPayload } from '../src/buffer';

// Mock Pretext so we strictly assert memory arrays in node without instantiating graphic drivers
vi.mock('../src/pretext', () => ({
    generateTextureAtlas: vi.fn((labels: string[]) => {
        const boxes = new Map();
        for (const label of labels) {
            boxes.set(label, { width: 100, height: 20, uMin: 0, vMin: 0, uMax: 1, vMax: 1 });
        }
        return {
            canvas: {} as any,
            boxes
        };
    })
}));

describe('WebGPU Memory Allocation (buffer.ts)', () => {
    it('Allocates strictly 48 bytes per node for std140 Vector layout', () => {
        const payload: GraphPayload = {
            nodes: [{ id: "A" }, { id: "B" }, { id: "C" }],
            edges: [],
            scopes: {},
            invariants: []
        };
        
        const buffers = buildPhysicsBuffers(payload);
        
        // 3 Nodes * 12 Floats (48 bytes) = 36 length array
        expect(buffers.nodeData.length).toBe(36);
        expect(buffers.nodeData.byteLength).toBe(144); // 48 * 3
        
        // Ensure velocity components naturally align on Float indices [4] and [5]
        expect(buffers.nodeData[4]).toBe(0.0); // Node 1 VX
        expect(buffers.nodeData[5]).toBe(0.0); // Node 1 VY
        
        // Node 2 starts at float index 12
        expect(buffers.nodeData[16]).toBe(0.0); // Node 2 VX bounds mapped correctly
    });
    
    it('Structurally flattens topology pointers natively', () => {
        const payload: GraphPayload = {
            nodes: [{ id: "A" }, { id: "B" }],
            edges: [{ source: "A", target: "B" }],
            scopes: {},
            invariants: []
        };
        
        const buffers = buildPhysicsBuffers(payload);
        expect(buffers.edgeData.length).toBe(2); 
    });
});
