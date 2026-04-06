import { describe, it, expect, vi } from 'vitest';

// We must mock the global OffscreenCanvas for Node testing matrix execution
class MockContext {
    font = "";
    textBaseline = "";
    fillStyle = "";
    measureText(text: string) {
        return {
            width: text.length * 5,
            actualBoundingBoxRight: text.length * 5,
            actualBoundingBoxLeft: 0,
            actualBoundingBoxAscent: 10,
            actualBoundingBoxDescent: 2
        };
    }
    clearRect() {}
    fillText() {}
}

// Inject Headless Canvas mapping dynamically
global.OffscreenCanvas = class MockOffscreenCanvas {
    width: number;
    height: number;
    constructor(width: number, height: number) {
        this.width = width;
        this.height = height;
    }
    getContext() {
        return new MockContext();
    }
} as any;

import { generateTextureAtlas } from '../src/pretext';


describe('Pretext 2D Grid Packer (pretext.ts)', () => {
    it('Wraps correctly across columns exceeding 4096 bounds without halting', () => {
        const labels = Array.from({ length: 5000 }, (_, i) => `very_long_file_name_that_forces_wrap_${i}.py`);
        
        const result = generateTextureAtlas(labels);
        
        // The atlas width should strictly obey 4096 hard-stop
        expect(result.canvas.width).toBe(4096);
        
        // Since it wrapped hundreds of times, the height should increment safely natively
        expect(result.canvas.height).toBeGreaterThan(100);
        expect(result.boxes.size).toBe(5000);
        
        // Check U/V bindings exist and are normalized floats suitable for Fragment sampling
        const box = result.boxes.get("very_long_file_name_that_forces_wrap_0.py");
        expect(box?.uMax).toBeLessThanOrEqual(1.0);
        expect(box?.vMax).toBeLessThanOrEqual(1.0);
    });
    
    it('Throws 8192px hardware exception trace when exceeding WebGPU max texture bounds', () => {
        const consoleSpy = vi.spyOn(console, 'warn');
        // generate 100,000 files to burst the grid height computations
        const labels = Array.from({ length: 80000 }, (_, i) => `file_${i}.ts`);
        generateTextureAtlas(labels);
        
        expect(consoleSpy).toHaveBeenCalledWith(expect.stringContaining('Hardware Exception'));
    });
});
