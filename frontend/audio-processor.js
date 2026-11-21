/**
 * VaaniKhata – Web Audio AudioWorkletProcessor
 * =============================================
 * Downsamples microphone input from native sample rate to 16,000 Hz mono PCM,
 * converts Float32 to 16-bit signed little-endian integers, and emits
 * exact 1,024-byte (512-sample, 32ms) frames for Gnani Prisma v3.0 STT.
 */

class PCMAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.buffer = new Int16Array(512); // 512 samples = 1,024 bytes
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0]) {
      return true;
    }

    const inputChannel = input[0]; // Float32Array at context.sampleRate
    const inputSampleRate = currentFrame ? sampleRate : 48000;
    const ratio = inputSampleRate / this.targetSampleRate;

    for (let i = 0; i < inputChannel.length; i += ratio) {
      const idx = Math.floor(i);
      let sample = inputChannel[idx];

      // Clamp between -1.0 and 1.0
      sample = Math.max(-1.0, Math.min(1.0, sample));

      // Convert float [-1.0, 1.0] to signed 16-bit PCM [-32768, 32767]
      const int16 = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      this.buffer[this.bufferIndex++] = Math.round(int16);

      // When we hit 512 samples (1,024 bytes), post to main thread
      if (this.bufferIndex >= 512) {
        const pcmBytes = new Int16Array(this.buffer);
        this.port.postMessage(pcmBytes.buffer, [pcmBytes.buffer]);
        this.bufferIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor("pcm-audio-processor", PCMAudioProcessor);
