/**
 * 分秒口播 timeline 防御性剥离测试（会话 3e88c1db 事故回归）。
 *
 * 事故形态：Agent 把 timeline 写成"画面+口播"混合时间轴且自带前缀
 * （"0s：中秋暖光灯笼画面""2s：旁白：中秋想家难安眠"），确认卡按
 * 下标渲染出现双重秒标（"0s 0s：…"），"旁白："前缀混进口播文本。
 *
 * 前端职责（治本在 SOP：timeline 只放口播短句本身）：渲染前剥离
 * 自带秒标与"旁白：/口播："前缀，语速统计基于剥离后文本。
 */
const assert = require('node:assert/strict');

global.window = { escapeHtml: (t) => String(t == null ? '' : t) };
require('../../web/js/marketing_article_card.js');
const card = global.window.MarketingArticleCard;

const script = {
  type: 'article_to_video_script',
  video_title: '测试',
  clips: [
    {
      index: 1,
      duration_seconds: 6,
      prompt: '画面描述与引号台词见分秒时间轴',
      // 事故真实形态：自带秒标 + 旁白前缀 + 画面条目混入
      timeline: [
        '0s：中秋暖光灯笼画面',
        '桂花花瓣缓缓飘落',
        '2s：旁白：中秋想家难安眠',
        '口播：乌灵帮你心归位',
        '3 - 5s：福利提示字幕浮现',
        '在外打拼盼中秋',
      ],
    },
  ],
};

const html = card.renderCard(script);

// 双重秒标：条目自带 "0s：" 不再与下标秒标重复出现
assert.ok(!html.includes('0s\n'), '不应出现裸秒标行');
assert.ok(!/>0s：/.test(html), '条目自带秒标前缀应被剥离');
assert.ok(!html.includes('旁白：'), '"旁白："前缀应被剥离');
assert.ok(!html.includes('口播：'), '"口播："前缀应被剥离');

// 剥离后的口播文本仍在展示
assert.ok(html.includes('中秋想家难安眠'), '剥离前缀后的口播文本保留');
assert.ok(html.includes('在外打拼盼中秋'), '纯口播短句原样保留');

// 下标秒标仍在（前端按数组下标标注）
assert.ok(html.includes('>0s<'), '下标秒标保留');

// 纯 timeline 的既有行为不回归（transformMessageText 卡片替换）
const transformed = card.transformMessageText(
  '请确认：\n```json\n' + JSON.stringify(script, null, 2) + '\n```');
assert.ok(transformed && transformed.includes('asc-timeline'), '确认卡时间轴正常渲染');

console.log('timeline 剥离测试全部通过');
