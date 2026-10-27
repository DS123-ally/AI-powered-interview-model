class LiveWhisperChunks extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const seconds = options.processorOptions?.chunkSeconds || 3;
        this.targetFrames = Math.round(sampleRate * seconds);
        this.parts = [];
        this.frameCount = 0;
        this.port.onmessage = event => {
            if (event.data?.type === 'flush') {
                if (this.frameCount >= sampleRate) this.emitChunk();
                this.port.postMessage({ type: 'flushed' });
            }
        };
    }

    emitChunk() {
        const chunk = new Float32Array(this.frameCount);
        let offset = 0;
        for (const part of this.parts) {
            chunk.set(part, offset);
            offset += part.length;
        }
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this.parts = [];
        this.frameCount = 0;
    }

    process(inputs) {
        const samples = inputs[0]?.[0];
        if (!samples || !samples.length) return true;

        this.parts.push(new Float32Array(samples));
        this.frameCount += samples.length;
        if (this.frameCount >= this.targetFrames) this.emitChunk();
        return true;
    }
}

registerProcessor('live-whisper-chunks', LiveWhisperChunks);
