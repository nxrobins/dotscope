import { WebGPUContext } from '../webgpu/device';
import { WGSLBuffers } from '../buffer';

export class TopographyEngine {
    private context: WebGPUContext;
    public buffers: WGSLBuffers;
    
    public alpha: number = 1.0;
    
    private computePipeline: GPUComputePipeline;
    private nodePipeline: GPURenderPipeline;
    private edgePipeline: GPURenderPipeline;
    
    private nodeBuffer: GPUBuffer;
    private edgeBuffer: GPUBuffer;
    private uniformBuffer: GPUBuffer;
    private cameraBuffer: GPUBuffer;
    
    private atlasTexture: GPUTexture;
    
    private computeBindGroup: GPUBindGroup;
    public renderBindGroup: GPUBindGroup;

    constructor(
        ctx: WebGPUContext,
        bufs: WGSLBuffers,
        compPipe: GPUComputePipeline,
        nodePipe: GPURenderPipeline,
        edgePipe: GPURenderPipeline
    ) {
        this.context = ctx;
        this.buffers = bufs;
        this.computePipeline = compPipe;
        this.nodePipeline = nodePipe;
        this.edgePipeline = edgePipe;
        
        this.nodeBuffer = ctx.device.createBuffer({
            size: bufs.nodeData.byteLength,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
            mappedAtCreation: true,
        });
        new Float32Array(this.nodeBuffer.getMappedRange()).set(bufs.nodeData);
        this.nodeBuffer.unmap();

        this.edgeBuffer = ctx.device.createBuffer({
            size: bufs.edgeData.byteLength,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
            mappedAtCreation: true,
        });
        new Uint32Array(this.edgeBuffer.getMappedRange()).set(bufs.edgeData);
        this.edgeBuffer.unmap();
        
        this.uniformBuffer = ctx.device.createBuffer({
            size: 16,
            usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
        });

        this.computeBindGroup = ctx.device.createBindGroup({
            layout: this.computePipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: this.nodeBuffer } },
                { binding: 1, resource: { buffer: this.edgeBuffer } },
                { binding: 2, resource: { buffer: this.uniformBuffer } }
            ]
        });

        this.cameraBuffer = ctx.device.createBuffer({
            size: 32,
            usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
        });
        
        this.atlasTexture = ctx.device.createTexture({
            size: [bufs.atlasCanvas.width, bufs.atlasCanvas.height, 1],
            format: 'rgba8unorm',
            usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT
        });
        
        ctx.device.queue.copyExternalImageToTexture(
            { source: bufs.atlasCanvas },
            { texture: this.atlasTexture },
            [bufs.atlasCanvas.width, bufs.atlasCanvas.height]
        );
        
        const atlasSampler = ctx.device.createSampler({
            magFilter: 'linear',
            minFilter: 'linear',
        });

        this.renderBindGroup = ctx.device.createBindGroup({
            layout: this.nodePipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: this.nodeBuffer } },
                { binding: 1, resource: { buffer: this.cameraBuffer } },
                { binding: 2, resource: { buffer: this.edgeBuffer } },
                { binding: 3, resource: this.atlasTexture.createView() },
                { binding: 4, resource: atlasSampler }
            ]
        });
    }
    
    public update(canvasWidth: number, canvasHeight: number) {
        const camData = new Float32Array([
            canvasWidth / 2, canvasHeight / 2, 
            1.0, 1.0,                            
            canvasWidth, canvasHeight          
        ]);
        this.context.device.queue.writeBuffer(this.cameraBuffer, 0, camData);

        const commandEncoder = this.context.device.createCommandEncoder();

        if (this.alpha > 0.001) {
            const uniformData = new Float32Array([
                this.buffers.nodeCount, 
                this.buffers.edgeCount, 
                this.alpha, 
                0.0 
            ]);
            this.context.device.queue.writeBuffer(this.uniformBuffer, 0, uniformData);

            const passEncoder = commandEncoder.beginComputePass();
            passEncoder.setPipeline(this.computePipeline);
            passEncoder.setBindGroup(0, this.computeBindGroup);
            passEncoder.dispatchWorkgroups(Math.ceil(this.buffers.nodeCount / 64));
            passEncoder.end();
            
            this.alpha *= 0.99;
        }

        const renderPassDescriptor: GPURenderPassDescriptor = {
            colorAttachments: [{
                view: this.context.context.getCurrentTexture().createView(),
                clearValue: { r: 0.04, g: 0.04, b: 0.04, a: 1.0 }, 
                loadOp: 'clear',
                storeOp: 'store',
            }]
        };

        const renderPassEncoder = commandEncoder.beginRenderPass(renderPassDescriptor);
        
        renderPassEncoder.setPipeline(this.edgePipeline);
        renderPassEncoder.setBindGroup(0, this.renderBindGroup);
        renderPassEncoder.draw(this.buffers.edgeCount * 2, 1, 0, 0);
        
        renderPassEncoder.setPipeline(this.nodePipeline);
        renderPassEncoder.setBindGroup(0, this.renderBindGroup);
        renderPassEncoder.draw(6, this.buffers.nodeCount, 0, 0);
        
        renderPassEncoder.end();
        this.context.device.queue.submit([commandEncoder.finish()]);
    }
    
    public destroy() {
        console.log("[Engine] Tearing down GPU contexts natively...");
        this.nodeBuffer.destroy();
        this.edgeBuffer.destroy();
        this.uniformBuffer.destroy();
        this.cameraBuffer.destroy();
        this.atlasTexture.destroy();
        this.context.device.destroy();
    }
}
