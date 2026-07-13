/**
 * 前端视频压缩模块 — Canvas + MediaRecorder 方案
 * 将参考视频转码到满足下游像素下限的轻量尺寸，适用于 15 秒内短视频
 * 兼容 iOS Safari / Chrome / Firefox，无需额外依赖
 */

const VIDEO_COMPRESSOR = {
    TARGET_SHORT_EDGE: 480,
    MIN_REFERENCE_VIDEO_PIXELS: 409600,
    FPS: 24,
    VIDEO_BITRATE: 1_500_000,
    COMPRESSION_THRESHOLD_MB: 10,
    MAX_DURATION_SECONDS: 15,

    getSupportedMimeType() {
        const candidates = [
            'video/webm;codecs=vp9,opus',
            'video/webm;codecs=vp8,opus',
            'video/webm;codecs=vp8',
            'video/webm',
            'video/mp4',
        ];
        for (const mime of candidates) {
            if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mime)) {
                return mime;
            }
        }
        return 'video/webm';
    },

    async getVideoResolution(file) {
        return new Promise((resolve, reject) => {
            const video = document.createElement('video');
            video.preload = 'metadata';
            video.muted = true;
            video.playsInline = true;
            video.onloadedmetadata = () => {
                const info = { width: video.videoWidth, height: video.videoHeight, duration: video.duration };
                URL.revokeObjectURL(video.src);
                resolve(info);
            };
            video.onerror = () => {
                URL.revokeObjectURL(video.src);
                reject(new Error('无法读取视频元数据'));
            };
            video.src = URL.createObjectURL(file);
        });
    },

    needsCompression(file, videoInfo, maxDuration) {
        const sizeMB = file.size / (1024 * 1024);
        const pixelCount = (videoInfo.width || 0) * (videoInfo.height || 0);
        if (sizeMB > this.COMPRESSION_THRESHOLD_MB) return true;
        if (Math.min(videoInfo.width, videoInfo.height) > this.TARGET_SHORT_EDGE) return true;
        if (pixelCount > 0 && pixelCount < this.MIN_REFERENCE_VIDEO_PIXELS) return true;
        if (maxDuration && videoInfo.duration > maxDuration) return true;
        return false;
    },

    roundToEven(value) {
        return Math.max(2, Math.round(value / 2) * 2);
    },

    ceilToEven(value) {
        return Math.max(2, Math.ceil(value / 2) * 2);
    },

    calculateOutputDimensions(videoInfo) {
        const sourceW = Number(videoInfo?.width) || 0;
        const sourceH = Number(videoInfo?.height) || 0;
        if (sourceW <= 0 || sourceH <= 0) {
            return { width: 0, height: 0 };
        }

        const shortestEdge = Math.min(sourceW, sourceH);
        const sourcePixels = sourceW * sourceH;
        let scale = Math.min(1, this.TARGET_SHORT_EDGE / shortestEdge);

        const scaledPixels = sourcePixels * scale * scale;
        if (scaledPixels < this.MIN_REFERENCE_VIDEO_PIXELS) {
            scale = Math.sqrt(this.MIN_REFERENCE_VIDEO_PIXELS / sourcePixels);
        }

        const toEven = scale > 1 ? this.ceilToEven.bind(this) : this.roundToEven.bind(this);
        let outW = toEven(sourceW * scale);
        let outH = toEven(sourceH * scale);

        while (outW * outH < this.MIN_REFERENCE_VIDEO_PIXELS) {
            if (outW >= outH) {
                outW += 2;
            } else {
                outH += 2;
            }
        }

        return { width: outW, height: outH };
    },

    async compressVideoForReference(file, onProgress, maxDuration) {
        const effectiveMaxDuration = maxDuration || this.MAX_DURATION_SECONDS;
        const videoInfo = await this.getVideoResolution(file);

        if (!this.needsCompression(file, videoInfo, effectiveMaxDuration)) {
            onProgress?.(100);
            return { blob: file, compressed: false, info: videoInfo };
        }

        const outputDimensions = this.calculateOutputDimensions(videoInfo);
        const outW = outputDimensions.width;
        const outH = outputDimensions.height;

        return new Promise((resolve, reject) => {
            const video = document.createElement('video');
            video.src = URL.createObjectURL(file);
            video.muted = true;
            video.playsInline = true;
            video.preload = 'auto';

            let recorder = null;
            let animationId = null;
            const chunks = [];
            let stopped = false;

            const cleanup = () => {
                if (animationId) cancelAnimationFrame(animationId);
                URL.revokeObjectURL(video.src);
            };

            const doStop = () => {
                if (stopped) return;
                stopped = true;
                if (recorder && recorder.state !== 'inactive') {
                    try { recorder.stop(); } catch (e) { /* ignore */ }
                }
            };

            video.onloadedmetadata = () => {
                video.play().catch(err => {
                    cleanup();
                    reject(new Error('视频播放失败: ' + err.message));
                });
            };

            video.onplay = () => {
                const duration = videoInfo.duration || video.duration;
                const effectiveDuration = Math.min(duration, effectiveMaxDuration);
                const truncated = duration > effectiveMaxDuration;

                if (truncated) {
                    console.log(`[VideoCompressor] 视频时长 ${duration.toFixed(1)}s 超过限制 ${effectiveMaxDuration}s，将截断`);
                }

                const canvas = document.createElement('canvas');
                canvas.width = outW;
                canvas.height = outH;
                const ctx = canvas.getContext('2d');

                const videoTrack = canvas.captureStream(this.FPS).getVideoTracks()[0];
                const combinedStream = new MediaStream([videoTrack]);

                // 用 video.captureStream() 获取音频轨道
                // 它读取的是解码后的原始音频数据，不受 muted/volume 影响
                try {
                    const sourceStream = video.captureStream();
                    const audioTracks = sourceStream.getAudioTracks();
                    if (audioTracks.length > 0) {
                        audioTracks.forEach(track => combinedStream.addTrack(track));
                        console.log('[VideoCompressor] 音频轨道已添加');
                    } else {
                        console.warn('[VideoCompressor] 视频无音频轨道');
                    }
                } catch (e) {
                    console.warn('[VideoCompressor] 音频捕获失败（视频将无声音）:', e.message);
                }

                const mimeType = this.getSupportedMimeType();
                const options = { mimeType };
                if (mimeType.includes('webm')) {
                    options.videoBitsPerSecond = this.VIDEO_BITRATE;
                }

                try {
                    recorder = new MediaRecorder(combinedStream, options);
                } catch (e) {
                    cleanup();
                    reject(new Error('MediaRecorder 初始化失败: ' + e.message));
                    return;
                }

                recorder.ondataavailable = (e) => {
                    if (e.data && e.data.size > 0) chunks.push(e.data);
                };

                recorder.onstop = () => {
                    cleanup();
                    const outputType = mimeType.includes('mp4') ? 'video/mp4' : 'video/webm';
                    const blob = new Blob(chunks, { type: outputType });
                    onProgress?.(100);
                    resolve({
                        blob,
                        compressed: true,
                        truncated: duration > effectiveDuration,
                        info: { ...videoInfo, outputWidth: outW, outputHeight: outH, outputDuration: effectiveDuration, outputType }
                    });
                };

                recorder.onerror = (e) => {
                    cleanup();
                    reject(new Error('录制出错: ' + (e.error?.message || 'unknown')));
                };

                recorder.start(1000);

                const drawFrame = () => {
                    if (stopped) return;
                    if (video.ended || video.paused || video.currentTime >= effectiveDuration) {
                        doStop();
                        return;
                    }
                    ctx.drawImage(video, 0, 0, outW, outH);

                    if (effectiveDuration > 0) {
                        const progress = Math.min(99, Math.round((video.currentTime / effectiveDuration) * 100));
                        onProgress?.(progress);
                    }

                    animationId = requestAnimationFrame(drawFrame);
                };
                drawFrame();
            };

            video.onended = () => doStop();
            video.onerror = () => {
                cleanup();
                reject(new Error('视频加载失败'));
            };

            // 安全超时：有效时长 * 2 + 10 秒
            const safeTimeoutDuration = Math.min(videoInfo.duration || 15, effectiveMaxDuration);
            const timeout = safeTimeoutDuration * 2000 + 10000;
            setTimeout(() => {
                if (!stopped) {
                    doStop();
                }
            }, timeout);
        });
    },

    async compressVideoTo480p(file, onProgress, maxDuration) {
        return this.compressVideoForReference(file, onProgress, maxDuration);
    }
};
