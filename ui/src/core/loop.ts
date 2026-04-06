import { TopographyEngine } from './engine';

export class SimulationLoop {
    private engine: TopographyEngine;
    private canvas: HTMLCanvasElement;
    private frameId: number = 0;
    private overlay: HTMLDivElement;
    
    private lastTime: number = performance.now();
    private frames: number = 0;
    
    constructor(engine: TopographyEngine, canvas: HTMLCanvasElement) {
        this.engine = engine;
        this.canvas = canvas;
        
        // Spawn Absolute Debug Overlay dynamically to avoid DOM reflow hits
        this.overlay = document.createElement('div');
        this.overlay.style.position = 'absolute';
        this.overlay.style.top = '16px';
        this.overlay.style.left = '16px';
        this.overlay.style.color = '#00FF00';
        this.overlay.style.fontFamily = 'monospace';
        this.overlay.style.fontSize = '12px';
        this.overlay.style.pointerEvents = 'none';
        this.overlay.style.zIndex = '9999';
        this.overlay.style.whiteSpace = 'pre';
        this.overlay.style.background = 'rgba(0,0,0,0.5)';
        this.overlay.style.padding = '8px';
        this.overlay.style.borderRadius = '4px';
        document.body.appendChild(this.overlay);
    }
    
    public start() {
        const tick = () => {
            // Resize handler binding
            if (this.canvas.width !== window.innerWidth || this.canvas.height !== window.innerHeight) {
                this.canvas.width = window.innerWidth;
                this.canvas.height = window.innerHeight;
            }
            
            // Advance GPU state natively
            this.engine.update(this.canvas.width, this.canvas.height);
            
            // Fast metrics dispatch
            this.frames++;
            const now = performance.now();
            if (now - this.lastTime >= 1000) {
                const fps = Math.round((this.frames * 1000) / (now - this.lastTime));
                this.overlay.innerText = `[Dotscope Engine]\nFPS:    ${fps}\nAlpha:  ${this.engine.alpha.toFixed(4)}\nNodes:  ${this.engine.buffers.nodeCount}`;
                this.frames = 0;
                this.lastTime = now;
            }
            
            this.frameId = requestAnimationFrame(tick);
        };
        tick();
    }
    
    public stop() {
        cancelAnimationFrame(this.frameId);
        this.overlay.remove();
        this.engine.destroy();
    }
}
