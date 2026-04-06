export async function createComputePipeline(device: GPUDevice): Promise<GPUComputePipeline> {
    const response = await fetch('/src/shader.wgsl');
    const code = await response.text();
    const module = device.createShaderModule({ code });
    return device.createComputePipeline({
        layout: 'auto',
        compute: { module, entryPoint: 'main' }
    });
}

export interface RenderPipelines {
    nodePipeline: GPURenderPipeline;
    edgePipeline: GPURenderPipeline;
}

export async function createRenderPipelines(device: GPUDevice, format: GPUTextureFormat): Promise<RenderPipelines> {
    const response = await fetch('/src/render.wgsl');
    const code = await response.text();
    const module = device.createShaderModule({ code });

    const blend: GPUBlendState = {
        color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha', operation: 'add' },
        alpha: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' }
    };

    const nodePipeline = device.createRenderPipeline({
        layout: 'auto',
        vertex: { module, entryPoint: 'vs_main' },
        fragment: {
            module,
            entryPoint: 'fs_main',
            targets: [{ format, blend }]
        },
        primitive: { topology: 'triangle-list' }
    });

    const edgePipeline = device.createRenderPipeline({
        layout: 'auto',
        vertex: { module, entryPoint: 'vs_edge_main' },
        fragment: {
            module,
            entryPoint: 'fs_edge_main',
            targets: [{ format, blend }]
        },
        primitive: { topology: 'line-list' }
    });

    return { nodePipeline, edgePipeline };
}
