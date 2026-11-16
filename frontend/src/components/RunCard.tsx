import { useState } from 'react';
import { Activity, ArrowRight, Check, CheckCircle2, ChevronDown, ChevronRight, Circle, CircleAlert, ClipboardList, Clock3, Info, Loader2, LockKeyhole, MessageSquare, Radio, ShieldCheck, Square, Terminal, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Approval, Run } from '../types';
import { useExecutions } from '../context/ExecutionContext';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { canUseControl } from '../lib/controlAccess';
import { errorMessage } from '../lib/api';
import { controlLabels, dateTime, isActive, pretty, relativeTime } from '../lib/format';
import { buildExecutionTimeline, isMessageStreaming, objectValue, toolDurationMs, toolExitCode, toolPhase } from '../lib/executionTimeline';
import type { ExecutionTimelineItem, MessageTimelineItem, ToolPhase, ToolTimelineItem } from '../lib/executionTimeline';
import { AsyncButton, Button, ControlBadge, CopyButton, Modal, StatusBadge } from './ui';
import { Content } from './Content';
import './RunCard.css';

export function RunLink({ run }: { run: Run }) { return <Link className="run-list-item" to={`/chat/${run.conversation_id}?run=${run.id}`}><span className={`run-list-icon ${isActive(run.status) ? 'is-active' : ''}`}>{isActive(run.status) ? <Activity size={18} /> : <Terminal size={18} />}</span><div className="run-list-main"><strong>{run.goal || '运维任务'}</strong><span>{run.model || '模型未配置'}<i>·</i>{relativeTime(run.created_at)}</span></div><StatusBadge status={run.status} /><ArrowRight size={16} className="muted" /></Link>; }

function eventTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date);
}
function durationText(value: number): string { return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} 秒`; }
function EventTime({ value }: { value: string }) { return <time dateTime={value} title={dateTime(value)}>{eventTime(value)}</time>; }

function ApprovalCard({ approval, actionable, level }: { approval: Approval; actionable: boolean; level: Run['control_level'] }) {
  const { user } = useAuth();
  const canApprove = user?.role !== 'admin' && canUseControl(user, level);
  const permissionReason = user?.role === 'admin' ? '管理员账户不能批准本地执行。' : `管理员未授权${controlLabels[level]}，你仍可拒绝或停止任务。`;
  const { decide } = useExecutions(); const notify = useToast(); const [busy, setBusy] = useState(false);
  const pending = ['pending', 'waiting', 'requested'].includes(approval.status || 'pending');
  const waiting = pending && actionable;
  const label = waiting ? '等待审批 · 尚未执行' : pending ? '审批已结束' : ({ approved: '已允许', rejected: '已拒绝', denied: '已拒绝', expired: '已失效' } as Record<string, string>)[approval.status] || approval.status;
  const choose = async (approved: boolean) => { if (approved && !canApprove) { notify(permissionReason, 'error'); return; } setBusy(true); try { await decide(approval, approved); notify(approved ? '操作已授权，智能体将继续执行' : '已拒绝本次操作'); } catch (err) { notify(errorMessage(err), 'error'); } finally { setBusy(false); } };
  return <section className={`ea-approval ${waiting ? 'is-pending' : ''}`} aria-label="操作审批"><div className="ea-approval-heading"><ShieldCheck size={19} /><div><strong>{waiting ? '请确认这一步操作' : '操作审批记录'}</strong><span>{label}</span></div></div>{waiting && <><p>确认上方目标、命令与风险后再授权。允许后才会实际执行。</p>{!canApprove && <p className="control-permission-hint" role="status">{permissionReason}</p>}<div className="ea-approval-actions"><Button variant="secondary" disabled={busy} onClick={() => { void choose(false); }}><X size={15} />拒绝执行</Button><Button busy={busy} disabled={!canApprove} title={canApprove ? undefined : permissionReason} onClick={() => { void choose(true); }}><Check size={15} />允许执行</Button></div></>}</section>;
}

const phaseLabels: Record<ToolPhase, string> = { preparing: '准备中 · 尚未执行', waiting_approval: '等待审批 · 尚未执行', running: '正在执行', succeeded: '执行成功', failed: '执行失败', blocked: '已拦截 · 未执行', interrupted: '执行已中断 · 结果未确认', not_executed: '未执行 / 无执行记录' };
const toolLabels: Record<string, string> = { ssh_exec: 'SSH 远程命令', kubernetes: 'Kubernetes 操作', server_info: '读取目标信息', knowledge_search: '检索知识库', list_files: '列出个人文件', read_file: '读取文件', write_report: '保存报告', plan: '发布行动计划' };
const argumentLabels: Record<string, string> = { action: '操作', resource: '资源', namespace: '命名空间', name: '名称', container: '容器', replicas: '副本数', tail_lines: '日志行数', timeout: '超时（秒）', query: '检索内容', file_id: '文件 ID', continue_token: '分页游标' };
function OutputBlock({ title, text, tone = '' }: { title: string; text: string; tone?: string }) {
  return <section className={`ea-output ${tone}`}><div className="ea-block-heading"><span>{title}</span><CopyButton value={text} /></div><pre tabIndex={0}>{text || '（无文本输出）'}</pre></section>;
}
function ToolCard({ step, run }: { step: ToolTimelineItem; run: Run }) {
  const phase = toolPhase(step, run.status);
  const duration = toolDurationMs(step); const exitCode = toolExitCode(step);
  const risk = ({ read: '只读', write: '变更', critical: '高风险' } as Record<string, string>)[step.risk] || step.risk || '未标注';
  const parameters = step.parameters;
  const command = typeof parameters.command === 'string' ? parameters.command : '';
  const scalarArguments = Object.entries(parameters).filter(([key, value]) => !['command', 'reason'].includes(key) && ['string', 'number', 'boolean'].includes(typeof value));
  const shortArguments = scalarArguments.slice(0, 8);
  const argsText = pretty(step.arguments);
  const fullArguments = argsText.length > 650 || Object.values(parameters).some(value => typeof value === 'object' && value !== null) || scalarArguments.some(([, value]) => String(value).length > 180) || scalarArguments.length > 8;
  const target = step.target && [step.target.name, step.target.host, step.target.kind === 'ssh' ? 'SSH' : step.target.kind === 'kubernetes' ? 'Kubernetes' : step.target.kind].filter(Boolean).join(' · ');
  const resultObject = objectValue(step.result?.data.output);
  const remainingResult = resultObject ? Object.fromEntries(Object.entries(resultObject).filter(([key]) => !['stdout', 'stderr', 'exit_code', 'exitcode'].includes(key))) : undefined;
  const resultText = resultObject ? Object.keys(remainingResult!).length ? pretty(remainingResult) : '' : pretty(step.result?.data.output);
  const hasOutput = step.streams.size > 0 || !!resultText;
  const phaseIcon = phase === 'running' ? <Loader2 size={15} className="spin" /> : phase === 'succeeded' ? <CheckCircle2 size={15} /> : ['failed', 'blocked', 'interrupted'].includes(phase) ? <CircleAlert size={15} /> : <Clock3 size={15} />;
  return <article className={`ea-step ea-phase-${phase}`} data-phase={phase} data-call-id={step.callId}>
    <header className="ea-step-heading"><div><strong>{toolLabels[step.name] || step.name}</strong><code>{step.name}</code></div><span className="ea-phase">{phaseIcon}{step.result?.data.reused === true ? '此前成功 · 复用结果' : phaseLabels[phase]}</span></header>
    <p className="ea-step-purpose"><span>目的</span>{step.reason || '此工具未提供操作目的，请结合下方参数核实范围。'}</p>
    <dl className="ea-step-facts"><div><dt>目标</dt><dd>{target || '未提供目标信息'}</dd></div><div><dt>风险</dt><dd className={['write', 'critical'].includes(step.risk) ? 'ea-risk-warning' : ''}>{risk}</dd></div></dl>
    {command && <OutputBlock title="准确 SSH 命令" text={command} />}
    {step.name === 'kubernetes' && <div className="ea-kube-action"><Terminal size={14} /><span>Kubernetes API：<code>{String(parameters.action || '未指定操作')} {String(parameters.resource || '未指定资源')}{typeof parameters.name === 'string' && parameters.name ? ` / ${parameters.name}` : ''}</code></span></div>}
    {shortArguments.length > 0 && <dl className="ea-arguments" aria-label="调用参数概要">{shortArguments.map(([key, value]) => <div key={key}><dt>{argumentLabels[key] || key}</dt><dd title={String(value)}>{String(value).length > 180 ? `${String(value).slice(0, 180)}…` : String(value)}</dd></div>)}</dl>}
    {step.name === 'kubernetes' && !parameters.namespace && <p className="ea-parameter-note">命名空间：未显式指定，以集群配置为准。</p>}
    {argsText && (fullArguments ? <details className="ea-argument-details"><summary>完整调用参数{scalarArguments.length > 8 ? `（另有 ${scalarArguments.length - 8} 项）` : ''}</summary><OutputBlock title="参数原文" text={argsText} /></details> : !command && !shortArguments.length ? <OutputBlock title="调用参数" text={argsText} /> : null)}
    <div className="ea-step-timing"><span>准备于 <EventTime value={step.createdAt} /></span>{step.execution && <span>执行于 <EventTime value={step.execution.created_at} /></span>}{step.result && <span>返回于 <EventTime value={step.result.created_at} /></span>}{duration !== undefined && <span>耗时 {durationText(duration)}</span>}{exitCode !== undefined && <span className={exitCode !== 0 ? 'ea-exit-error' : ''}>退出码 {exitCode}</span>}</div>
    {step.approvals.map(approval => <ApprovalCard key={approval.id} approval={approval} level={run.control_level} actionable={isActive(run.status) && !step.execution && !step.result} />)}
    <div className="ea-tool-results" aria-live={phase === 'running' ? 'polite' : 'off'}><div className="ea-result-label">{step.result ? phase === 'blocked' ? '拦截原因 · 操作未执行' : '实际执行结果' : '实时输出'}</div>{(['stdout', 'stderr', 'progress'] as const).filter(stream => step.streams.has(stream)).map(stream => <OutputBlock key={stream} title={stream === 'stdout' ? '标准输出 · stdout' : stream === 'stderr' ? '标准错误 · stderr' : '执行进度'} text={step[stream]} tone={stream === 'stderr' && step.stderr ? 'is-stderr' : ''} />)}{resultText && <OutputBlock title={phase === 'blocked' ? '拦截详情' : '工具返回'} text={resultText} />}{!hasOutput && <p className="ea-output-placeholder">{step.result ? phase === 'blocked' ? '此操作未执行。' : '工具已返回，未包含文本输出。' : phase === 'running' ? '已开始实际执行，等待工具返回输出…' : phase === 'interrupted' ? '未收到完整结果，请核实目标状态后再操作。' : '尚无实际执行输出。'}</p>}</div>
  </article>;
}
function ModelMessage({ message, run }: { message: MessageTimelineItem; run: Run }) {
  const streaming = isMessageStreaming(message, run.status);
  return <section className={`ea-message ${streaming ? 'is-streaming' : ''}`} data-message-id={message.messageId}>
    <header className="ea-entry-heading"><strong><MessageSquare size={14} />模型公开回复</strong><div>{message.turn !== undefined && <span>第 {message.turn} 轮</span>}<EventTime value={message.createdAt} /></div></header>
    {streaming && <div className="ea-generation-status" role="status"><Loader2 size={13} className="spin" />{message.text ? '正在接收公开回复' : '正在等待模型公开回复'}</div>}
    <div className="ea-message-text" aria-live={streaming ? 'polite' : 'off'} aria-atomic="false">{message.text ? <Content text={message.text} /> : !streaming && <p className="ea-output-placeholder">{message.interrupted || !message.ended ? '本段回复已结束，未收到公开文本。' : message.toolCount !== undefined && message.toolCount > 0 ? `本轮生成 ${message.toolCount} 项工具调用，具体执行见下方步骤。` : '本轮模型未返回公开文本。'}</p>}{streaming && message.text && <span className="ea-stream-cursor" aria-hidden="true" />}</div>
    {(message.interrupted || message.durationMs !== undefined) && <div className="ea-message-meta">{message.interrupted && <span>本段回复已中断</span>}{message.durationMs !== undefined && <span>生成耗时 {durationText(message.durationMs)}</span>}</div>}
  </section>;
}
function TimelineEntry({ item, run }: { item: ExecutionTimelineItem; run: Run }) {
  if (item.kind === 'tool') return <ToolCard step={item} run={run} />;
  if (item.kind === 'message') return <ModelMessage message={item} run={run} />;
  if (item.kind === 'plan') return <section className="ea-plan"><header className="ea-entry-heading"><strong><ClipboardList size={15} />行动计划<span className="ea-intent-label">意图，不是执行结果</span></strong><EventTime value={item.createdAt} /></header><ol>{item.steps.map((step, index) => <li key={index}><span className="ea-plan-number">{index + 1}</span><span>{step}</span></li>)}</ol><p>计划可能随证据调整，完成情况以实际工具记录为准。</p></section>;
  if (item.kind === 'notice') return <div className="ea-notice" role="status"><Info size={16} /><div><div className="ea-entry-heading"><strong>运行提示</strong><EventTime value={item.createdAt} /></div><p>{item.text}</p></div></div>;
  if (item.kind === 'error') return <div className="ea-run-error" role="alert"><CircleAlert size={17} /><div><div className="ea-entry-heading"><strong>运行错误</strong><EventTime value={item.createdAt} /></div><p>{item.text}</p></div></div>;
  return <section className="ea-summary"><header className="ea-entry-heading"><strong><ClipboardList size={15} />运行摘要</strong><EventTime value={item.createdAt} /></header><Content text={item.text} /></section>;
}

export function RunCard({ run, initiallyExpanded = true }: { run: Run; initiallyExpanded?: boolean }) {
  const { runs, watch, cancel } = useExecutions(); const [expanded, setExpanded] = useState(initiallyExpanded); const [detail, setDetail] = useState(false);
  const snapshot = runs[run.id]; const actual = snapshot?.run || run;
  const timeline = buildExecutionTimeline(snapshot?.events || [], snapshot?.approvals || [], actual);
  const tools = timeline.filter(item => item.kind === 'tool');
  const body = <div className="run-card-body ea-run-body">
    {snapshot?.connectionError && <div className="ea-connection-notice" role="status"><Radio size={15} /><span>{snapshot.connectionError}</span><button onClick={() => { void watch(run.id).catch(() => undefined); }}>重新同步</button></div>}
    {timeline.length > 0 ? <><div className="ea-timeline-caption"><span><span className="ea-caption-dot" />按发生顺序记录</span><span>仅展示公开回复与真实工具事件</span></div><ol className="ea-timeline" aria-label="按时间排序的执行记录">{timeline.map(item => <li key={item.key} className={`ea-timeline-item ea-item-${item.kind}`} data-timeline-kind={item.kind}><span className="ea-timeline-mark" aria-label={item.kind === 'tool' ? `工具步骤 ${item.stepIndex}` : undefined}>{item.kind === 'tool' ? item.stepIndex : item.kind === 'message' ? <MessageSquare size={12} /> : item.kind === 'plan' ? <ClipboardList size={12} /> : <Circle size={9} />}</span><div className="ea-timeline-content"><TimelineEntry item={item} run={actual} /></div></li>)}</ol></> : <div className="ea-run-pending">{isActive(actual.status) ? <><Loader2 size={18} className="spin" />正在准备执行，等待模型开始公开回复…</> : <><Circle size={16} />暂无执行事件</>}</div>}
    <footer className="ea-run-footer"><span><Clock3 size={12} />{dateTime(actual.created_at, true)}</span><span>{actual.step_count || 0} 轮模型交互 · {tools.length} 个工具步骤</span><span>{controlLabels[actual.control_level]}</span></footer>
  </div>;
  return <><article className={`run-card ea-run-record run-${actual.status}`}><div className="run-card-header"><button className="run-toggle" onClick={() => { setExpanded(!expanded); if (!snapshot) void watch(run.id).catch(() => undefined); }} aria-expanded={expanded}><span className="run-emblem">{isActive(actual.status) ? <Activity size={18} /> : <Terminal size={18} />}</span><div><strong>智能体执行记录</strong><span>{actual.model || '尚未选择模型'}</span></div>{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button><div className="run-header-actions"><StatusBadge status={actual.status} /><button className="text-button" onClick={() => { setDetail(true); void watch(run.id).catch(() => undefined); }}>详情</button>{isActive(actual.status) && <AsyncButton variant="ghost" className="button-small" action={() => cancel(run.id)} aria-label="停止执行"><Square size={13} />停止</AsyncButton>}</div></div>{expanded && !detail && body}</article>{detail && <Modal title="运行详情" description={`运行 ID：${run.id}`} onClose={() => setDetail(false)} wide><div className="ea-run-record ea-run-detail"><div className="ea-detail-meta"><StatusBadge status={actual.status} /><ControlBadge level={actual.control_level} /><span><LockKeyhole size={13} />审计记录已持久化</span></div><div className="ea-detail-goal">{actual.goal}</div>{body}</div></Modal>}</>;
}
