/**
 * Pretext Text Engine & Atlas Generator
 * 
 * Bypasses DOM reflows entirely by computing font metrics strictly in-memory.
 * Packs 15,000+ string labels into a dense, row-wrapped 2D texture grid and 
 * generates strict normalized UV bounds for WGSL rendering.
 */

const FONT_FAMILY = "'Inter', sans-serif";
const FONT_SIZE = 12; // px

export interface BoundingBox {
    width: number;
    height: number;
    uMin: number;
    vMin: number;
    uMax: number;
    vMax: number;
}

export interface AtlasResult {
    canvas: OffscreenCanvas;
    boxes: Map<string, BoundingBox>;
}

export function generateTextureAtlas(labels: string[]): AtlasResult {
    const PADDING_X = 16;
    const PADDING_Y = 8;
    const ROW_GAP = 2;
    const MAX_WIDTH = 4096;

    // Use a temporary canvas to pre-calculate the required height
    const tempCanvas = new OffscreenCanvas(1, 1);
    const tempCtx = tempCanvas.getContext("2d") as OffscreenCanvasRenderingContext2D;
    tempCtx.font = `600 ${FONT_SIZE}px ${FONT_FAMILY}`;
    tempCtx.textBaseline = "top";

    const labelMetrics = labels.map(label => {
        const metrics = tempCtx.measureText(label);
        const w = Math.ceil(Math.max(metrics.width, metrics.actualBoundingBoxRight + Math.abs(metrics.actualBoundingBoxLeft))) + PADDING_X;
        const h = Math.ceil(metrics.actualBoundingBoxAscent + metrics.actualBoundingBoxDescent) + PADDING_Y;
        return { label, w, h };
    });

    // Grid Packer Algorithm
    let currentX = 0;
    let currentY = 0;
    let maxRowHeight = 0;

    const packedLayouts: { label: string, x: number, y: number, w: number, h: number }[] = [];

    for (const metric of labelMetrics) {
        if (currentX + metric.w > MAX_WIDTH) {
            currentX = 0;
            currentY += maxRowHeight + ROW_GAP;
            maxRowHeight = 0;
        }
        
        packedLayouts.push({ label: metric.label, x: currentX, y: currentY, w: metric.w, h: metric.h });
        
        currentX += metric.w;
        if (metric.h > maxRowHeight) maxRowHeight = metric.h;
    }

    const finalHeight = currentY + maxRowHeight;

    if (finalHeight > 8192) {
        console.warn(`[Pretext Shield] Hardware Exception: Canvas height (${finalHeight}px) exceeds generic WebGPU 8192px limit. Node truncation may occur.`);
    }

    // Allocate the actual physical Canvas Atlas
    const atlas = new OffscreenCanvas(MAX_WIDTH, Math.max(finalHeight, 1));
    const ctx = atlas.getContext("2d") as OffscreenCanvasRenderingContext2D;
    
    // Transparent background strictly ensures #000000 Alpha is clear
    ctx.clearRect(0, 0, MAX_WIDTH, finalHeight);
    ctx.fillStyle = "rgba(255, 255, 255, 1.0)"; // Pure crisp white for text overlay
    ctx.font = tempCtx.font;
    ctx.textBaseline = "top";

    const boxes = new Map<string, BoundingBox>();

    // Draw the Ink and Map the UV Matrices
    for (const layout of packedLayouts) {
        ctx.fillText(layout.label, layout.x + PADDING_X / 2, layout.y + PADDING_Y / 2);
        
        boxes.set(layout.label, {
            width: layout.w,
            height: layout.h,
            uMin: layout.x / MAX_WIDTH,
            vMin: layout.y / atlas.height,
            uMax: (layout.x + layout.w) / MAX_WIDTH,
            vMax: (layout.y + layout.h) / atlas.height
        });
    }

    return { canvas: atlas, boxes };
}
