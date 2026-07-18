const { escapeHtml } = require('../js/utils.js');

describe('escapeHtml', () => {
  test('转义 HTML 特殊字符', () => {
    expect(escapeHtml('<script>alert("xss")</script>')).toBe(
      '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
    );
  });

  test('转义 & 符号', () => {
    expect(escapeHtml('a & b')).toBe('a &amp; b');
  });

  test('转义单引号为 &#39;', () => {
    expect(escapeHtml("it's")).toBe("it&#39;s");
  });

  test('null 返回空字符串', () => {
    expect(escapeHtml(null)).toBe('');
  });

  test('undefined 返回空字符串', () => {
    expect(escapeHtml(undefined)).toBe('');
  });

  test('数值 0 不应返回空字符串', () => {
    expect(escapeHtml(0)).toBe('0');
  });

  test('数字类型正确转为字符串', () => {
    expect(escapeHtml(42)).toBe('42');
  });

  test('空字符串返回空字符串', () => {
    expect(escapeHtml('')).toBe('');
  });

  test('不含特殊字符的字符串原样返回', () => {
    expect(escapeHtml('hello world')).toBe('hello world');
  });

  test('已转义的字符串不会双重转义', () => {
    expect(escapeHtml('&amp;')).toBe('&amp;amp;');
  });
});
