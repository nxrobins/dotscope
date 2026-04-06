import { buildPhysicsBuffers, GraphPayload } from './buffer';
import { requestWebGPUContext } from './webgpu/device';
import { createComputePipeline, createRenderPipelines } from './webgpu/pipelines';
import { TopographyEngine } from './core/engine';
import { SimulationLoop } from './core/loop';

async function bootstrap() {
    const canvas = document.getElementById('topo') as HTMLCanvasElement;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const ctx = await requestWebGPUContext(canvas);
    if (!ctx) {
        document.getElementById('fallback')!.style.display = 'block';
        return;
    }

    // Hydrate from injected python JSON payload
    // @ts-ignore
    const rawPayload = window.__DOTSCOPE_DATA__;
    
    // Mock string payload prevents local dev server crashing if not injected
    const payloadBuffer: GraphPayload = typeof rawPayload === 'string' && rawPayload === '__GRAPH_DATA_PAYLOAD__' 
        ? { nodes: [{id: "src/main.ts"}, {id: "src/pretext.ts"}], edges: [{source: "src/main.ts", target: "src/pretext.ts"}], scopes: {}, invariants: [] }
        : rawPayload;

    const computePipeline = await createComputePipeline(ctx.device);
    const renderPipelines = await createRenderPipelines(ctx.device, ctx.format);
    
    const buffers = buildPhysicsBuffers(payloadBuffer);

    const engine = new TopographyEngine(
        ctx, 
        buffers, 
        computePipeline, 
        renderPipelines.nodePipeline, 
        renderPipelines.edgePipeline
    );

    const loop = new SimulationLoop(engine, canvas);
    
    // Architecturally sound Hot Module Replacement (HMR) lifecycle cleanup natively averting out of memory exceptions
    // @ts-ignore
    if (import.meta.hot) {
        // @ts-ignore
        import.meta.hot.dispose(() => {
            loop.stop();
        });
    }

    loop.start();
}

bootstrap();
