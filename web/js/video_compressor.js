/**
 * 前端视频压缩模块 — Canvas + MediaRecorder 方案
 * 将参考视频转码到满足下游像素下限的轻量尺寸，适用于 15 秒内短视频
 * 兼容 iOS Safari / Chrome / Firefox，无需额外依赖
 */

const VIDEO_COMPRESSOR = {
    TARGET_SHORT_EDGE: 480,
    MIN_REFERENCE_VIDEO_PIXELS: 409600,
    // 目标帧率：与后端 MediaConstants.VIDEO_REFERENCE_MAX_FPS 对齐。
    // 注意：仅靠 canvas.captureStream(FPS) 无法可靠限频——在 120Hz/144Hz 高刷屏上，
    // 浏览器会按屏幕刷新率采样，实际捕获帧率可能远超 FPS（如 120fps），导致下游
    // 视频模型因帧率超限报错。真正的限频由 drawFrame 内的时间戳节流保证。
    FPS: 30,
    VIDEO_BITRATE: 1_500_000,
    COMPRESSION_THRESHOLD_MB: 10,
    MAX_DURATION_SECONDS: 15,
    // VP8 降级重试候选：首选编码（通常 VP9）0 字节时换 VP8 变体再试一次
    VP8_RETRY_MIMES: ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp8', 'video/webm'],

    getSupportedMimeType() {
        const candidates = [
            'video/webm;codecs=vp9,opus',
            'video/webm;codecs=vp8,opus',
            'video/webm;codecs=vp8',
            'video/webm',
            'video/mp4',
        ];
        // 编码器诊断：360极速浏览器等 chromium 套壳可能 isTypeSupported 返回 true
        // 但实际编码器被阉割（录制产出 0 字节），逐项打印支持表便于定位
        if (typeof MediaRecorder === 'undefined') {
            console.warn('[VideoCompressor] MediaRecorder 不可用，回退 video/webm');
            return 'video/webm';
        }
        const supportTable = candidates
            .map(mime => `${mime}=${MediaRecorder.isTypeSupported(mime)}`)
            .join(', ');
        for (const mime of candidates) {
            if (MediaRecorder.isTypeSupported(mime)) {
                console.log(`[VideoCompressor] MediaRecorder 编码支持: ${supportTable}, 选用 ${mime}`);
                return mime;
            }
        }
        console.warn(`[VideoCompressor] 所有候选编码均不受支持(${supportTable})，回退 video/webm`);
        return 'video/webm';
    },

    // 纯函数：首选编码 0 字节后可降级重试的 VP8 变体。首选已是 VP8/webm 系
    // （重试无意义）或无受支持变体（如 Safari 不支持 webm 编码）时返回 null。
    vp8RetryMime(preferredMime) {
        if (typeof MediaRecorder === 'undefined') return null;
        if (this.VP8_RETRY_MIMES.includes(preferredMime)) return null;
        return this.VP8_RETRY_MIMES.find(mime => MediaRecorder.isTypeSupported(mime)) || null;
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
        console.log(
            `[VideoCompressor] 压缩开始: name=${file.name}, size=${(file.size / 1024 / 1024).toFixed(1)}MB, ` +
            `type=${file.type || 'unknown'}, maxDuration=${effectiveMaxDuration}s`
        );
        const videoInfo = await this.getVideoResolution(file);
        const needsCompress = this.needsCompression(file, videoInfo, effectiveMaxDuration);
        console.log(
            `[VideoCompressor] 源视频信息: ${videoInfo.width}x${videoInfo.height}, ` +
            `duration=${videoInfo.duration}s, needsCompression=${needsCompress}`
        );

        if (!needsCompress) {
            onProgress?.(100);
            return { blob: file, compressed: false, info: videoInfo };
        }

        const outputDimensions = this.calculateOutputDimensions(videoInfo);
        const outW = outputDimensions.width;
        const outH = outputDimensions.height;

        // 首选编码录制；0 字节（编码器声称支持但实际不吐数据，如 360极速浏览器
        // VP9 硬编静默失败）时降级 VP8 重试一次，仍失败则结果本身已是
        // buildRecorderResult 的回退原始文件产物（后端校验兜底）
        const preferredMime = this.getSupportedMimeType();
        let result = await this._recordCompressed(
            file, videoInfo, outW, outH, effectiveMaxDuration, preferredMime, onProgress
        );
        const retryMime = this.vp8RetryMime(preferredMime);
        if (result.fallbackToOriginal && retryMime) {
            console.warn(
                `[VideoCompressor] ${preferredMime} 录制产出 0 字节（编码器异常），降级 ${retryMime} 重试`
            );
            result = await this._recordCompressed(
                file, videoInfo, outW, outH, effectiveMaxDuration, retryMime, null
            );
        }
        return result;
    },

    // 单次压缩录制（内部方法）：按指定 mimeType 用 Canvas + MediaRecorder 录制。
    // 0 字节产物经 buildRecorderResult 返回 fallbackToOriginal 结果，降级/回退
    // 决策由调用方 compressVideoForReference 做
    async _recordCompressed(file, videoInfo, outW, outH, effectiveMaxDuration, mimeType, onProgress) {
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
            let recordedBytes = 0;
            let drewFrames = 0;

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
                    console.warn(`[VideoCompressor] 视频播放失败: ${err.message || err}`);
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

                // captureStream 传 FPS 作为「上限提示」，但浏览器不保证严格按此值采样
                // （高刷屏上会按屏幕刷新率），真正的限频由下方 drawFrame 的时间戳节流保证。
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

                const options = { mimeType };
                if (mimeType.includes('webm')) {
                    options.videoBitsPerSecond = this.VIDEO_BITRATE;
                }

                try {
                    recorder = new MediaRecorder(combinedStream, options);
                } catch (e) {
                    console.warn(`[VideoCompressor] MediaRecorder 初始化失败: ${e.message}`);
                    cleanup();
                    reject(new Error('MediaRecorder 初始化失败: ' + e.message));
                    return;
                }

                recorder.ondataavailable = (e) => {
                    if (e.data && e.data.size > 0) {
                        chunks.push(e.data);
                        recordedBytes += e.data.size;
                    }
                };

                recorder.onstop = () => {
                    cleanup();
                    const result = this.buildRecorderResult(chunks, mimeType, file, videoInfo, {
                        duration, effectiveDuration, outW, outH
                    });
                    if (result.fallbackToOriginal) {
                        // 0 字节诊断：区分「一帧未绘制（播放被拦/提前停止）」与
                        // 「绘制了帧但编码器未吐数据（浏览器编码器被阉割，如 360极速浏览器）」
                        console.warn(
                            `[VideoCompressor] 录制产出 0 字节: ` +
                            `chunks=${chunks.length}, recordedBytes=${recordedBytes}, drewFrames=${drewFrames}, ` +
                            `recorderState=${recorder ? recorder.state : 'n/a'}, ` +
                            `video currentTime=${video.currentTime}, paused=${video.paused}, ended=${video.ended}, ` +
                            `readyState=${video.readyState}, mimeType=${mimeType}`
                        );
                    } else {
                        console.log(
                            `[VideoCompressor] 录制完成: ${(result.blob.size / 1024 / 1024).toFixed(1)}MB, ` +
                            `chunks=${chunks.length}, drewFrames=${drewFrames}, truncated=${result.truncated}`
                        );
                    }
                    onProgress?.(100);
                    resolve(result);
                };

                recorder.onerror = (e) => {
                    console.warn('[VideoCompressor] 录制出错:', e.error?.message || e.error || 'unknown');
                    cleanup();
                    reject(new Error('录制出错: ' + (e.error?.message || 'unknown')));
                };

                recorder.start(1000);
                console.log(
                    `[VideoCompressor] 开始录制: ${outW}x${outH}@${this.FPS}fps, mime=${mimeType}, ` +
                    `bitrate=${options.videoBitsPerSecond || 'default'}, ` +
                    `audioTracks=${combinedStream.getAudioTracks().length}, ` +
                    `effectiveDuration=${effectiveDuration.toFixed(1)}s` +
                    (truncated ? `(截断自 ${duration.toFixed(1)}s)` : '')
                );

                // 帧率节流：requestAnimationFrame 的回调首个参数是 DOMHighResTimeStamp。
                // 在高刷屏（120Hz/144Hz）上 rAF 会被高频调用，若不节流会产出超过 FPS
                // 的超频帧（如 120fps），触发下游模型帧率上限报错。仅当距上一帧达到
                // 间隔阈值时才真正 drawImage，从而把 canvas 实际重绘频率钉在 FPS 上。
                const frameInterval = 1000 / this.FPS;
                let lastDrawTime = -Infinity;

                const drawFrame = (now) => {
                    if (stopped) return;
                    if (video.ended || video.paused || video.currentTime >= effectiveDuration) {
                        // paused=true 且 drewFrames=0 说明 play() 后立即被浏览器暂停，
                        // 是 0 字节产物的常见直接原因，打印便于定位
                        console.log(
                            `[VideoCompressor] 停止绘制: ended=${video.ended}, paused=${video.paused}, ` +
                            `currentTime=${video.currentTime.toFixed(2)}s/${effectiveDuration.toFixed(2)}s, drewFrames=${drewFrames}`
                        );
                        doStop();
                        return;
                    }

                    // 进度更新不受节流影响，保证 UI 流畅
                    if (effectiveDuration > 0) {
                        const progress = Math.min(99, Math.round((video.currentTime / effectiveDuration) * 100));
                        onProgress?.(progress);
                    }

                    // 首帧或达到间隔才绘制；否则跳过本次，直接排下一帧
                    if (now - lastDrawTime >= frameInterval) {
                        lastDrawTime = now;
                        ctx.drawImage(video, 0, 0, outW, outH);
                        drewFrames++;
                    }

                    animationId = requestAnimationFrame(drawFrame);
                };
                animationId = requestAnimationFrame(drawFrame);
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

    // 录制产物构造（纯函数，便于单测）：chunks 为空（MediaRecorder 一帧未吐，
    // 如 360极速浏览器编码器异常）时回退原始文件，由后端校验兜底，避免 0 字节
    // 文件被静默传到参考视频链路（下游 ffmpeg EBML 解析失败 → edit 任务无视频被 400）。
    buildRecorderResult(chunks, mimeType, file, videoInfo, dims) {
        const outputType = mimeType.includes('mp4') ? 'video/mp4' : 'video/webm';
        const blob = new Blob(chunks, { type: outputType });
        if (blob.size === 0) {
            return {
                blob: file,
                compressed: false,
                fallbackToOriginal: true,
                info: videoInfo
            };
        }
        return {
            blob,
            compressed: true,
            truncated: dims.duration > dims.effectiveDuration,
            info: {
                ...videoInfo,
                outputWidth: dims.outW,
                outputHeight: dims.outH,
                outputDuration: dims.effectiveDuration,
                outputType
            }
        };
    },

    async compressVideoTo480p(file, onProgress, maxDuration) {
        return this.compressVideoForReference(file, onProgress, maxDuration);
    }
};
