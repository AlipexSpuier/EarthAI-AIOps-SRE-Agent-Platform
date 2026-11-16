import { isActive } from './format';
import type { Approval, Run, RunEvent, RunStatus } from '../types';

export function mergeEvents(a: RunEvent[], b: RunEvent[]): RunEvent[] {
  return [...new Map([...a, ...b].map(event => [event.id, event])).values()].sort((x, y) => x.id - y.id);
}

export function applyRunEvents(run: Run, events: RunEvent[]): Run {
  const result = { ...run };
  const authoritativeTime = Date.parse(run.updated_at);
  for (const event of events) {
    const eventTime = Date.parse(event.created_at);
    const newer = eventTime >= authoritativeTime;
    if (newer && isActive(result.status) && (event.type === 'status' || event.type === 'done') && typeof event.data.status === 'string') {
      result.status = event.data.status as RunStatus;
      result.updated_at = event.created_at;
    }
    if (event.type === 'done' && typeof event.data.summary === 'string' && (newer || !result.summary)) result.summary = event.data.summary;
    if (event.type === 'error' && !result.error) result.error = String(event.data.message || event.data.error || event.data.content || '执行出错');
  }
  return result;
}

export function mergeApprovals(existing: Approval[], fetched: Approval[], events: RunEvent[], runStatus: RunStatus): Approval[] {
  const map = new Map(existing.map(approval => [approval.id, approval]));
  for (const approval of fetched) {
    const current = map.get(approval.id);
    if (!current || current.status === 'pending' || approval.status !== 'pending') map.set(approval.id, approval);
  }
  for (const event of events) {
    if (event.type !== 'approval' || typeof event.data.id !== 'string') continue;
    const approval = event.data as unknown as Approval;
    const current = map.get(approval.id);
    if (!current || current.status === 'pending' || approval.status !== 'pending') map.set(approval.id, approval);
  }
  return [...map.values()].map(approval => !isActive(runStatus) && approval.status === 'pending' ? { ...approval, status: 'expired' } : approval);
}
