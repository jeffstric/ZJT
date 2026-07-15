/**
 * 故事板 UI 分区刷新：region 常量与组合预设。
 * 业务侧应 `refresh(regions)` 声明脏区，禁止无脑全量 renderApp。
 */

export const Region = {
    HEADER: 'header',
    HEADER_POWER: 'headerPower',
    SCENE_CHROME: 'sceneChrome',
    LEFT_TABS: 'leftTabs',
    LEFT_TAB_BODY: 'leftTabBody',
    /** 整个左栏（画面/对话 + 助手），切镜时用 */
    LEFT_SIDEBAR: 'leftSidebar',
    AGENT_PANEL: 'agentPanel',
    AGENT_LOG: 'agentLog',
    AGENT_COMPOSER: 'agentComposer',
    PREVIEW: 'preview',
    /** 整个中栏（timeline / grid） */
    CENTER: 'center',
    TIMELINE_CHROME: 'timelineChrome',
    TIMELINE_LIST: 'timelineList',
    GRID: 'grid',
    CANDIDATES: 'candidates',
    /** 所有弹层（export / model / power / mention / …） */
    MODAL: 'modal',
};

/** 切当前分镜后通常要刷的区域（不含全页；TIMELINE_LIST 仅更新选中态/缩略，不拆 preview） */
export const REGIONS_ON_SCENE_CHANGE = [
    Region.LEFT_SIDEBAR,
    Region.PREVIEW,
    Region.CANDIDATES,
    Region.TIMELINE_LIST,
    Region.TIMELINE_CHROME,
    Region.GRID,
];

/** 增删/复制分镜后：结构重建 list，仍不整页 */
export const REGIONS_ON_SCENE_STRUCT = [
    Region.TIMELINE_LIST,
    Region.GRID,
    Region.TIMELINE_CHROME,
    Region.LEFT_SIDEBAR,
    Region.CANDIDATES,
    Region.PREVIEW,
];

/** 仅助手对话流 */
export const REGIONS_AGENT_STREAM = [Region.AGENT_LOG];

/** 打开/关闭弹窗 */
export const REGIONS_MODAL = [Region.MODAL];
