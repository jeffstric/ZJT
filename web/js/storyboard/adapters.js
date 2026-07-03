// 后端 storyboard_scene 字段 → 前端 scene 对象（命名与后端模型对齐）
// 2026-06-24 重构：废弃 demo2 照搬的 thumbnail/previewImageUrl/sceneInfo/charDesc/voiceoverText，
// 改为 videoType/videoPrompt/selectedFirstFrameId 等；配音拆为 dialogues。

export function normalizePagedList(response) {
    // 资产接口统一为 {code, message, data:{total,page,page_size,data:[...]}}
    if (Array.isArray(response)) return response;
    if (!response) return [];
    const outer = response.data !== undefined ? response.data : response;
    if (Array.isArray(outer)) return outer;
    if (outer && Array.isArray(outer.data)) return outer.data;
    return [];
}

export function formatDuration(value) {
    const seconds = parseDurationSeconds(value);
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

export function parseDurationSeconds(value) {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return Math.max(0, Math.round(value));
    }
    if (typeof value !== 'string') return 0;
    const parts = value.split(':').map(part => parseInt(part, 10));
    if (parts.length === 2 && parts.every(Number.isFinite)) {
        return Math.max(0, parts[0] * 60 + parts[1]);
    }
    const parsed = parseInt(value, 10);
    return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

export function mapAssetAvatar(item) {
    if (!item) return '';
    if (item.reference_image) return item.reference_image;
    if (item.referenceImage) return item.referenceImage;
    if (Array.isArray(item.reference_images) && item.reference_images.length > 0) {
        const first = item.reference_images[0];
        return typeof first === 'string' ? first : (first.url || first.file_url || first.image_url || '');
    }
    if (item.avatar) return item.avatar;
    if (item.image_url) return item.image_url;
    if (item.imageUrl) return item.imageUrl;
    if (item.cover_url) return item.cover_url;
    if (item.pic_url) return item.pic_url;
    return '';
}

export function assetFromApi(item) {
    const avatar = mapAssetAvatar(item);
    return {
        id: item.id,
        name: item.name || item.title || `#${item.id}`,
        avatar,
        reference_image: item.reference_image || item.referenceImage || avatar,
        reference_images: item.reference_images || [],
        raw: item,
    };
}

export function dialogueFromApi(raw = {}) {
    return {
        id: raw.id,
        sceneId: raw.scene_id,
        sortOrder: raw.sort_order || 0,
        characterId: raw.character_id ?? null,
        text: raw.text || '',
        speed: raw.speed ?? 1.0,
        volume: raw.volume ?? 100,
        selectedAudioId: raw.selected_audio_id ?? null,
        audioUrl: raw.audio_url || '',
        raw,
    };
}

export function dialoguesFromApi(rawDialogues = []) {
    return rawDialogues.map(dialogueFromApi)
        .sort((left, right) => (left.sortOrder || 0) - (right.sortOrder || 0));
}

export function sceneFromApi(raw = {}) {
    const prompt = raw.prompt_json || {};
    return {
        id: raw.id,
        storyboardId: raw.storyboard_id,
        sortOrder: raw.sort_order || 0,
        title: raw.title || `分镜${raw.sort_order ?? ''}`,
        duration: parseDurationSeconds(raw.duration || 5),
        durationLabel: formatDuration(raw.duration || 5),
        videoType: raw.video_type || 'video',
        videoPrompt: raw.video_prompt || '',
        videoConfigJson: raw.video_config_json || {},
        selectedFirstFrameId: raw.selected_first_frame_id ?? null,
        selectedLastFrameId: raw.selected_last_frame_id ?? null,
        selectedVideoId: raw.selected_video_id ?? null,
        // 当前选中 asset 的结果 URL（后端 list_by_storyboard LEFT JOIN 提供）
        firstFrameUrl: raw.first_frame_url || '',
        lastFrameUrl: raw.last_frame_url || '',
        videoUrl: raw.video_url || '',
        thumbnail: raw.preview_image_url || raw.thumbnail || raw.first_frame_url || '',
        // 画面提示词（key 与后端 prompt_json 对齐）
        promptJson: {
            perspective: prompt.perspective || '',
            style: prompt.style || '',
            scene_desc: prompt.scene_desc || '',
            character_desc: prompt.character_desc || '',
        },
        sceneInfo: {
            perspective: prompt.perspective || '',
            style: prompt.style || '',
            sceneDesc: prompt.scene_desc || '',
            charDesc: prompt.character_desc || '',
        },
        status: {
            image: raw.image_status,
            video: raw.video_status,
        },
        dialogues: dialoguesFromApi(raw.dialogues || []),
        // 当前分镜关联的场景/道具（从 prompt_json 或顶层提取，后端创建时会放在 prompt 里）
        location: raw.location || prompt.location || (prompt.source ? { id: prompt.source.location_db_id || prompt.source.location_id, name: prompt.source.location_name } : null),
        props: raw.props || prompt.props || [],
        raw,
    };
}

export function scenesFromApi(rawScenes = []) {
    return rawScenes
        .map(sceneFromApi)
        .sort((left, right) => (left.sortOrder || 0) - (right.sortOrder || 0));
}

export function sceneToPromptPayload(scene) {
    const p = scene.promptJson || {};
    const info = scene.sceneInfo || {};
    // 保留原始 prompt_json 中的额外字段（如 location, props, source）
    let original = {};
    if (scene.raw && scene.raw.prompt_json) {
        original = typeof scene.raw.prompt_json === 'string' ? JSON.parse(scene.raw.prompt_json) : scene.raw.prompt_json;
    } else if (scene._fullPrompt) {
        original = scene._fullPrompt;
    }
    return {
        ...original,
        perspective: p.perspective || info.perspective || '',
        style: p.style || info.style || '',
        scene_desc: p.scene_desc || info.sceneDesc || '',
        character_desc: p.character_desc || info.charDesc || '',
    };
}

export function sceneToUpdatePayload(scene) {
    return {
        title: scene.title || '',
        duration: parseDurationSeconds(scene.duration),
        video_type: scene.videoType || 'video',
        video_prompt: scene.videoPrompt || '',
        video_config_json: scene.videoConfigJson || {},
        prompt_json: sceneToPromptPayload(scene),
    };
}

export function dialogueToPayload(dialogue) {
    return {
        character_id: dialogue.characterId ?? null,
        text: dialogue.text || '',
        speed: dialogue.speed ?? 1.0,
        volume: dialogue.volume ?? 100,
    };
}

export function buildStoryboardTitle(storyboard = {}) {
    if (storyboard.title) return storyboard.title;
    const episode = storyboard.episode_number || 1;
    return `第${episode}集故事板`;
}
