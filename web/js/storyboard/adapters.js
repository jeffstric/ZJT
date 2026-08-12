// 后端 storyboard_scene 字段 → 前端 scene 对象（命名与后端模型对齐）
// 2026-06-24 重构：废弃 demo2 照搬的 thumbnail/previewImageUrl/sceneInfo/charDesc/voiceoverText，
// 改为 videoType/videoPrompt/selectedFirstFrameId 等；配音拆为 dialogues。

// 分镜难易程度规范化（与后端 SceneDifficulty.normalize 对齐：易/中/难，非法值回落"中"）
export function normalizeDifficulty(value) {
    const v = String(value ?? '').trim();
    return v === '易' || v === '难' ? v : '中';
}

export function normalizePagedList(response) {
    // 资产接口统一为 {code, message, data:{total,page,page_size,data:[...]}}
    if (Array.isArray(response)) return response;
    if (!response) return [];
    const outer = response.data !== undefined ? response.data : response;
    if (Array.isArray(outer)) return outer;
    if (outer && Array.isArray(outer.data)) return outer.data;
    const keys = ['items', 'list', 'records', 'characters', 'props', 'locations', 'data'];
    for (const key of keys) {
        if (outer && Array.isArray(outer[key])) return outer[key];
    }
    if (outer && outer.data && typeof outer.data === 'object') {
        for (const key of keys) {
            if (Array.isArray(outer.data[key])) return outer.data[key];
        }
    }
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
    const referenceImages = parseReferenceImages(item.reference_images || item.referenceImages);
    if (referenceImages.length > 0) {
        const first = referenceImages.find(Boolean);
        if (typeof first === 'string') return first;
        if (first) {
            return first.url || first.file_url || first.image_url || first.reference_image || first.path || '';
        }
    }
    if (item.avatar) return item.avatar;
    if (item.image_url) return item.image_url;
    if (item.imageUrl) return item.imageUrl;
    if (item.cover_url) return item.cover_url;
    if (item.pic_url) return item.pic_url;
    if (item.file_url) return item.file_url;
    if (item.thumbnail_url) return item.thumbnail_url;
    if (item.url) return item.url;
    if (item.path) return item.path;
    return '';
}

export function assetFromApi(item) {
    const avatar = mapAssetAvatar(item);
    const referenceImages = parseReferenceImages(item.reference_images || item.referenceImages);
    return {
        id: item.id,
        name: item.name || item.title || `#${item.id}`,
        avatar,
        reference_image: item.reference_image || item.referenceImage || avatar,
        reference_images: referenceImages,
        raw: item,
    };
}

export function parseReferenceImages(value) {
    if (!value) return [];
    if (Array.isArray(value)) return value;
    if (typeof value !== 'string') return [];
    const trimmed = value.trim();
    if (!trimmed) return [];
    try {
        const parsed = JSON.parse(trimmed);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function normalizeReferenceSelectionItem(value) {
    if (!value || typeof value !== 'object') return null;
    const url = value.url || value.reference_image || value.image_url || value.file_url || '';
    if (!url) return null;
    return {
        character_id: value.character_id ?? value.characterId ?? null,
        location_id: value.location_id ?? value.locationId ?? null,
        name: value.name || '',
        url,
        label: value.label || '',
        angle: value.angle || '',
        source: value.source || '',
    };
}

export function normalizeReferenceSelections(value) {
    const raw = value && typeof value === 'object' ? value : {};
    const characters = {};
    const rawCharacters = raw.characters && typeof raw.characters === 'object' ? raw.characters : {};
    Object.entries(rawCharacters).forEach(([key, item]) => {
        const normalized = normalizeReferenceSelectionItem(item);
        if (normalized) characters[key] = normalized;
    });
    const location = normalizeReferenceSelectionItem(raw.location);
    return {
        schema_version: 1,
        characters,
        location,
    };
}

function hasReferenceSelections(value) {
    return Boolean(value?.location || Object.keys(value?.characters || {}).length > 0);
}

export function characterReferenceSelectionKey(character) {
    const id = character?.id ?? character?.character_id ?? character?.characterId ?? character?.db_id;
    if (id !== null && id !== undefined && id !== '') return String(id);
    const name = String(character?.name || '').trim().replace(/\s+/g, '');
    return name ? `name:${name}` : '';
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
        /** 情感向量：逗号分隔 8 维字符串，与 IndexTTS / audio_generate 一致 */
        emoVec: raw.emo_vec ?? raw.emoVec ?? null,
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
    const source = prompt.source || {};
    return {
        id: raw.id,
        storyboardId: raw.storyboard_id,
        sortOrder: raw.sort_order || 0,
        title: raw.title || `分镜${raw.sort_order ?? ''}`,
        // 剧本解析时的分组信息（埋在 prompt_json.source 里），用于左侧栏显示"幕XX"
        groupId: source.group_id || '',
        groupName: source.group_name || '',
        // duration 现为 DECIMAL(10,3) 浮点（音频求和同步后可达毫秒级精度）。
        // 数字原样保留浮点；字符串/undefined 时降级走 parseDurationSeconds（兼容旧值与 MM:SS）。
        duration: (typeof raw.duration === 'number' && Number.isFinite(raw.duration))
            ? raw.duration
            : parseDurationSeconds(raw.duration || 5),
        // 显示始终 floor 为 MM:SS（与产品决策一致：时间线标签保持秒级显示）。
        durationLabel: formatDuration(raw.duration || 5),
        videoType: raw.video_type || 'video',
        videoPrompt: raw.video_prompt || '',
        // 音频来源偏好：true=强制视频原声并跳过 TTS；false=优先对话配音。
        // 无可用对话配音时预览/导出会自动兜底视频原声（见 playback_audio.resolveSceneAudioMode）。
        // 数字人分镜默认 true。DB 字段沿用 audio_embedded，前端统一转 bool。
        audioEmbedded: raw.audio_embedded === true || raw.audio_embedded === 1,
        videoConfigJson: raw.video_config_json || {},
        // 分镜难易程度（易/中/难，后端 SceneDifficulty；非法值统一回落"中"）
        difficulty: normalizeDifficulty(raw.difficulty),
        // 所属幕/分镜组名称（后端独立列；旧数据为 null 时回落到 source.group_name）
        actName: raw.act_name || source.group_name || '',
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
        referenceSelections: normalizeReferenceSelections(prompt.reference_selections),
        _fullPrompt: prompt,
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
    }
    if (scene._fullPrompt && typeof scene._fullPrompt === 'object') {
        original = { ...original, ...scene._fullPrompt };
    }
    if (p && typeof p === 'object') {
        original = { ...original, ...p };
    }
    const referenceSelections = normalizeReferenceSelections(scene.referenceSelections || original.reference_selections);
    const payload = {
        ...original,
        perspective: p.perspective || info.perspective || '',
        style: p.style || info.style || '',
        scene_desc: p.scene_desc || info.sceneDesc || '',
        character_desc: p.character_desc || info.charDesc || '',
    };
    if (hasReferenceSelections(referenceSelections)) {
        payload.reference_selections = referenceSelections;
    } else {
        delete payload.reference_selections;
    }
    return payload;
}

export function sceneToUpdatePayload(scene) {
    return {
        title: scene.title || '',
        // duration 已为浮点，直接回传，不截断精度（后端 DECIMAL(10,3) 接收）。
        duration: scene.duration,
        video_type: scene.videoType || 'video',
        video_prompt: scene.videoPrompt || '',
        video_config_json: scene.videoConfigJson || {},
        audio_embedded: scene.audioEmbedded ? 1 : 0,
        difficulty: normalizeDifficulty(scene.difficulty),
        act_name: scene.actName || '',
        prompt_json: sceneToPromptPayload(scene),
    };
}

export function dialogueToPayload(dialogue) {
    return {
        character_id: dialogue.characterId ?? null,
        text: dialogue.text || '',
        speed: dialogue.speed ?? 1.0,
        volume: dialogue.volume ?? 100,
        emo_vec: dialogue.emoVec ?? null,
    };
}

export function buildStoryboardTitle(storyboard = {}) {
    if (storyboard.title) return storyboard.title;
    const episode = storyboard.episode_number || 1;
    return `第${episode}集故事板`;
}
