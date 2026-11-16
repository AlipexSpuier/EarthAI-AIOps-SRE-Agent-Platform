import type { ControlLevel, RunStatus } from '../types';

export const controlLabels: Record<ControlLevel, string> = { observe: '观察模式', approve: '审批模式', autonomous: '自主模式' };
export const controlDescriptions: Record<ControlLevel, string> = { observe: '仅查看与分析，不执行变更操作', approve: '远端变更先审批，再执行', autonomous: '常规变更自动执行，高风险仍需审批' };
export const statusLabels: Record<RunStatus, string> = { queued: '等待开始', running: '执行中', waiting_approval: '等待审批', completed: '已完成', failed: '执行失败', cancelled: '已停止', interrupted: '执行中断' };
export const activeStatuses: RunStatus[] = ['queued', 'running', 'waiting_approval'];
export const isActive = (status: RunStatus) => activeStatuses.includes(status);
export function dateTime(value?: string | null, short = false): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', ...(short ? {} : { year: 'numeric' }) }).format(date);
}
export function relativeTime(value?: string | null): string {
  if (!value) return '尚未执行';
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} 天前`;
  return dateTime(value, true);
}
export function fileSize(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB']; const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3);
  return `${(bytes / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}
export function pretty(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === undefined || value === null) return '';
  return JSON.stringify(value, null, 2);
}
export function initials(name: string): string { return name.trim().slice(0, 2).toUpperCase() || 'EA'; }
export const listFromText = (text: string) => [...new Set(text.split(/[,，\n]/).map(item => item.trim()).filter(Boolean))];
export const colorChoices = ['#087f69', '#3683c7', '#8b67c8', '#d38b36', '#cf6685', '#667889'];
