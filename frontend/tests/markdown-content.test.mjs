import { after, afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';

const cache = resolve('node_modules/.cache/earthai-markdown-tests');
await mkdir(cache, { recursive: true });
await build({
  entryPoints: ['src/components/Content.tsx'],
  outfile: `${cache}/content.mjs`,
  bundle: true,
  packages: 'external',
  platform: 'node',
  target: 'node22',
  jsx: 'automatic',
  format: 'esm',
  loader: { '.css': 'text' },
  logOverride: { 'ignored-bare-import': 'silent' },
});

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/chat', pretendToBeVisual: true });
const { window } = dom;
Object.assign(globalThis, {
  window,
  document: window.document,
  Node: window.Node,
  HTMLElement: window.HTMLElement,
  Event: window.Event,
  MouseEvent: window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
const copied = [];
Object.defineProperty(window.navigator, 'clipboard', { value: { writeText: async value => { copied.push(value); } } });
const { createRoot } = await import('react-dom/client');
const { Content } = await import(pathToFileURL(`${cache}/content.mjs`).href);
const host = document.getElementById('root');
let root;
const render = async text => { await act(async () => { root.render(createElement(Content, { text })); }); };

beforeEach(() => { copied.length = 0; root = createRoot(host); });
afterEach(async () => { await act(async () => { root.unmount(); }); });
after(() => { dom.window.close(); });

test('Markdown tables render GFM headers, rows and all three alignments inside a scoped scroll region', async () => {
  await render('| 名称 | 状态 | 数量 |\n| :--- | :---: | ---: |\n| **服务** | 运行中 | 12 |\n| 数据库 | *正常* | 3 |');
  const region = host.querySelector('.markdown-table-scroll');
  assert.ok(region);
  assert.equal(region.getAttribute('role'), 'region');
  assert.equal(region.tabIndex, 0);
  assert.equal(region.querySelectorAll('thead th').length, 3);
  assert.equal(region.querySelectorAll('tbody tr').length, 2);
  assert.deepEqual([...region.querySelectorAll('thead th')].map(cell => cell.style.textAlign), ['left', 'center', 'right']);
  assert.deepEqual([...region.querySelectorAll('tbody tr:first-child td')].map(cell => cell.style.textAlign), ['left', 'center', 'right']);
  assert.equal(region.querySelector('td strong').textContent, '服务');
  assert.equal(region.querySelector('td em').textContent, '正常');

  const css = await readFile('src/components/Content.css', 'utf8');
  const style = document.createElement('style');
  style.textContent = css;
  document.head.append(style);
  try {
    const scrollStyle = window.getComputedStyle(region);
    assert.equal(scrollStyle.overflowX, 'auto');
    assert.equal(scrollStyle.maxWidth, '100%');
    assert.equal(scrollStyle.minWidth, '0');
    assert.equal(scrollStyle.contain, 'inline-size');
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].map(match => match[1].trim());
    assert.ok(selectors.length > 0);
    assert.ok(selectors.every(selector => selector.startsWith('.rich-content.markdown-content')));
  } finally {
    style.remove();
  }
});

test('Markdown renders links, emphasis, quotes, rules, strikethrough, nested lists and disabled task boxes', async () => {
  await render('# 标题\n\n[文档](/docs) **加粗** *强调* ~~删除~~\n\n> 引用\n\n---\n\n- [x] 完成\n- [ ] 待办\n\n1. 第一项\n   - 子项');
  assert.equal(host.querySelector('h1').textContent, '标题');
  assert.equal(host.querySelector('a').getAttribute('href'), '/docs');
  assert.equal(host.querySelector('strong').textContent, '加粗');
  assert.equal(host.querySelector('em').textContent, '强调');
  assert.equal(host.querySelector('del').textContent, '删除');
  assert.equal(host.querySelector('blockquote').textContent.trim(), '引用');
  assert.ok(host.querySelector('hr'));
  assert.ok(host.querySelector('ol > li > ul > li'));
  const boxes = [...host.querySelectorAll('.task-list-item input[type="checkbox"]')];
  assert.equal(boxes.length, 2);
  assert.ok(boxes.every(box => box.disabled));
  assert.deepEqual(boxes.map(box => box.checked), [true, false]);
});

test('Markdown escapes raw HTML and rejects executable and unsupported link URLs while retaining safe links', async () => {
  await render([
    '<script>globalThis.markdownExecuted = true</script>',
    '',
    '<img src="https://tracker.invalid/raw.png" onerror="alert(1)">',
    '',
    '<iframe src="https://tracker.invalid"></iframe>',
    '',
    '[js](javascript:alert%281%29) [mixed](JaVaScRiPt:alert%281%29) [entity](jav&#x61;script:alert%281%29)',
    '[control](java&#x09;script:alert%281%29) [data](data:text/html;base64,PHNjcmlwdD4=) [vb](vbscript:msgbox%281%29)',
    '[file](file:///etc/passwd) [ftp](ftp://example.com/file) [network](//tracker.invalid/path) [slashes](<https:\\tracker.invalid>)',
    '[secure](https://example.com/docs) [plain](http://example.com) [mail](mailto:team@example.com) [local](/docs) [relative](../help) [fragment](#part) [query](?page=2)',
  ].join('\n'));
  assert.equal(host.querySelector('script, iframe, img, object, embed, style'), null);
  assert.match(host.textContent, /<script>globalThis\.markdownExecuted = true<\/script>/);
  assert.match(host.textContent, /<img src=/);
  assert.equal(globalThis.markdownExecuted, undefined);
  assert.deepEqual([...host.querySelectorAll('a')].map(link => link.getAttribute('href')), [
    'https://tracker.invalid/raw.png', 'https://example.com/docs', 'http://example.com', 'mailto:team@example.com', '/docs', '../help', '#part', '?page=2',
  ]);
  assert.ok([...host.querySelectorAll('a')].every(link => link.getAttribute('rel') === 'noopener noreferrer'));
  for (const label of ['js', 'mixed', 'entity', 'control', 'data', 'vb', 'file', 'ftp', 'network', 'slashes']) {
    assert.ok([...host.querySelectorAll('span')].some(span => span.textContent === label));
  }
});

test('Markdown fenced and indented code retain the existing copy structure, language and exact clipboard content', async () => {
  const code = 'const answer = 42;\n  console.log(answer);';
  await render(`行内 \`answer\`\n\n\`\`\`typescript\n${code}\n\`\`\`\n\n\`\`\`\nplain text\n\`\`\`\n\n    indented();`);
  const blocks = [...host.querySelectorAll('.code-block')];
  assert.equal(blocks.length, 3);
  assert.deepEqual(blocks.map(block => block.querySelector('.code-heading > span').textContent), ['typescript', 'text', 'text']);
  assert.equal(blocks[0].querySelector('pre > code').className, 'language-typescript');
  assert.equal(blocks[0].querySelector('pre > code').textContent, `${code}\n`);
  assert.equal(host.querySelector('p > code').textContent, 'answer');
  assert.equal(host.querySelector('p .code-block'), null);
  for (const block of blocks) {
    const button = block.querySelector('.code-heading > button[aria-label="复制内容"]');
    assert.ok(button);
    assert.ok(button.classList.contains('icon-button'));
    await act(async () => { button.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
  }
  assert.deepEqual(copied, [code, 'plain text', 'indented();']);
});

test('Markdown images never render an image element or fetch a remote resource and only expose safe links', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async input => { requests.push(input); throw new Error('Unexpected Markdown request'); };
  try {
    await render('![远程示例](https://tracker.invalid/pixel.png "图片说明")\n\n![本站图片](/images/example.png)\n\n![引用图片][image]\n\n[image]: https://tracker.invalid/reference.png\n\n![恶意](javascript:alert%281%29) ![数据](data:image/png;base64,AAAA) ![协议相对](//tracker.invalid/pixel.png)');
    assert.equal(host.querySelector('img, picture, source, video, audio, iframe'), null);
    assert.deepEqual(requests, []);
    const links = [...host.querySelectorAll('a.markdown-image-link')];
    assert.deepEqual(links.map(link => link.getAttribute('href')), ['https://tracker.invalid/pixel.png', '/images/example.png', 'https://tracker.invalid/reference.png']);
    assert.equal(links[0].textContent, '图片：远程示例');
    assert.equal(links[0].title, '图片说明');
    assert.deepEqual([...host.querySelectorAll('span.markdown-image-link')].map(span => span.textContent), ['图片：恶意', '图片：数据', '图片：协议相对']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Markdown renders every streaming prefix and incomplete fences, tables, links and images without crashing', async () => {
  const text = '# 流式回复\n\n| 服务 | 数量 |\n| :--- | ---: |\n| **EarthAI** | 1 |\n\n> 引用 *内容*\n\n- [x] 完成\n\n[文档](https://example.com/docs)\n\n![图片](https://tracker.invalid/pixel.png)\n\n```js\nconst message = "hello";\nconsole.log(message);\n```';
  for (let length = 0; length <= text.length; length += 1) {
    await render(text.slice(0, length));
    assert.ok(host.querySelector('.rich-content.markdown-content'));
    assert.equal(host.querySelector('img, script, iframe'), null);
  }
  for (const incomplete of ['`', '```', '```python\nprint("partial', '| A | B |\n| --- |', '[文档](javascript:', '![图片](', '**加粗', '<img src="https://tracker.invalid/', '[引用][id]\n\n[id]:']) {
    await render(incomplete);
    assert.ok(host.querySelector('.markdown-content'));
    assert.equal(host.querySelector('img, script, iframe'), null);
  }
  await render('```python\nprint("partial');
  const button = host.querySelector('.code-heading button');
  assert.equal(host.querySelector('.code-heading > span').textContent, 'python');
  await act(async () => { button.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
  assert.deepEqual(copied, ['print("partial']);
});
