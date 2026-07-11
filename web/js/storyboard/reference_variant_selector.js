import state from './state.js';
import * as api from './api.js';
import {
    characterReferenceSelectionKey,
    parseReferenceImages,
    sceneToPromptPayload,
} from './adapters.js';
import { getThumbnailUrl, renderApp } from './render.js';

let activePopover = null;
let saving = false;

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function urlFromReferenceImage(item) {
    if (!item) return '';
    if (typeof item === 'string') return item;
    return item.url || item.file_url || item.image_url || item.reference_image || item.path || '';
}

function labelFromReferenceImage(item, fallback) {
    if (!item || typeof item === 'string') return fallback;
    return item.label || item.name || item.title || item.caption || item.angle || item.view || fallback;
}

function getAssetPrimaryUrl(asset) {
    return asset?.reference_image || asset?.avatar || urlFromReferenceImage((asset?.reference_images || [])[0]);
}

function buildOptions(asset, variantType) {
    const labelNoun = variantType === 'location' ? '角度' : '服装';
    const options = [];
    const primaryUrl = getAssetPrimaryUrl(asset);
    if (primaryUrl) {
        options.push({
            url: primaryUrl,
            label: '默认',
            angle: '',
            source: 'reference_image',
        });
    }
    parseReferenceImages(asset?.reference_images || asset?.referenceImages).forEach((item, index) => {
        const url = urlFromReferenceImage(item);
        if (!url || options.some(option => option.url === url)) return;
        options.push({
            url,
            label: labelFromReferenceImage(item, `${labelNoun}${index + 1}`),
            angle: typeof item === 'object' ? (item.angle || item.view || '') : '',
            source: 'reference_images',
        });
    });
    return options;
}

function findCharacter({ characterId, characterName }) {
    const chars = state.characters || [];
    if (characterId) {
        const found = chars.find(item => String(item.id) === String(characterId));
        if (found) return found;
    }
    return chars.find(item => String(item.name || '').trim() === String(characterName || '').trim()) || null;
}

function findLocation(scene, locationId) {
    const locId = locationId || scene?.location?.id || scene?.location?.db_id;
    const locations = state.locations || [];
    if (locId) {
        const found = locations.find(item => String(item.id) === String(locId));
        if (found) return found;
    }
    if (scene?.location?.name) {
        return locations.find(item => String(item.name || '').trim() === String(scene.location.name || '').trim())
            || scene.location;
    }
    return scene?.location || null;
}

function ensureSelections(scene) {
    scene.referenceSelections = scene.referenceSelections || { schema_version: 1, characters: {}, location: null };
    scene.referenceSelections.schema_version = 1;
    scene.referenceSelections.characters = scene.referenceSelections.characters || {};
    return scene.referenceSelections;
}

async function persistSelection(scene, applySelection) {
    const previous = JSON.parse(JSON.stringify(scene.referenceSelections || {}));
    applySelection();
    try {
        const payload = sceneToPromptPayload(scene);
        await api.updateScenePrompt(scene.id, payload);
        scene.promptJson = payload;
        scene._fullPrompt = payload;
        if (scene.raw) scene.raw.prompt_json = payload;
        renderApp();
    } catch (error) {
        scene.referenceSelections = previous;
        renderApp();
        throw error;
    }
}

function closePopover() {
    if (activePopover) {
        activePopover.remove();
        activePopover = null;
    }
    document.removeEventListener('click', handleOutsideClick, true);
    document.removeEventListener('keydown', handleKeydown, true);
}

function handleOutsideClick(event) {
    if (activePopover && !activePopover.contains(event.target)) {
        closePopover();
    }
}

function focusOption(delta) {
    if (!activePopover) return;
    const buttons = Array.from(activePopover.querySelectorAll('.reference-variant-option:not([disabled])'));
    if (!buttons.length) return;
    const currentIndex = buttons.indexOf(document.activeElement);
    const nextIndex = currentIndex < 0 ? 0 : (currentIndex + delta + buttons.length) % buttons.length;
    buttons[nextIndex].focus();
}

function handleKeydown(event) {
    if (event.key === 'Escape') {
        closePopover();
        return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        event.preventDefault();
        focusOption(1);
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        event.preventDefault();
        focusOption(-1);
    }
}

function positionPopover(popover, anchor) {
    const rect = anchor.getBoundingClientRect();
    const margin = 8;
    document.body.appendChild(popover);
    const popRect = popover.getBoundingClientRect();
    let left = rect.left + window.scrollX;
    let top = rect.bottom + window.scrollY + margin;
    const maxLeft = window.scrollX + document.documentElement.clientWidth - popRect.width - margin;
    if (left > maxLeft) left = Math.max(window.scrollX + margin, maxLeft);
    const maxTop = window.scrollY + document.documentElement.clientHeight - popRect.height - margin;
    if (top > maxTop) top = Math.max(window.scrollY + margin, rect.top + window.scrollY - popRect.height - margin);
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
}

function renderOptions({ title, options, currentUrl, emptyText, onSwitchLocation }) {
    return `
        <div class="reference-variant-popover" role="dialog" aria-label="${escapeHtml(title)}">
            <div class="reference-variant-header">
                <strong>${escapeHtml(title)}</strong>
                ${onSwitchLocation ? '<button class="reference-variant-switch" data-reference-switch-location>切换场景</button>' : ''}
            </div>
            <div class="reference-variant-grid">
                ${options.map((option, index) => `
                    <button class="reference-variant-option ${option.url === currentUrl ? 'selected' : ''}"
                        data-reference-option-index="${index}"
                        aria-label="${escapeHtml(option.label)}">
                        <span class="reference-variant-thumb">
                            ${option.url ? `<img src="${escapeHtml(getThumbnailUrl(option.url, 96))}" alt="">` : '<span>无图</span>'}
                        </span>
                        <span class="reference-variant-name">${escapeHtml(option.label)}</span>
                        ${option.url === currentUrl ? '<span class="reference-variant-check">✓</span>' : ''}
                    </button>
                `).join('')}
            </div>
            ${options.length <= 1 ? `<div class="reference-variant-empty">${escapeHtml(emptyText)}</div>` : ''}
        </div>`;
}

export function openReferenceVariantSelector({
    type,
    sceneId,
    characterId = '',
    characterName = '',
    locationId = '',
    anchor,
    notify = () => {},
    openLocationSwitcher = null,
}) {
    const scene = (state.scenes || []).find(item => String(item.id) === String(sceneId)) || state.scenes.find(item => item.id === state.currentSceneId);
    if (!scene || !anchor) return false;
    const asset = type === 'location'
        ? findLocation(scene, locationId)
        : findCharacter({ characterId, characterName });
    if (!asset) {
        notify(type === 'location' ? '当前分镜还没有可选择的场景' : '未找到该角色资产');
        return false;
    }

    closePopover();
    const options = buildOptions(asset, type);
    const selections = ensureSelections(scene);
    const key = type === 'location' ? '' : characterReferenceSelectionKey(asset || { name: characterName });
    const current = type === 'location' ? selections.location : selections.characters[key];
    const currentUrl = current?.url || getAssetPrimaryUrl(asset);
    const title = type === 'location'
        ? `选择场景角度 · ${asset.name || scene.location?.name || '场景'}`
        : `选择角色服装 · ${asset.name || characterName}`;
    const popover = document.createElement('div');
    popover.innerHTML = renderOptions({
        title,
        options,
        currentUrl,
        emptyText: type === 'location' ? '暂无其他角度' : '暂无其他服装',
        onSwitchLocation: type === 'location' && typeof openLocationSwitcher === 'function',
    });
    activePopover = popover.firstElementChild;

    activePopover.addEventListener('click', async (event) => {
        event.stopPropagation();
        const switchBtn = event.target.closest('[data-reference-switch-location]');
        if (switchBtn) {
            closePopover();
            openLocationSwitcher(scene, anchor);
            return;
        }
        const optionButton = event.target.closest('[data-reference-option-index]');
        if (!optionButton || saving) return;
        const option = options[Number(optionButton.dataset.referenceOptionIndex)];
        if (!option) return;
        saving = true;
        activePopover.classList.add('saving');
        try {
            await persistSelection(scene, () => {
                const nextSelections = ensureSelections(scene);
                if (type === 'location') {
                    nextSelections.location = {
                        location_id: asset.id || scene.location?.id || null,
                        name: asset.name || scene.location?.name || '',
                        url: option.url,
                        label: option.label,
                        angle: option.angle || '',
                        source: option.source,
                    };
                } else if (key) {
                    nextSelections.characters[key] = {
                        character_id: asset.id || null,
                        name: asset.name || characterName,
                        url: option.url,
                        label: option.label,
                        source: option.source,
                    };
                }
            });
            closePopover();
        } catch (error) {
            notify(`保存参考图选择失败: ${error.message || error}`);
        } finally {
            saving = false;
            if (activePopover) activePopover.classList.remove('saving');
        }
    });

    positionPopover(activePopover, anchor);
    setTimeout(() => {
        document.addEventListener('click', handleOutsideClick, true);
        document.addEventListener('keydown', handleKeydown, true);
        activePopover?.querySelector('.reference-variant-option')?.focus();
    }, 0);
    return true;
}

export function clearLocationReferenceSelection(scene) {
    if (!scene) return;
    const selections = ensureSelections(scene);
    selections.location = null;
}

export function closeReferenceVariantSelector() {
    closePopover();
}
