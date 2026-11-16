import type { Approval, Run, RunEvent, RunStatus } from '../types';

interface TimelinePosition { key: string; eventId: number; createdAt: string }
export interface MessageTimelineItem extends TimelinePosition {
  kind: 'message'; messageId?: string; turn?: number; model?: string;
  text: string; started: boolean; final: boolean; ended: boolean; interrupted: boolean;
  durationMs?: number; finishReason?: string; toolCount?: number;
}
export interface ToolTimelineItem extends TimelinePosition {
  kind: 'tool'; callId?: string; name: string; stepIndex: number; turn?: number;
  arguments: unknown; parameters: Record<string, unknown>; reason: string; risk: string;
  target?: { name: string; kind: string; host: string };
  start?: RunEvent; execution?: RunEvent; result?: RunEvent;
  stdout: string; stderr: string; progress: string;
  streams: Set<'stdout' | 'stderr' | 'progress'>; approvals: Approval[];
}
interface PlanTimelineItem extends TimelinePosition { kind: 'plan'; steps: string[]; turn?: number }
interface NoticeTimelineItem extends TimelinePosition { kind: 'notice'; text: string; code?: string }
interface ErrorTimelineItem extends TimelinePosition { kind: 'error'; text: string }
interface SummaryTimelineItem extends TimelinePosition { kind: 'summary'; text: string }
export type ExecutionTimelineItem = MessageTimelineItem | ToolTimelineItem | PlanTimelineItem | NoticeTimelineItem | ErrorTimelineItem | SummaryTimelineItem;
export type ToolPhase = 'preparing' | 'waiting_approval' | 'running' | 'succeeded' | 'failed' | 'blocked' | 'interrupted' | 'not_executed';

export function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
const textValue = (value: unknown): string => typeof value === 'string' ? value : '';
const integerValue = (value: unknown): number | undefined => typeof value === 'number' && Number.isInteger(value) ? value : undefined;
const durationValue = (value: unknown): number | undefined => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
const activeStatus = (status: RunStatus) => ['queued', 'running', 'waiting_approval'].includes(status);
const pendingApproval = (approval: Approval) => ['pending', 'waiting', 'requested'].includes(approval.status || 'pending');
function argumentsValue(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try { return objectValue(JSON.parse(value)) || {}; } catch { return {}; }
  }
  return objectValue(value) || {};
}
function position(event: RunEvent, key: string): TimelinePosition { return { key, eventId: event.id, createdAt: event.created_at }; }

export function toolExitCode(step: ToolTimelineItem): number | undefined {
  const output = objectValue(step.result?.data.output);
  const code = output?.exit_code ?? output?.exitcode ?? step.result?.data.exit_code;
  return typeof code === 'number' && Number.isFinite(code) ? code : undefined;
}
export function toolDurationMs(step: ToolTimelineItem): number | undefined {
  const supplied = durationValue(step.result?.data.duration_ms);
  if (supplied !== undefined) return supplied;
  if (!step.execution || !step.result) return undefined;
  const elapsed = Date.parse(step.result.created_at) - Date.parse(step.execution.created_at);
  return Number.isFinite(elapsed) && elapsed >= 0 ? elapsed : undefined;
}
export function toolPhase(step: ToolTimelineItem, status: RunStatus): ToolPhase {
  if (step.result) {
    const { executed, outcome, ok, output } = step.result.data;
    if (step.result.data.reused === true || outcome === 'reused') return 'succeeded';
    if (executed === false || outcome === 'blocked') return 'blocked';
    const code = toolExitCode(step);
    return ok === false || outcome === 'failed' || !!objectValue(output)?.error || (code !== undefined && code !== 0) ? 'failed' : 'succeeded';
  }
  if (!step.execution && step.approvals.some(approval => ['denied', 'rejected'].includes(approval.status))) return 'blocked';
  if (step.execution) return activeStatus(status) ? 'running' : 'interrupted';
  if (!activeStatus(status)) return 'not_executed';
  return step.approvals.some(pendingApproval) ? 'waiting_approval' : 'preparing';
}
export function isMessageStreaming(message: MessageTimelineItem, status: RunStatus): boolean {
  return activeStatus(status) && !message.ended && !message.final && !message.interrupted;
}

export function buildExecutionTimeline(events: readonly RunEvent[], approvals: readonly Approval[] = [], run?: Run): ExecutionTimelineItem[] {
  const unique = new Map<number, RunEvent>();
  for (const event of events) if (Number.isFinite(event.id)) unique.set(event.id, event);
  // Persisted event IDs are the stream cursor and authoritative order, including identical timestamps.
  const ordered = [...unique.values()].sort((a, b) => a.id - b.id);
  const items: ExecutionTimelineItem[] = [];
  const messages = new Map<string, MessageTimelineItem>();
  const tools = new Map<string, ToolTimelineItem>();
  const toolItems: ToolTimelineItem[] = [];
  const approvalEvents = new Map<string, RunEvent>();
  const approvalRecords = new Map(approvals.map(approval => [approval.id, { ...approval }]));
  const sequenceAt = (createdAt: string) => {
    const time = Date.parse(createdAt);
    const nextIndex = ordered.findIndex(event => Date.parse(event.created_at) > time);
    if (nextIndex < 0) return (ordered.at(-1)?.id || 0) + 0.5;
    const next = ordered[nextIndex].id;
    return ((ordered[nextIndex - 1]?.id ?? next - 1) + next) / 2;
  };
  const getMessage = (event: RunEvent, id: string): MessageTimelineItem => {
    let message = messages.get(id);
    if (!message) {
      message = { ...position(event, `message:${id}`), kind: 'message', messageId: id, text: '', started: false, final: false, ended: false, interrupted: false };
      messages.set(id, message); items.push(message);
    }
    const turn = integerValue(event.data.turn);
    if (turn !== undefined) message.turn = turn;
    return message;
  };
  const createTool = (event: RunEvent, callId?: string): ToolTimelineItem => {
    const step: ToolTimelineItem = {
      ...position(event, callId ? `tool:${callId}` : `tool-event:${event.id}`), kind: 'tool', callId,
      name: textValue(event.data.name) || textValue(event.data.tool_name) || '未知工具', stepIndex: 0,
      arguments: undefined, parameters: {}, reason: '', risk: '', stdout: '', stderr: '', progress: '', streams: new Set(), approvals: [],
    };
    if (callId) tools.set(callId, step);
    toolItems.push(step); items.push(step); return step;
  };
  for (const event of ordered) {
    const data = event.data;
    if (['model_start', 'assistant_delta', 'assistant', 'model_end'].includes(event.type)) {
      const id = textValue(data.message_id);
      if (!id) {
        if (event.type === 'assistant' && textValue(data.content)) {
          items.push({ ...position(event, `legacy-message:${event.id}`), kind: 'message', text: textValue(data.content), turn: integerValue(data.turn), started: false, final: true, ended: true, interrupted: data.status === 'interrupted' });
        }
        continue;
      }
      const message = getMessage(event, id);
      if (event.type === 'model_start') {
        if (!message.started) Object.assign(message, position(event, message.key));
        message.started = true; message.model = textValue(data.model) || undefined;
      } else if (event.type === 'assistant_delta') {
        if (!message.final && typeof data.delta === 'string') message.text = data.reset === true ? data.delta : message.text + data.delta;
      } else if (event.type === 'assistant') {
        if (typeof data.content === 'string') message.text = data.content;
        message.final = true; message.interrupted = data.status === 'interrupted';
      } else {
        message.ended = true; message.durationMs = durationValue(data.duration_ms);
        message.finishReason = textValue(data.finish_reason) || undefined;
        const toolCount = integerValue(data.tool_count);
        if (toolCount !== undefined && toolCount >= 0) message.toolCount = toolCount;
      }
    } else if (['tool_start', 'tool_execution', 'tool_output', 'tool_result'].includes(event.type)) {
      const callId = textValue(data.tool_call_id) || undefined;
      const name = textValue(data.name);
      let step = callId ? tools.get(callId) : event.type === 'tool_start' ? undefined : [...toolItems].reverse().find(item => !item.callId && !item.result && (!name || item.name === name));
      step ||= createTool(event, callId);
      if (name) step.name = name;
      const stepIndex = integerValue(data.step_index);
      if (stepIndex !== undefined && stepIndex > 0) step.stepIndex = stepIndex;
      const turn = integerValue(data.turn);
      if (turn !== undefined) step.turn = turn;
      if (data.arguments !== undefined) { step.arguments = data.arguments; step.parameters = argumentsValue(data.arguments); }
      if (typeof data.reason === 'string') step.reason = data.reason;
      if (typeof data.risk === 'string') step.risk = data.risk;
      const target = objectValue(data.target);
      if (target) step.target = { name: textValue(target.name), kind: textValue(target.kind), host: textValue(target.host) };
      if (event.type === 'tool_start') {
        if (!step.start) Object.assign(step, position(event, step.key));
        step.start = event;
      } else if (event.type === 'tool_execution') {
        step.execution ||= event;
      } else if (event.type === 'tool_output') {
        const stream = data.stream;
        if (['stdout', 'stderr', 'progress'].includes(textValue(stream)) && typeof data.content === 'string' && !step.result) {
          const channel = stream as 'stdout' | 'stderr' | 'progress';
          step[channel] = data.reset === true ? data.content : step[channel] + data.content;
          step.streams.add(channel);
        }
      } else {
        step.result = event;
        const output = objectValue(data.output);
        for (const stream of ['stdout', 'stderr'] as const) {
          if (typeof output?.[stream] === 'string') { step[stream] = output[stream]; step.streams.add(stream); }
        }
      }
      step.reason ||= textValue(step.parameters.reason);
    } else if (event.type === 'plan') {
      const steps = Array.isArray(data.steps) ? data.steps.filter((step): step is string => typeof step === 'string') : [];
      if (steps.length) items.push({ ...position(event, `plan:${event.id}`), kind: 'plan', steps, turn: integerValue(data.turn) });
    } else if (event.type === 'notice') {
      const text = textValue(data.message);
      if (text) items.push({ ...position(event, `notice:${event.id}`), kind: 'notice', text, code: textValue(data.code) || undefined });
    } else if (event.type === 'error') {
      items.push({ ...position(event, `error:${event.id}`), kind: 'error', text: textValue(data.message) || textValue(data.error) || textValue(data.content) || '执行遇到错误' });
    } else if (event.type === 'approval') {
      const id = textValue(data.id);
      if (!id) continue;
      approvalEvents.set(id, event);
      const saved = approvalRecords.get(id);
      approvalRecords.set(id, {
        id, run_id: event.run_id, tool_name: textValue(data.tool_name) || textValue(data.name), arguments: data.arguments,
        risk: textValue(data.risk), status: textValue(data.status) || 'pending', created_at: textValue(data.created_at) || event.created_at,
        ...saved, tool_call_id: saved?.tool_call_id || textValue(data.tool_call_id) || undefined,
      });
    }
  }
  for (const approval of [...approvalRecords.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))) {
    const event = approvalEvents.get(approval.id);
    const at = event?.id ?? sequenceAt(approval.created_at);
    let step = approval.tool_call_id ? tools.get(approval.tool_call_id) : undefined;
    if (!step && !approval.tool_call_id) {
      const candidates = toolItems.filter(item => item.eventId <= at && item.name === approval.tool_name && !item.approvals.length);
      step = [...candidates].reverse().find(item => JSON.stringify(item.arguments) === JSON.stringify(approval.arguments)) || candidates.at(-1);
    }
    if (!step) step = createTool({ id: at, run_id: approval.run_id, type: 'approval', data: { tool_name: approval.tool_name }, created_at: approval.created_at }, approval.tool_call_id);
    if (step.arguments === undefined) { step.arguments = approval.arguments; step.parameters = argumentsValue(approval.arguments); }
    step.risk ||= approval.risk; step.reason ||= textValue(step.parameters.reason);
    step.approvals.push(approval);
  }
  if (run?.error && !items.some(item => item.kind === 'error' && item.text.trim() === run.error?.trim())) {
    items.push({ kind: 'error', key: 'run-error', eventId: sequenceAt(run.updated_at), createdAt: run.updated_at, text: run.error });
  }
  const summary = run?.summary?.trim();
  const comparable = (value: string) => value.trim().replace(/\r\n/g, '\n');
  if (summary && run && !activeStatus(run.status) && !items.some(item => ['message', 'error', 'summary'].includes(item.kind) && 'text' in item && comparable(item.text) === comparable(summary))) {
    items.push({ kind: 'summary', key: 'run-summary', eventId: sequenceAt(run.updated_at), createdAt: run.updated_at, text: run.summary! });
  }
  const timeline = items.sort((a, b) => a.eventId - b.eventId);
  let ordinal = 0;
  for (const item of timeline) if (item.kind === 'tool') { ordinal = Math.max(ordinal + 1, item.stepIndex); item.stepIndex ||= ordinal; }
  return timeline;
}
