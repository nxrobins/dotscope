export interface WebGPUContext {
    adapter: GPUAdapter;
    device: GPUDevice;
    context: GPUCanvasContext;
    format: GPUTextureFormat;
}

export async function requestWebGPUContext(canvas: HTMLCanvasElement): Promise<WebGPUContext | null> {
    if (!navigator.gpu) {
        return null;
    }
    
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
        return null;
    }

    const device = await adapter.requestDevice();
    const context = canvas.getContext('webgpu') as GPUCanvasContext | null;
    if (!context) {
        return null;
    }

    const format = navigator.gpu.getPreferredCanvasFormat();
    
    // Explicit format and alpha mapping mapped directly
    context.configure({
        device,
        format,
        alphaMode: 'premultiplied',
    });

    return { adapter, device, context, format };
}
