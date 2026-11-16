import { cloneElement, isValidElement, useEffect, useId, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, FormEvent, ReactElement, ReactNode } from 'react';
import { AlertCircle, ArrowUpRight, Check, ChevronDown, Copy, Inbox, Loader2, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { createPortal } from 'react-dom';
import { errorMessage } from '../lib/api';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { allowedControlLevels, canUseControl, fallbackControl } from '../lib/controlAccess';
import { controlDescriptions, controlLabels, statusLabels } from '../lib/format';
import { Select } from './Select';
import './MultiSelect.css';
import type { ControlLevel, RunStatus } from '../types';

export function Button({ children, variant = 'primary', busy = false, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; busy?: boolean }) {
  return <button className={`button button-${variant} ${className}`} {...props} disabled={props.disabled || busy}>{busy && <Loader2 size={16} className="spin" />}{children}</button>;
}
export function AsyncButton({ action, children, ...props }: Omit<Parameters<typeof Button>[0], 'onClick'> & { action: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false); const notify = useToast();
  return <Button {...props} busy={busy} onClick={() => { setBusy(true); void action().catch(error => notify(errorMessage(error), 'error')).finally(() => setBusy(false)); }}>{children}</Button>;
}
export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-header"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}<span className="heading-dot">.</span></h1><p>{description}</p></div>{action && <div className="header-actions">{action}</div>}</div>;
}
export function EmptyState({ icon: Icon = Inbox, title, description, action, compact = false }: { icon?: LucideIcon; title: string; description: string; action?: ReactNode; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'compact' : ''}`}><div className="empty-orbit"><span /><span /><div className="empty-icon"><Icon size={28} strokeWidth={1.5} /></div></div><h3>{title}</h3><p>{description}</p>{action}</div>;
}
export function Loading({ text = '正在加载工作空间…' }: { text?: string }) { return <div className="loading-state" role="status"><Loader2 size={24} className="spin" /><span>{text}</span></div>; }
export function ErrorState({ message, retry }: { message: string; retry?: () => unknown }) { return <div className="error-state" role="alert"><AlertCircle size={20} /><div><strong>暂时无法获取数据</strong><p>{message}</p></div>{retry && <Button variant="secondary" onClick={() => retry()}><RefreshCw size={15} />重试</Button>}</div>; }
export function Banner({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'success' }) { return <div className={`banner banner-${tone}`}><AlertCircle size={17} /><div>{children}</div></div>; }
export function SearchInput({ value, onChange, placeholder = '搜索…' }: { value: string; onChange: (value: string) => void; placeholder?: string }) { return <label className="search-input"><Search size={17} /><input value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} aria-label={placeholder} />{value && <button className="icon-button" onClick={() => onChange('')} aria-label="清除搜索"><X size={14} /></button>}</label>; }
export function StatusBadge({ status }: { status: RunStatus | 'online' | 'offline' | 'unknown' | 'open' | 'resolved' | 'active' | 'archived' }) {
  const label = status in statusLabels ? statusLabels[status as RunStatus] : ({ online: '连接正常', offline: '连接失败', unknown: '未测试', open: '待处理', resolved: '已解决', active: '进行中', archived: '已归档' } as Record<string, string>)[status];
  return <span className={`status-badge status-${status}`}><i />{label}</span>;
}
export function ControlBadge({ level }: { level: ControlLevel }) { return <span className={`control-badge control-${level}`}>{controlLabels[level]}</span>; }
export function ControlSelect({ value, onChange, name = 'control_level', defaultValue }: { value?: ControlLevel; onChange?: (value: ControlLevel) => void; name?: string; defaultValue?: ControlLevel }) {
  const { user } = useAuth();
  const [internalValue, setInternalValue] = useState(() => fallbackControl(user, defaultValue));
  const preferred = value ?? internalValue;
  const selected = fallbackControl(user, preferred);
  const permissions = allowedControlLevels(user).join(',');
  useEffect(() => {
    setInternalValue(current => fallbackControl(user, current));
  }, [permissions, user?.id]);
  return <div className="control-level-picker"><Select name={name} label="控制等级" value={selected || ''} displayValue={selected ? undefined : '暂无已授权控制等级'} onChange={next => {
    if (!canUseControl(user, next)) return;
    if (value === undefined) setInternalValue(next);
    onChange?.(next);
  }} options={Object.entries(controlLabels).map(([key, label]) => ({ value: key, label, disabled: !canUseControl(user, key), description: canUseControl(user, key) ? controlDescriptions[key as ControlLevel] : `管理员未授权 · ${controlDescriptions[key as ControlLevel]}` }))} />{!selected ? <span className="control-permission-hint" role="status">管理员尚未授权任何控制等级，无法提交执行配置。</span> : preferred && selected !== preferred ? <span className="control-permission-hint" role="status">原控制等级管理员未授权，当前使用{controlLabels[selected]}；保存后才会修改配置。</span> : null}</div>;
}
export function Field({ label, hint, children, required, className = '' }: { label: string; hint?: string; children: ReactNode; required?: boolean; className?: string }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const child = isValidElement(children) ? children as ReactElement<{ id?: string; 'aria-describedby'?: string }> : null;
  return <div ref={ref} className={`field ${className}`}><label className="field-label" htmlFor={child?.props.id || id} onClick={event => { event.preventDefault(); ref.current?.querySelector<HTMLElement>('input:not([type="hidden"]), textarea, button[role="combobox"]')?.focus(); }}>{label}{required && <b> *</b>}</label>{child ? cloneElement(child, { id: child.props.id || id, ...(hint ? { 'aria-describedby': `${id}-hint` } : {}) }) : children}{hint && <span id={`${id}-hint`} className="field-hint">{hint}</span>}</div>;
}
export function Switch({ checked, onChange, label, name, defaultChecked }: { checked?: boolean; onChange?: (checked: boolean) => void; label: string; name?: string; defaultChecked?: boolean }) { return <label className="switch-label"><input className="switch-input" type="checkbox" name={name} checked={checked} defaultChecked={checked === undefined ? defaultChecked : undefined} onChange={event => onChange?.(event.target.checked)} /><span className="switch-track" /><span>{label}</span></label>; }
export function MultiSelect({ label, name, options, selected = [], hint }: { label: string; name: string; options: { id: string; name: string; disabled?: boolean }[]; selected?: string[]; hint?: string }) {
  const [checkedIds, setCheckedIds] = useState(() => new Set(selected));
  const countId = useId();
  const enabledOptions = options.filter(option => !option.disabled);
  const selectedCount = enabledOptions.filter(option => checkedIds.has(option.id)).length;
  const unavailableCount = options.filter(option => option.disabled && checkedIds.has(option.id)).length;
  return <fieldset className="multi-select ea-multi-select" data-multi-select={name} aria-describedby={countId}>
    <legend>{label}</legend>
    <div className="multi-select-toolbar">
      <span id={countId} className="multi-select-count" role="status">已选 {selectedCount} / 可选 {enabledOptions.length}{unavailableCount > 0 && <span className="multi-select-unavailable-count">另有 {unavailableCount} 项已选但不可用</span>}</span>
      <div className="multi-select-actions">
        <button type="button" className="button button-secondary button-small multi-select-all" disabled={!enabledOptions.length || selectedCount === enabledOptions.length} onClick={event => {
          if (event.currentTarget.matches(':disabled')) return;
          setCheckedIds(current => new Set([...current, ...enabledOptions.map(option => option.id)]));
        }}>全选</button>
        <button type="button" className="button button-secondary button-small multi-select-clear" disabled={!selectedCount} onClick={event => {
          if (event.currentTarget.matches(':disabled')) return;
          setCheckedIds(current => {
            const next = new Set(current);
            enabledOptions.forEach(option => next.delete(option.id));
            return next;
          });
        }}>清空</button>
      </div>
    </div>
    {options.length ? <div className="check-options multi-select-list">{options.map(option => <label key={option.id} className="multi-select-option">
      <input type="checkbox" name={name} value={option.id} disabled={option.disabled} checked={checkedIds.has(option.id)} onChange={event => {
        if (event.currentTarget.matches(':disabled')) return;
        const { checked } = event.currentTarget;
        setCheckedIds(current => {
          const next = new Set(current);
          if (checked) next.add(option.id); else next.delete(option.id);
          return next;
        });
      }} />
      <span>{option.name}{option.disabled && <small className="multi-select-unavailable">不可用</small>}</span>
    </label>)}</div> : <p className="muted small">{hint || '暂无可选项，请先创建相应资源。'}</p>}
  </fieldset>;
}
export function Modal({ title, description, children, onClose, wide = false, preventClose = false }: { title: string; description?: string; children: ReactNode; onClose: () => void; wide?: boolean; preventClose?: boolean }) {
  const titleId = useId(); const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose); onCloseRef.current = onClose;
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    const timer = window.setTimeout(() => (ref.current?.querySelector<HTMLElement>('form input:not([type="hidden"]), form textarea, form select') || ref.current?.querySelector<HTMLElement>('input:not([type="hidden"]), textarea, select, button'))?.focus(), 20);
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !preventClose) { event.preventDefault(); onCloseRef.current(); }
      if (event.key !== 'Tab' || !ref.current) return;
      const items = Array.from(ref.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')).filter(element => element.offsetParent !== null);
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', handleKey);
    return () => { window.clearTimeout(timer); document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', handleKey); previouslyFocused?.focus(); };
  }, [preventClose]);
  return createPortal(<div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !preventClose) onClose(); }}><div className={`modal ${wide ? 'modal-wide' : ''}`} ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}><div className="modal-heading"><div><h2 id={titleId}>{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" aria-label="关闭对话框" onClick={onClose} disabled={preventClose}><X size={20} /></button></div>{children}</div></div>, document.body);
}
export function FormDialog({ title, description, onClose, onSubmit, children, submitLabel = '保存', wide = false }: { title: string; description?: string; onClose: () => void; onSubmit: (data: FormData) => Promise<unknown>; children: ReactNode; submitLabel?: string; wide?: boolean }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); setBusy(true); setError(''); try { await onSubmit(data); onClose(); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); } };
  return <Modal title={title} description={description} onClose={onClose} wide={wide} preventClose={busy}><form onSubmit={event => { void submit(event); }}><fieldset className="form-body" disabled={busy}>{children}{error && <div className="inline-error" role="alert"><AlertCircle size={17} />{error}</div>}</fieldset><div className="modal-footer"><span className="small muted">{busy ? '正在安全保存…' : '数据仅对当前账户可见'}</span><Button type="button" variant="secondary" onClick={onClose} disabled={busy}>取消</Button><Button type="submit" busy={busy}><Check size={16} />{submitLabel}</Button></div></form></Modal>;
}
export function useConfirm() {
  const [confirmation, setConfirmation] = useState<{ title: string; description: string; action: () => Promise<unknown> } | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const confirm = (title: string, description: string, action: () => Promise<unknown>) => { setError(''); setConfirmation({ title, description, action }); };
  const dialog = confirmation ? <Modal title={confirmation.title} onClose={() => setConfirmation(null)} preventClose={busy}><div className="confirm-content"><div className="danger-icon"><Trash2 size={25} /></div><p>{confirmation.description}</p>{error && <div className="inline-error">{error}</div>}</div><div className="modal-footer"><Button variant="secondary" disabled={busy} onClick={() => setConfirmation(null)}>取消</Button><Button variant="danger" busy={busy} onClick={() => { setBusy(true); void confirmation.action().then(() => setConfirmation(null)).catch(err => setError(errorMessage(err))).finally(() => setBusy(false)); }}>确认操作</Button></div></Modal> : null;
  return { confirm, dialog };
}
export function CopyButton({ value }: { value: string }) { const notify = useToast(); return <button className="icon-button" aria-label="复制内容" title="复制内容" onClick={() => { void navigator.clipboard.writeText(value).then(() => notify('已复制到剪贴板')).catch(() => notify('当前浏览器不允许访问剪贴板', 'error')); }}><Copy size={14} /></button>; }
export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) { return <div className="section-title"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>; }
export function NewButton({ children, onClick }: { children: ReactNode; onClick: () => void }) { return <Button onClick={onClick}><Plus size={17} />{children}</Button>; }
export function TextLink({ children }: { children: ReactNode }) { return <span className="text-link">{children}<ArrowUpRight size={15} /></span>; }
export function SelectShell({ children }: { children: ReactNode }) { return <div className="select-shell">{children}<ChevronDown size={13} /></div>; }
export const formString = (form: FormData, name: string) => String(form.get(name) || '').trim();
export const formList = (form: FormData, name: string) => form.getAll(name).map(String);
