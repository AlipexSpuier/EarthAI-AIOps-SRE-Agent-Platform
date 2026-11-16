import { after, afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';

const cache = resolve('node_modules/.cache/earthai-streaming-tests');
await mkdir(cache, { recursive: true });
await build({
  stdin: { contents: "export { RunCard, RunLink } from './src/components/RunCard'; export * from './src/lib/executionTimeline';", resolveDir: resolve('.'), loader: 'ts' },
  outfile: `${cache}/streaming-ui.mjs`, bundle: true, packages: 'external', platform: 'node', target: 'node22', jsx: 'automatic', format: 'esm',
  loader: { '.css': 'text' }, logOverride: { 'ignored-bare-import': 'silent' },
  plugins: [{ name: 'execution-fixture', setup(builder) {
    builder.onLoad({ filter: /\/context\/AuthContext\.tsx$/ }, () => ({ contents: "export function useAuth() { return { user: { id: 'streaming-legacy-user', name: '流式回归用户', email: 'streaming@example.com', avatar: 'EA', theme: 'light', role: 'user', control_level: 'approve', allowed_control_levels: ['observe', 'approve', 'autonomous'] } }; }", loader: 'js' }));
    builder.onLoad({ filter: /\/context\/ExecutionContext\.tsx$/ }, () => ({ contents: 'export function useExecutions() { return globalThis.__streamingExecution; }', loader: 'js' }));
    builder.onLoad({ filter: /\/context\/ToastContext\.tsx$/ }, () => ({ contents: 'export function useToast() { return () => {}; }', loader: 'js' }));
  } }],
});
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/chat', pretendToBeVisual: true });
const { window } = dom;
Object.assign(globalThis, { window, document: window.document, Node: window.Node, HTMLElement: window.HTMLElement, Event: window.Event, MouseEvent: window.MouseEvent, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
const { createRoot } = await import('react-dom/client');
const { MemoryRouter } = await import('react-router-dom');
const { RunCard, RunLink, buildExecutionTimeline, toolPhase, toolExitCode, toolDurationMs, isMessageStreaming } = await import(pathToFileURL(`${cache}/streaming-ui.mjs`).href);
const stylesheet = await readFile('src/components/RunCard.css', 'utf8');
const at = seconds => new Date(Date.UTC(2026, 9, 24, 10, 0, seconds)).toISOString();
const makeRun = (extra = {}) => ({ id: 'run-stream', conversation_id: 'chat-stream', status: 'running', goal: '检查服务实际运行情况', model: 'stream-model', control_level: 'approve', created_at: at(0), updated_at: at(30), step_count: 2, ...extra });
const event = (id, type, data = {}, time = id) => ({ id, run_id: 'run-stream', type, data, created_at: at(time) });
const tool = (id, type, data = {}) => event(id, type, { tool_call_id: 'call-ssh', name: 'ssh_exec', ...data });
const model = (id, type, data = {}) => event(id, type, { message_id: 'message-1', turn: 1, ...data });
const makeApproval = (extra = {}) => ({ id: 'approve-1', run_id: 'run-stream', tool_name: 'ssh_exec', arguments: { command: 'systemctl restart example', reason: '恢复服务' }, risk: 'write', status: 'pending', created_at: at(3), ...extra });
let root;
let calls;
let copied;
beforeEach(() => {
  calls = []; copied = [];
  document.body.innerHTML = '<div id="root"></div>';
  root = createRoot(document.getElementById('root'));
  Object.defineProperty(window.navigator, 'clipboard', { configurable: true, value: { writeText: async value => { copied.push(value); } } });
  globalThis.__streamingExecution = { runs: {}, watch: async id => { calls.push(['watch', id]); }, cancel: async id => { calls.push(['cancel', id]); }, decide: async (approval, approved) => { calls.push(['decide', approval.id, approved]); } };
});
afterEach(async () => { await act(async () => root.unmount()); delete globalThis.__streamingExecution; });
after(() => dom.window.close());
async function renderEvents(events, run = makeRun(), approvals = [], extra = {}) {
  globalThis.__streamingExecution.runs[run.id] = { run, events, approvals, connection: 'live', ...extra };
  await act(async () => { root.render(createElement(RunCard, { run })); });
}
async function click(node) { assert.ok(node, 'click target exists'); await act(async () => { node.dispatchEvent(new MouseEvent('click', { bubbles: true })); }); }
const body = () => document.querySelector('.ea-run-body');
const messageText = () => document.querySelector('.ea-message-text')?.textContent;

test('public deltas aggregate by string message_id and deduplicate repeated persisted event IDs', () => {
  const start = model(1, 'model_start', { model: 'stream-model' });
  const one = model(2, 'assistant_delta', { delta: '你好，' });
  const two = model(3, 'assistant_delta', { delta: '正在检查。' });
  const other = model(4, 'assistant_delta', { message_id: 'message-2', turn: 2, delta: '另一段' });
  const items = buildExecutionTimeline([other, two, one, start, one, two]);
  assert.deepEqual(items.map(item => [item.kind, item.text]), [['message', '你好，正在检查。'], ['message', '另一段']]);
  assert.equal(items[0].eventId, 1);
  assert.equal(items[0].turn, 1);
});

test('authoritative assistant final replaces partial content and cannot be doubled by late replay', async () => {
  const events = [model(1, 'model_start'), model(2, 'assistant_delta', { delta: '临时内容' }), model(3, 'model_end', { duration_ms: 1250 }), model(4, 'assistant', { content: '完整结果' }), model(5, 'assistant_delta', { delta: '临时内容' })];
  const timeline = buildExecutionTimeline([...events, events[3]]);
  assert.equal(timeline.length, 1);
  assert.equal(timeline[0].text, '完整结果');
  await renderEvents(events, makeRun({ status: 'completed', summary: '完整结果' }));
  assert.equal(messageText(), '完整结果');
  assert.equal(document.querySelectorAll('.ea-summary').length, 0);
  assert.equal(document.querySelector('.ea-stream-cursor'), null);
  assert.equal(document.querySelector('.ea-generation-status'), null);
});

test('reset deltas replace existing text, including an empty reset', async () => {
  const events = [model(1, 'model_start'), model(2, 'assistant_delta', { delta: '已废弃' }), model(3, 'assistant_delta', { delta: '', reset: true }), model(4, 'assistant_delta', { delta: '新回复' }), model(5, 'assistant_delta', { delta: '重试后', reset: true }), model(6, 'assistant_delta', { delta: '完成' })];
  assert.equal(buildExecutionTimeline(events)[0].text, '重试后完成');
  await renderEvents(events);
  assert.equal(messageText(), '重试后完成');
  assert.ok(document.querySelector('.ea-stream-cursor'));
});

test('refresh/reconnect histories reconstruct the same text without mutating source events', () => {
  const history = [model(1, 'model_start'), model(2, 'assistant_delta', { delta: '第一段' }), model(3, 'assistant_delta', { delta: '第二段' }), tool(4, 'tool_start', { arguments: { command: 'uptime' } }), tool(5, 'tool_execution'), tool(6, 'tool_output', { stream: 'stdout', content: 'up 3 days\n' })];
  const original = JSON.stringify(history);
  assert.deepEqual(buildExecutionTimeline(history), buildExecutionTimeline([...history, ...history].reverse()));
  assert.equal(JSON.stringify(history), original);
});

test('legacy assistant and tool_result without starts remain visible in their original order', async () => {
  const events = [event(1, 'assistant', { content: '旧版公开回复' }), tool(2, 'tool_result', { ok: true, output: { stdout: 'legacy stdout', stderr: '', exit_code: 0 } }), event(3, 'assistant', { content: '旧版后续结果' })];
  const timeline = buildExecutionTimeline(events);
  assert.deepEqual(timeline.map(item => item.kind), ['message', 'tool', 'message']);
  assert.equal(toolPhase(timeline[1], 'completed'), 'succeeded');
  await renderEvents(events, makeRun({ status: 'completed' }));
  assert.match(body().textContent, /旧版公开回复/);
  assert.match(body().textContent, /legacy stdout/);
  assert.equal(document.querySelectorAll('.ea-step').length, 1);
  assert.match(body().textContent, /旧版后续结果/);
});

test('legacy tools without call IDs match a preceding tool start by name', () => {
  const items = buildExecutionTimeline([event(1, 'tool_start', { name: 'ssh_exec', arguments: { command: 'pwd' } }), event(2, 'tool_result', { name: 'ssh_exec', ok: true, output: { stdout: '/home/test', exit_code: 0 } })]);
  assert.equal(items.length, 1);
  assert.equal(items[0].parameters.command, 'pwd');
  assert.equal(items[0].stdout, '/home/test');
});

test('mixed plans, messages, tools, notices and errors preserve first-start chronology', async () => {
  const events = [event(1, 'plan', { steps: ['先检查', '再验证'] }), model(2, 'model_start'), model(3, 'assistant_delta', { delta: '开始检查' }), tool(4, 'tool_start', { arguments: { command: 'uptime' } }), event(5, 'notice', { message: '已切换为兼容读取方式' }), event(6, 'error', { message: '连接曾中断' }), model(7, 'assistant_delta', { delta: '，继续读取' }), tool(8, 'tool_result', { ok: true, output: '实际结果' }), model(9, 'assistant', { content: '本轮最终说明' }), model(10, 'model_end'), model(11, 'model_start', { message_id: 'message-2', turn: 2 }), model(12, 'assistant_delta', { message_id: 'message-2', turn: 2, delta: '第二轮' })];
  const items = buildExecutionTimeline([...events].reverse());
  assert.deepEqual(items.map(item => item.kind), ['plan', 'message', 'tool', 'notice', 'error', 'message']);
  assert.deepEqual(items.map(item => item.eventId), [1, 2, 4, 5, 6, 11]);
  await renderEvents(events);
  assert.deepEqual([...document.querySelectorAll('[data-timeline-kind]')].map(node => node.dataset.timelineKind), ['plan', 'message', 'tool', 'notice', 'error', 'message']);
  assert.equal(document.querySelector('[data-message-id="message-1"] .ea-generation-status'), null);
  assert.ok(document.querySelector('[data-message-id="message-2"] .ea-generation-status'));
});

test('model_start immediately displays a truthful waiting state; model_end ends only that segment', async () => {
  const events = [model(1, 'model_start', { model: 'stream-model', reasoning_content: 'HIDDEN_PRIVATE_CHAIN' })];
  await renderEvents(events);
  assert.match(body().textContent, /正在等待模型公开回复/);
  assert.doesNotMatch(body().textContent, /HIDDEN_PRIVATE_CHAIN/);
  assert.equal(isMessageStreaming(buildExecutionTimeline(events)[0], 'running'), true);
  events.push(model(2, 'assistant_delta', { delta: '公开文字' }));
  await renderEvents(events);
  assert.equal(messageText(), '公开文字');
  events.push(model(3, 'model_end', { finish_reason: 'tool_calls', duration_ms: 20, reasoning: 'HIDDEN_PRIVATE_CHAIN' }));
  await renderEvents(events);
  assert.equal(document.querySelector('.ea-generation-status'), null);
  assert.equal(document.querySelector('.ea-stream-cursor'), null);
  assert.ok(document.querySelector('[aria-label="停止执行"]'));
  assert.doesNotMatch(body().textContent, /HIDDEN_PRIVATE_CHAIN/);
});

test('tool-only model turns describe generated calls without claiming actual execution', async () => {
  const start = model(1, 'model_start');
  const end = model(2, 'model_end', { finish_reason: 'tool_calls', tool_count: 2, reasoning: 'HIDDEN_PRIVATE_CHAIN' });
  const events = [start, end, tool(3, 'tool_start', { arguments: { command: 'uptime' } })];
  const timeline = buildExecutionTimeline(events);
  assert.equal(timeline[0].toolCount, 2);
  assert.equal(toolPhase(timeline[1], 'running'), 'preparing');
  await renderEvents(events);
  assert.equal(messageText(), '本轮生成 2 项工具调用，具体执行见下方步骤。');
  assert.equal(document.querySelector('.ea-step').dataset.phase, 'preparing');
  assert.equal(document.querySelector('.ea-generation-status,.ea-stream-cursor'), null);
  assert.ok(document.querySelector('[aria-label="停止执行"]'));
  assert.doesNotMatch(body().textContent, /正在执行|执行成功|已执行|HIDDEN_PRIVATE_CHAIN|本轮模型未返回公开文本/);
  for (const tool_count of [-1, 1.5, '2', null, undefined]) {
    assert.equal(buildExecutionTimeline([start, model(2, 'model_end', { tool_count })])[0].toolCount, undefined);
  }
  assert.equal(buildExecutionTimeline([start, model(2, 'model_end', { tool_count: 0 })])[0].toolCount, 0);
  await renderEvents([start, model(2, 'model_end', { finish_reason: 'tool_calls' })]);
  assert.equal(messageText(), '本轮模型未返回公开文本。');
});

test('terminal and interrupted runs never display live generation status or cursor', async () => {
  for (const status of ['completed', 'failed', 'cancelled', 'interrupted']) {
    await renderEvents([model(1, 'model_start'), model(2, 'assistant_delta', { delta: '收到的真实片段' })], makeRun({ status }));
    assert.equal(messageText(), '收到的真实片段');
    assert.equal(document.querySelector('.ea-generation-status,.ea-stream-cursor'), null);
    assert.equal(document.querySelector('[aria-label="停止执行"]'), null);
  }
});

test('tool_start is preparing, approval is pending, and only tool_execution changes to running', async () => {
  const approval = makeApproval({ tool_call_id: 'call-ssh' });
  const start = tool(1, 'tool_start', { arguments: approval.arguments, reason: '恢复服务', risk: 'write' });
  let events = [start];
  await renderEvents(events);
  assert.equal(document.querySelector('.ea-step').dataset.phase, 'preparing');
  assert.match(body().textContent, /尚未执行/);
  assert.doesNotMatch(body().textContent, /正在执行/);
  events = [...events, tool(2, 'tool_output', { stream: 'progress', content: '审批前准备' }), event(3, 'approval', approval)];
  await renderEvents(events, makeRun({ status: 'waiting_approval' }), [approval]);
  assert.equal(document.querySelector('.ea-step').dataset.phase, 'waiting_approval');
  assert.equal(document.querySelectorAll('.ea-step .ea-approval').length, 1);
  await renderEvents([...events, tool(4, 'tool_execution', { phase: 'running' })], makeRun(), [{ ...approval, status: 'approved' }]);
  assert.equal(document.querySelector('.ea-step').dataset.phase, 'running');
  assert.equal(document.querySelectorAll('.ea-approval-actions button').length, 0);
});

test('blocked and refused operations cannot be presented as executed', async () => {
  const events = [tool(1, 'tool_start', { arguments: { command: 'rm -rf /example', reason: '变更测试' }, risk: 'critical' }), tool(2, 'tool_result', { executed: false, outcome: 'blocked', ok: false, output: { error: '用户拒绝审批，操作未执行' }, duration_ms: 0 })];
  const step = buildExecutionTimeline(events)[0];
  assert.equal(toolPhase(step, 'completed'), 'blocked');
  await renderEvents(events, makeRun({ status: 'completed' }));
  assert.equal(document.querySelector('.ea-step').dataset.phase, 'blocked');
  assert.match(body().textContent, /已拦截 · 未执行/);
  assert.match(body().textContent, /用户拒绝审批，操作未执行/);
  assert.doesNotMatch(body().textContent, /执行成功|执行于/);
  assert.equal(toolPhase(buildExecutionTimeline([events[0]], [makeApproval({ status: 'rejected', tool_call_id: 'call-ssh' })])[0], 'running'), 'blocked');
});

test('real stdout/stderr append independently; final output is authoritative without duplication', async () => {
  const one = tool(3, 'tool_output', { stream: 'stdout', content: 'line 1\n' });
  const events = [tool(1, 'tool_start', { arguments: { command: 'printf test', reason: '读取实际输出' } }), tool(2, 'tool_execution'), one, tool(4, 'tool_output', { stream: 'stderr', content: 'warn 1\n' }), tool(5, 'tool_output', { stream: 'stdout', content: 'line 2\n' }), one, tool(6, 'tool_output', { stream: 'stderr', content: 'warn 2\n' })];
  let step = buildExecutionTimeline(events)[0];
  assert.equal(step.stdout, 'line 1\nline 2\n'); assert.equal(step.stderr, 'warn 1\nwarn 2\n');
  await renderEvents(events);
  assert.match(document.querySelector('.ea-tool-results').textContent, /line 1\nline 2/);
  assert.match(document.querySelector('.ea-tool-results').textContent, /warn 1\nwarn 2/);
  events.push(tool(7, 'tool_result', { ok: true, executed: true, outcome: 'succeeded', output: { stdout: 'line 1\nline 2\n', stderr: 'warn 1\nwarn 2\n', exit_code: 0 }, duration_ms: 1650 }));
  await renderEvents(events, makeRun({ status: 'completed' }));
  step = buildExecutionTimeline(events)[0];
  assert.equal(step.stdout, 'line 1\nline 2\n');
  assert.equal(body().textContent.split('line 1').length - 1, 1);
  assert.match(body().textContent, /退出码 0/);
  assert.match(body().textContent, /耗时 1.6 秒|耗时 1.7 秒/);
  assert.equal(document.querySelector('.ea-step .spin'), null);
});

test('tool output reset is channel-local and refresh replays it exactly once', () => {
  const reset = tool(6, 'tool_output', { stream: 'stdout', content: 'new', reset: true });
  const events = [tool(1, 'tool_start'), tool(2, 'tool_execution'), tool(3, 'tool_output', { stream: 'stdout', content: 'old' }), tool(4, 'tool_output', { stream: 'stderr', content: 'error' }), tool(5, 'tool_output', { stream: 'progress', content: '真实进度' }), reset, tool(7, 'tool_output', { stream: 'stdout', content: ' tail' }), reset];
  const step = buildExecutionTimeline(events)[0];
  assert.equal(step.stdout, 'new tail'); assert.equal(step.stderr, 'error'); assert.equal(step.progress, '真实进度');
  assert.deepEqual(step, buildExecutionTimeline([...events, ...events])[0]);
});

test('nonzero exit code is failure even for legacy ok:true; elapsed time starts at actual dispatch', async () => {
  const events = [tool(1, 'tool_start', { arguments: { command: 'false' } }), tool(5, 'tool_execution'), tool(9, 'tool_result', { ok: true, output: { stdout: '', stderr: 'failure', exit_code: 7 } })];
  const step = buildExecutionTimeline(events)[0];
  assert.equal(toolPhase(step, 'completed'), 'failed'); assert.equal(toolExitCode(step), 7); assert.equal(toolDurationMs(step), 4000);
  await renderEvents(events, makeRun({ status: 'completed' }));
  assert.equal(document.querySelector('.ea-step').dataset.phase, 'failed');
  assert.match(body().textContent, /退出码 7/); assert.match(body().textContent, /耗时 4.0 秒/);
});

test('purpose, safe target objects, exact SSH command, brief parameters and result are visible by default', async () => {
  const command = 'LC_ALL=C systemctl status example.service --no-pager | tee /tmp/example-status';
  const events = [tool(1, 'tool_start', { step_index: 3, turn: 2, target: { name: '生产服务器', kind: 'ssh', host: '192.0.2.5' }, reason: '核对服务与退出状态', risk: 'read', arguments: { command, timeout: 45 } }), tool(2, 'tool_execution'), tool(3, 'tool_result', { ok: true, executed: true, output: { stdout: 'active (running)', exit_code: 0 } })];
  await renderEvents(events, makeRun({ status: 'completed' }));
  assert.match(body().textContent, /核对服务与退出状态|生产服务器|192.0.2.5/);
  assert.equal([...document.querySelectorAll('.ea-output pre')].find(node => node.textContent === command)?.closest('details'), null);
  assert.match(body().textContent, /超时（秒）45/);
  assert.ok([...document.querySelectorAll('.ea-output pre')].some(node => node.textContent === 'active (running)' && !node.closest('details')));
  assert.equal(document.querySelector('.ea-item-tool .ea-timeline-mark').textContent, '3');
  assert.equal(buildExecutionTimeline([tool(1, 'tool_start', { target: '<script>unsafe</script>' })])[0].target, undefined);
  assert.equal(buildExecutionTimeline([tool(1, 'tool_start', { target: ['not', 'object'] })])[0].target, undefined);
});

test('Kubernetes actions, resource, namespace and scalar parameters remain visible with long manifests disclosed', async () => {
  const args = { action: 'scale', resource: 'deployments', namespace: 'production', name: 'api', replicas: 4, reason: '恢复期望副本', manifest: { kind: 'Deployment', metadata: { name: 'api' }, spec: { description: 'long'.repeat(400) } } };
  await renderEvents([event(1, 'tool_start', { tool_call_id: 'kube-1', name: 'kubernetes', arguments: args, target: { name: '生产集群', kind: 'kubernetes' }, risk: 'write' }), event(2, 'tool_result', { tool_call_id: 'kube-1', name: 'kubernetes', executed: false, outcome: 'blocked', ok: false, output: { error: '只读模式不允许变更' } })], makeRun({ status: 'completed' }));
  assert.match(document.querySelector('.ea-kube-action').textContent, /scale deployments \/ api/);
  assert.match(document.querySelector('.ea-arguments').textContent, /命名空间production/);
  assert.match(document.querySelector('.ea-arguments').textContent, /副本数4/);
  assert.equal(document.querySelector('.ea-argument-details').open, false);
  assert.match(document.querySelector('.ea-tool-results').textContent, /只读模式不允许变更/);
  assert.equal(document.querySelector('.ea-tool-results').closest('details'), null);
});

test('finished runs do not falsely check off every planned intention', async () => {
  const events = [event(1, 'plan', { steps: ['检查磁盘', '重启服务', '验证恢复'] }), tool(2, 'tool_start', { arguments: { command: 'df -h' } }), tool(3, 'tool_result', { executed: true, ok: true, output: { stdout: '磁盘正常', exit_code: 0 } })];
  await renderEvents(events, makeRun({ status: 'completed', summary: '仅检查磁盘' }));
  assert.deepEqual([...document.querySelectorAll('.ea-plan-number')].map(node => node.textContent), ['1', '2', '3']);
  assert.equal(document.querySelectorAll('.ea-plan .done, .ea-plan .lucide-check, .ea-plan .lucide-check-check').length, 0);
  assert.match(document.querySelector('.ea-plan').textContent, /意图，不是执行结果/);
});

test('recovery notices and run errors are chronological; duplicate errors/summaries are suppressed', async () => {
  const events = [event(1, 'notice', { message: '流式接口不兼容，已切换兼容请求', code: 'fallback' }), model(2, 'model_start'), model(3, 'assistant_delta', { delta: '部分回复' }), event(4, 'error', { message: '模型连接失败' })];
  await renderEvents(events, makeRun({ status: 'failed', error: '模型连接失败', summary: '模型连接失败' }));
  assert.equal(document.querySelectorAll('.ea-run-error').length, 1);
  assert.equal(document.querySelectorAll('.ea-summary').length, 0);
  assert.deepEqual([...document.querySelectorAll('[data-timeline-kind]')].map(node => node.dataset.timelineKind), ['notice', 'message', 'error']);
  await renderEvents(events.slice(0, 3), makeRun({ status: 'failed', error: '另一个真实错误', updated_at: at(10), summary: '最终状态说明' }));
  assert.deepEqual([...document.querySelectorAll('[data-timeline-kind]')].map(node => node.dataset.timelineKind), ['notice', 'message', 'error', 'summary']);
});

test('HTML in replies, output, parameters and notices is escaped and hidden reasoning is excluded', async () => {
  const malicious = '<img src=x onerror="alert(1)"><script>alert(2)</script><iframe src="bad"></iframe>';
  await renderEvents([model(1, 'model_start', { reasoning_content: 'DO_NOT_SHOW_PRIVATE_REASONING' }), model(2, 'assistant_delta', { delta: malicious, reasoning: 'DO_NOT_SHOW_PRIVATE_REASONING' }), event(3, 'notice', { message: malicious }), tool(4, 'tool_start', { arguments: { command: malicious, reason: malicious }, target: { name: malicious, kind: 'ssh' }, risk: 'read' }), tool(5, 'tool_result', { ok: true, output: { stdout: malicious, stderr: '', exit_code: 0, reasoning: undefined } })]);
  assert.equal(document.querySelectorAll('img,script,iframe').length, 0);
  assert.match(body().textContent, /<img src=x onerror=/);
  assert.doesNotMatch(body().textContent, /DO_NOT_SHOW_PRIVATE_REASONING/);
});

test('approval decisions, cancel, copy and reconnect use the existing context actions', async () => {
  const approval = makeApproval();
  const events = [tool(1, 'tool_start', { arguments: approval.arguments, risk: 'write' }), event(3, 'approval', { ...approval, tool_call_id: 'call-ssh' })];
  await renderEvents(events, makeRun({ status: 'waiting_approval' }), [approval], { connectionError: '连接暂时中断，正在自动重连；后台任务不会因此停止。' });
  const step = document.querySelector('.ea-step');
  assert.ok(step.querySelector('.ea-approval'));
  await click([...step.querySelectorAll('button')].find(node => node.textContent.includes('允许执行')));
  await click([...step.querySelectorAll('button')].find(node => node.textContent.includes('拒绝执行')));
  await click(document.querySelector('[aria-label="停止执行"]'));
  await click(step.querySelector('[aria-label="复制内容"]'));
  await click(document.querySelector('.ea-connection-notice button'));
  assert.ok(calls.some(call => call[0] === 'decide' && call[1] === 'approve-1' && call[2] === true));
  assert.ok(calls.some(call => call[0] === 'decide' && call[2] === false));
  assert.ok(calls.some(call => call[0] === 'cancel' && call[1] === 'run-stream'));
  assert.ok(calls.some(call => call[0] === 'watch' && call[1] === 'run-stream'));
  assert.deepEqual(copied, ['systemctl restart example']);
});

test('snapshot-only legacy approval matches its tool by parameters without a duplicate detached panel', async () => {
  const approval = makeApproval();
  const events = [tool(1, 'tool_start', { arguments: approval.arguments, risk: 'write' })];
  const timeline = buildExecutionTimeline(events, [approval]);
  assert.equal(timeline.length, 1);
  assert.equal(timeline[0].approvals[0].id, approval.id);
  await renderEvents(events, makeRun({ status: 'waiting_approval' }), [approval]);
  assert.equal(document.querySelectorAll('.ea-approval').length, 1);
  assert.equal(document.querySelectorAll('.ea-step .ea-approval').length, 1);
});

test('invalid message IDs and non-integer turns are not coerced into correlation keys', () => {
  const timeline = buildExecutionTimeline([event(1, 'model_start', { message_id: { invalid: true }, turn: '1' }), event(2, 'assistant_delta', { message_id: 7, turn: 1, delta: '不应被合并' }), model(3, 'model_start', { turn: 1.5 }), model(4, 'assistant_delta', { turn: '2', delta: '公开文本' })]);
  assert.equal(timeline.length, 1);
  assert.equal(timeline[0].turn, undefined);
  assert.equal(timeline[0].text, '公开文本');
});

test('long output has bounded wrapping and narrow-screen layout rules scoped above global styles', () => {
  assert.match(stylesheet, /\.ea-run-record\.ea-run-record pre\s*\{[^}]*max-width:\s*100%[^}]*max-height:\s*260px[^}]*overflow:\s*auto[^}]*white-space:\s*pre-wrap/s);
  assert.match(stylesheet, /overflow-wrap:\s*anywhere/);
  assert.match(stylesheet, /@media\s*\(max-width:\s*600px\)/);
  assert.match(stylesheet, /grid-template-columns:\s*21px minmax\(0, 1fr\)/);
  assert.match(stylesheet, /\.ea-run-record\.ea-run-record \.ea-arguments\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
});

test('RunLink keeps the existing conversation/run navigation API', async () => {
  await act(async () => root.render(createElement(MemoryRouter, null, createElement(RunLink, { run: makeRun() }))));
  assert.equal(document.querySelector('a').getAttribute('href'), '/chat/chat-stream?run=run-stream');
});
