import { useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Activity, ArrowDown, ArrowUp, ArrowUpDown, Bell, Blocks, BookOpen, Bot, Check, CheckCircle2, Download, Eye, FileJson, FileText, FolderKanban, Globe, GripVertical, KeyRound, Palette, Pencil, Plus, RefreshCw, RotateCcw, Save, Search, Server as ServerIcon, ShieldCheck, Sparkles, Trash2, Upload, Users, X, CalendarClock } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Select } from '../components/Select';
import { Content } from '../components/Content';
import { AsyncButton, Banner, Button, ControlSelect, EmptyState, ErrorState, Field, Loading, Modal, MultiSelect, NewButton, PageHeader, SearchInput, SectionTitle, StatusBadge, Switch, formList, formString, useConfirm } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api, errorMessage } from '../lib/api';
import { controlDescriptions, controlLabels, dateTime, initials, listFromText, pretty } from '../lib/format';
import { dataChanged, useResource } from '../lib/hooks';
import type { Agent, Alert, Audit, ControlLevel, Knowledge, Project, Provider, Server, Skill, User } from '../types';
import './Agents.css';
import './AdminPages.css';

type ResourceKind = 'agents' | 'skills' | 'knowledge' | 'projects' | 'servers' | 'providers' | 'schedules';
const resourceInfo: Record<ResourceKind, { name: string; singular: string; icon: LucideIcon; note: string }> = {
  agents: { name: '默认智能体', singular: '智能体', icon: Bot, note: '统一维护本地助手的能力边界，或配置远程智能体的访问入口。' },
  skills: { name: '默认技能', singular: '技能', icon: Blocks, note: '将经过审阅的专业指令和操作规范同步给每一位用户。' },
  knowledge: { name: '默认知识库', singular: '知识库', icon: BookOpen, note: '维护知识库及真实文档，让所有用户使用同一份可靠业务知识。' },
  projects: { name: '默认项目', singular: '项目', icon: FolderKanban, note: '以业务组织默认服务器、知识库和技能，提供一致的项目上下文。' },
  servers: { name: '默认服务器', singular: '服务器', icon: ServerIcon, note: '集中维护 SSH 与 Kubernetes 连接、凭据及主机信任策略。' },
  providers: { name: '默认模型供应商', singular: '供应商', icon: Sparkles, note: '统一管理真实模型端点、可选模型、默认模型和启停状态。' },
  schedules: { name: '默认定时任务', singular: '定时任务', icon: CalendarClock, note: '为所有普通用户配置可审阅的自动化任务，新建任务默认不启用。' },
};
const resourceKinds = Object.keys(resourceInfo) as ResourceKind[];
const syncMessage = '这里维护的是系统默认模板。新用户自动继承；后续更新会同步仍跟随模板的副本，已保存的个人定制不会被覆盖，个人删除的副本不会重新出现。普通用户可修改自己的默认本地智能体、技能和知识库；默认远程智能体及其他默认资源只读。个人编辑不影响模板和其他用户。';
const usageMethodMessage = '本地智能体执行、技能注入、知识库检索命中，在同一任务内对同一资源只计一次；远程智能体每次打开计一次。不代表任务完成或成功；浏览资源页面与手动搜索不计入。';
const usageScopeMessage = `汇总所有用户的默认资源副本与自建资源。${usageMethodMessage}`;
const defaultUsageScopeMessage = `汇总该平台模板在所有用户中的默认副本调用，与概览包含自建资源的全量总计范围不同。${usageMethodMessage}`;
type UsageResourceKind = 'agents' | 'knowledge' | 'skills';
function usageCount(value?: number) { return typeof value === 'number' ? `${value.toLocaleString('zh-CN')} 次` : '暂无统计'; }
interface DefaultResource {
  id: string; name: string; description?: string; kind?: 'local' | 'remote' | 'ssh' | 'kubernetes';
  url?: string; system_prompt?: string; icon?: string; color?: string; sort_order?: number;
  skill_ids?: string[]; knowledge_ids?: string[]; server_ids?: string[]; provider_id?: string | null;
  agent_id?: string | null; server_id?: string | null; model?: string | null; control_level?: 'observe' | 'approve' | 'autonomous';
  content?: string; enabled?: boolean; status?: 'active' | 'archived' | 'unknown' | 'online' | 'offline';
  document_count?: number; chunk_count?: number; host?: string; port?: number; username?: string;
  auth_type?: 'password' | 'key'; fingerprint?: string; trust_on_first_use?: boolean; has_credentials?: boolean;
  tags?: string[]; base_url?: string; has_api_key?: boolean; models?: string[]; default_model?: string;
  model_sync?: Provider['model_sync']; usage_count?: number;
  prompt?: string; cron?: string; timezone?: string;
}
interface AdminDocument { id: string; name: string; content: string }
type OwnedAlert = Alert & { owner_id: string; owner_email: string };
type AdminAudit = Audit & { owner_email?: string; owner?: string };
type SpaceModule = 'personal' | 'team';
type AdminUser = User & { created_at?: string; space_modules?: SpaceModule[]; readonly team_invites_blocked?: boolean };
const allControlLevels: ControlLevel[] = ['observe', 'approve', 'autonomous'];
const defaultSpaceModules: SpaceModule[] = ['personal'];
const allSpaceModules: SpaceModule[] = ['personal', 'team'];
const spaceModuleLabels: Record<SpaceModule, string> = { personal: '个人空间', team: '团队空间' };

function ControlLevelPermissions({ selected = ['observe'], disabled = false }: { selected?: ControlLevel[]; disabled?: boolean }) {
  return <fieldset className="ea-admin-control-levels" disabled={disabled}>
    <legend>授权控制模式 · 至少选择一项</legend>
    <p>可多选，只决定账户可以使用哪些模式，不修改个人默认控制等级。管理员不执行任务，但仍可保存授权，切换为普通用户后生效。</p>
    <div>{allControlLevels.map(level => <label key={level}><input className="ea-admin-checkbox" type="checkbox" name="allowed_control_levels" value={level} defaultChecked={selected.includes(level)} /><span><strong>{controlLabels[level]}</strong><small>{controlDescriptions[level]}</small></span></label>)}</div>
  </fieldset>;
}

function SpaceModulePermissions({ selected = defaultSpaceModules, disabled = false }: { selected?: SpaceModule[]; disabled?: boolean }) {
  return <fieldset className="ea-admin-control-levels ea-admin-space-modules" disabled={disabled}>
    <legend>开放空间模块 · 可多选或全部关闭</legend>
    <p>新账户默认仅开放个人空间。两项都不选表示暂停所有空间访问，不影响账户角色或控制模式授权。</p>
    <div>{allSpaceModules.map(module => <label key={module}><input className="ea-admin-checkbox" type="checkbox" name="space_modules" value={module} defaultChecked={selected.includes(module)} /><span><strong>{spaceModuleLabels[module]}</strong><small>{module === 'personal' ? '使用自己的文件、默认资源副本与个人工作空间。' : '创建或加入团队，访问已获授权的团队资源。'}</small></span></label>)}</div>
    <p className="ea-admin-space-preservation"><strong>关闭模块不删除数据，可重新开放恢复访问</strong>仅隐藏对应入口并拒绝访问；已有个人文件、团队资源与成员关系保留。这不同于永久删除账户。</p>
    <p className="ea-admin-space-invite-policy">新账户未开放团队空间时，仍可通过邀请自动开通。管理员取消已开放的团队空间后，邀请不能绕过停用；需管理员重新勾选团队空间并保存，才能解除邀请阻止。</p>
  </fieldset>;
}

function AdminForm({ title, description, onClose, onSubmit, children, scope, wide = true, submitLabel = '保存并同步', submitDisabled = false }: {
  title: string; description?: string; onClose: () => void; onSubmit: (form: FormData) => Promise<unknown>;
  children: ReactNode; scope: string; wide?: boolean; submitLabel?: string; submitDisabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError('');
    try { await onSubmit(form); onClose(); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };
  return <Modal title={title} description={description} onClose={onClose} wide={wide} preventClose={busy}>
    <form className="ea-admin-dialog" onSubmit={event => { void submit(event); }}>
      <fieldset className="form-body" disabled={busy}>
        <Banner tone="warning">{scope}</Banner>
        {children}
        {error && <div className="inline-error" role="alert">{error}</div>}
      </fieldset>
      <div className="modal-footer"><span className="small muted">{busy ? '正在保存，请勿重复提交…' : '以本表单上方的生效范围为准'}</span><Button type="button" variant="secondary" onClick={onClose} disabled={busy}>取消</Button><Button type="submit" busy={busy} disabled={submitDisabled}><Check size={16} />{submitLabel}</Button></div>
    </form>
  </Modal>;
}

function CheckBox({ label, checked, mixed = false, onChange, disabled = false }: { label: string; checked: boolean; mixed?: boolean; onChange: () => void; disabled?: boolean }) {
  return <input className="ea-admin-checkbox" ref={element => { if (element) element.indeterminate = mixed; }} type="checkbox" aria-label={label} checked={checked} onChange={onChange} disabled={disabled} />;
}
function useSelection(items: { id: string }[]) {
  const [ids, setIds] = useState<string[]>([]);
  const valid = new Set(items.map(item => item.id));
  const selected = ids.filter(id => valid.has(id));
  const toggle = (id: string) => setIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const toggleAll = (visible: string[]) => setIds(current => visible.every(id => current.includes(id)) ? current.filter(id => !visible.includes(id)) : [...new Set([...current.filter(id => valid.has(id)), ...visible])]);
  return { ids: selected, toggle, toggleAll, clear: () => setIds([]) };
}
type Selection = ReturnType<typeof useSelection>;
function SelectionBar({ selection, visible, total, children, disabled = false }: { selection: Selection; visible: string[]; total: number; children: ReactNode; disabled?: boolean }) {
  const all = visible.length > 0 && visible.every(id => selection.ids.includes(id));
  const some = visible.some(id => selection.ids.includes(id));
  return <div className="ea-admin-selection" aria-label="批量操作">
    <label><CheckBox label="全选当前筛选结果" checked={all} mixed={some && !all} onChange={() => selection.toggleAll(visible)} disabled={disabled || !visible.length} /><span>全选当前结果</span></label>
    <span className="ea-admin-selection-count" aria-live="polite">已选 <strong>{selection.ids.length}</strong> / 共 {total} 项</span>
    {selection.ids.length > 0 && <button type="button" className="ea-admin-text-button" onClick={selection.clear}>清空选择</button>}
    <div className="ea-admin-selection-actions">{children}</div>
  </div>;
}

interface AdminOverview {
  counts: Record<string, number>; health: Record<string, string>;
  usage?: { totals: Record<UsageResourceKind, number>; started_at: string; scope: 'all_resources'; method: 'per_run_resource_and_remote_click'; description: string };
}
const usageMetrics: { key: UsageResourceKind; label: string; icon: LucideIcon; hint: string }[] = [
  { key: 'agents', label: '智能体总调用次数', icon: Bot, hint: '所有用户的默认及自建智能体；本地同任务同资源计一次，远程每次打开计一次。' },
  { key: 'knowledge', label: '知识库总调用次数', icon: BookOpen, hint: '所有用户的默认及自建知识库检索命中；同任务同资源计一次，不是任务成功数。' },
  { key: 'skills', label: '技能总调用次数', icon: Blocks, hint: '所有用户的默认及自建技能注入；同任务同资源计一次，不是任务成功数。' },
];
function auditPreset(value: string) {
  if (value === 'all') return { start: '', end: '' };
  const end = new Date();
  const days = value === '24h' ? 1 : value === '30d' ? 30 : 7;
  return { start: new Date(end.getTime() - days * 86400000).toISOString(), end: end.toISOString() };
}
export function AdminOverviewPage() {
  const overview = useResource<AdminOverview | null>('/admin/overview', null);
  const [range, setRange] = useState('7d');
  const [period, setPeriod] = useState(() => auditPreset('7d'));
  const [start, setStart] = useState(''); const [end, setEnd] = useState('');
  const [validation, setValidation] = useState(''); const [search, setSearch] = useState('');
  const params = new URLSearchParams();
  if (period.start) params.set('start', period.start);
  if (period.end) params.set('end', period.end);
  const audit = useResource<AdminAudit[]>(`/admin/audit${params.size ? `?${params}` : ''}`, []);
  const data = overview.data;
  const filtered = audit.data.filter(item => `${item.owner_email || ''} ${item.action} ${item.resource} ${pretty(item.detail)}`.toLowerCase().includes(search.toLowerCase()));
  const applyDates = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const from = start ? new Date(start) : null; const to = end ? new Date(end) : null;
    if (!from && !to) { setValidation('请至少填写开始或结束时间，或选择全部时间。'); return; }
    if ((from && Number.isNaN(from.getTime())) || (to && Number.isNaN(to.getTime()))) { setValidation('请输入有效的日期与时间。'); return; }
    if (from && to && from > to) { setValidation('结束时间不能早于开始时间。'); return; }
    setValidation('');
    const next = { start: from?.toISOString() || '', end: to?.toISOString() || '' };
    if (next.start === period.start && next.end === period.end) void audit.reload();
    else setPeriod(next);
  };
  return <div className="page ea-admin-page">
    <PageHeader eyebrow="PLATFORM CONTROL" title="全局视野，可靠治理" description="查看平台资源、服务健康与跨账户操作记录。这里不发起普通用户的诊断或执行任务。" action={<Button variant="secondary" busy={overview.loading || audit.loading} onClick={() => { void overview.reload(); if (range === 'custom') void audit.reload(); else setPeriod(auditPreset(range)); }}><RefreshCw size={16} />刷新</Button>} />
    <div className="ea-admin-governance"><ShieldCheck size={24} /><div><strong>管理配置，服务每一位用户</strong><p>{syncMessage}</p></div><span>管理员工作台</span></div>
    {overview.error && <ErrorState message={overview.error} retry={overview.reload} />}
    {overview.loading ? <Loading text="读取平台概览…" /> : !overview.error && data && <>
      <div className="ea-admin-metrics">{[
        { key: 'users', label: '全部账户', icon: Users, hint: `其中 ${data.counts.admins || 0} 位管理员` },
        { key: 'runs', label: '累计执行', icon: Activity, hint: '来自全平台真实运行记录' },
        { key: 'active_runs', label: '正在执行', icon: Sparkles, hint: '包含排队与等待审批' },
        { key: 'alerts', label: '全员告警', icon: Bell, hint: '在告警管理中统一处理' },
      ].map(metric => <section className="ea-admin-metric" key={metric.key}><div><span>{metric.label}</span><metric.icon size={20} /></div><strong>{data.counts[metric.key] || 0}</strong><p>{metric.hint}</p></section>)}</div>
      <section className="ea-admin-usage" aria-label="全平台资源调用统计" data-usage-scope={data.usage?.scope} data-usage-method={data.usage?.method}>
        <div className="ea-admin-usage-grid">{usageMetrics.map(metric => <section className="ea-admin-metric ea-admin-usage-card" key={metric.key} data-usage-kind={metric.key} data-usage-state={typeof data.usage?.totals?.[metric.key] === 'number' ? 'available' : 'unavailable'} title={usageScopeMessage}>
          <div><h2>{metric.label}</h2><metric.icon size={20} /></div>
          <strong className="ea-admin-usage-value">{usageCount(data.usage?.totals?.[metric.key])}</strong>
          <p>{metric.hint}</p>
          <p className="ea-admin-usage-start">统计起点：{data.usage?.started_at ? <time dateTime={data.usage.started_at}>{dateTime(data.usage.started_at)}</time> : '暂无统计'}</p>
        </section>)}</div>
        <p className="ea-admin-caption ea-admin-usage-scope" title={data.usage?.description}><strong>统计口径：</strong>{usageScopeMessage} 仅记录统计起点后的调用，不推算历史调用。</p>
      </section>
      <div className="ea-admin-overview-grid"><section className="panel ea-admin-panel"><SectionTitle title="默认资源目录" subtitle="这里只统计平台模板，不重复计算各用户的继承副本。" /><div className="ea-admin-default-counts">{resourceKinds.map(kind => { const Icon = resourceInfo[kind].icon; return <div key={kind}><Icon size={19} /><span>{resourceInfo[kind].name}</span><strong>{data.counts[kind] || 0}</strong></div>; })}</div></section><section className="panel ea-admin-panel"><SectionTitle title="服务健康" /><div className="ea-admin-health"><span><CheckCircle2 size={30} /></span><div><strong>{data.health.status === 'ok' ? '服务运行正常' : data.health.status || '状态未知'}</strong><p>状态由服务端真实返回</p></div></div><dl className="ea-admin-health-list">{Object.entries(data.health).map(([key, value]) => <div key={key}><dt>{({ status: '应用状态', database: '数据库', version: '版本' } as Record<string, string>)[key] || key}</dt><dd>{value === 'ok' ? '正常' : value}</dd></div>)}</dl></section></div>
    </>}
    <section className="panel ea-admin-panel ea-admin-audit"><SectionTitle title="全平台审计日志" subtitle="追溯操作账户、对象与详情，最多返回最近 100 条。日志不提供编辑或删除入口。" />
      <form className="ea-admin-audit-filter" onSubmit={applyDates}><Field label="时间范围"><Select label="审计时间范围" value={range} onChange={value => { setRange(value); setValidation(''); if (value !== 'custom') setPeriod(auditPreset(value)); }} options={[{ value: '24h', label: '最近 24 小时' }, { value: '7d', label: '最近 7 天' }, { value: '30d', label: '最近 30 天' }, { value: 'all', label: '全部时间' }, { value: 'custom', label: '自定义时间' }]} /></Field>{range === 'custom' && <><Field label="开始时间（本地）"><input type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></Field><Field label="结束时间（本地）"><input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></Field><Button variant="secondary" type="submit" busy={audit.loading}><Search size={15} />查询</Button></>}</form>
      <p className="ea-admin-caption">浏览器时区：{Intl.DateTimeFormat().resolvedOptions().timeZone}。输入会转换为 UTC 查询；当前范围：{period.start ? dateTime(period.start) : '不限开始'} 至 {period.end ? dateTime(period.end) : '不限结束'}。</p>
      {validation && <div className="inline-error" role="alert">{validation}</div>}
      <div className="ea-admin-toolbar"><span className="muted small">已读取 {audit.data.length} 条 · 当前显示 {filtered.length} 条</span><SearchInput value={search} onChange={setSearch} placeholder="筛选账户、操作或资源…" /></div>
      {audit.loading ? <Loading text="查询审计记录…" /> : audit.error ? <ErrorState message={audit.error} retry={audit.reload} /> : filtered.length ? <div className="ea-admin-audit-list">{filtered.map(item => <details key={item.id}><summary><span className="ea-admin-audit-dot" /><div><strong>{item.action}</strong><span>{item.owner_email || item.owner || '系统'} · {item.resource || '平台配置'}</span></div><time dateTime={item.created_at}>{dateTime(item.created_at)}</time></summary><pre>{pretty(item.detail) || '无补充详情'}</pre></details>)}</div> : <EmptyState compact title="没有匹配的审计记录" description="可调整时间范围或关键词。不会生成示例记录。" />}
    </section>
  </div>;
}

export function AdminResourcePage({ kind }: { kind: string }) {
  if (!resourceKinds.includes(kind as ResourceKind)) return <div className="page ea-admin-page"><EmptyState title="未知的默认资源类型" description="请从管理员导航打开智能体、技能、知识库、项目、服务器、供应商或定时任务。" /></div>;
  return <DefaultResourcePage key={kind} kind={kind as ResourceKind} />;
}
function DefaultResourcePage({ kind }: { kind: ResourceKind }) {
  const info = resourceInfo[kind]; const Icon = info.icon;
  const path = `/admin/defaults/${kind}`;
  const resource = useResource<DefaultResource[]>(path, []);
  const [search, setSearch] = useState(''); const [filter, setFilter] = useState('all');
  const [edit, setEdit] = useState<DefaultResource | 'new' | null>(null);
  const [importing, setImporting] = useState(false); const [batching, setBatching] = useState(false);
  const [ordering, setOrdering] = useState(false);
  const [documents, setDocuments] = useState<DefaultResource | null>(null);
  const selection = useSelection(resource.data); const { confirm, dialog } = useConfirm(); const notify = useToast();
  const hasEnabled = ['skills', 'providers', 'schedules'].includes(kind);
  const hasDescription = !['providers', 'schedules'].includes(kind);
  const filters = hasEnabled ? [{ value: 'enabled', label: '已启用' }, { value: 'disabled', label: '已停用' }] : kind === 'projects' ? [{ value: 'active', label: '进行中' }, { value: 'archived', label: '已归档' }] : kind === 'agents' ? [{ value: 'local', label: '本地智能体' }, { value: 'remote', label: '远程智能体' }] : kind === 'servers' ? [{ value: 'ssh', label: 'SSH' }, { value: 'kubernetes', label: 'Kubernetes' }] : [];
  const filtered = resource.data.filter(item => `${item.name} ${item.description || ''} ${item.host || ''} ${item.base_url || ''} ${item.prompt || ''} ${item.tags?.join(' ') || ''}`.toLowerCase().includes(search.toLowerCase()) && (filter === 'all' || (hasEnabled ? item.enabled === (filter === 'enabled') : kind === 'projects' ? item.status === filter : (item.kind || 'local') === filter)));
  const changed = (message: string) => { dataChanged(); notify(message); };
  const syncModels = async (item: DefaultResource) => {
    const response = await api.post<Provider>(`${path}/${item.id}/sync-models`);
    dataChanged();
    const sync = response.model_sync;
    if (sync?.status === 'ok') notify(`已同步 ${sync.count ?? response.models.length} 个模型，并同步所有普通用户`);
    else if (sync?.status === 'error') notify('模型同步失败，已保留原有模型配置；可点击“同步模型”重试，或编辑后手动填写模型。', 'error');
    else if (sync?.status === 'empty') notify('供应商未返回可用模型，已保留原有模型配置；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    else if (sync?.status === 'stale') notify('供应商配置已变更，本次同步结果未应用；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    else notify('未收到模型同步结果，请刷新后重试或手动填写模型。', 'info');
  };
  const remove = (ids: string[]) => confirm(`删除 ${ids.length} 个默认${info.singular}？`, '平台模板将移除，仍跟随模板的用户副本也会移除；用户已保存的个人定制副本会保留，新用户不再继承。关联资源或任务可能失去依赖；已有执行记录不会被改写。', async () => { if (ids.length === 1) await api.delete(`${path}/${ids[0]}`); else await api.post(`${path}/batch`, { ids, action: 'delete', changes: {} }); selection.clear(); changed('默认资源已删除并同步'); });
  return <div className="page ea-admin-page">
    <PageHeader eyebrow="SHARED DEFAULTS" title={info.name} description={info.note} action={<>{kind === 'agents' && <Button variant="secondary" data-admin-action="reorder-agents" onClick={() => setOrdering(true)} disabled={resource.loading || Boolean(resource.error) || resource.data.length < 2}><ArrowUpDown size={16} />调整排序</Button>}<Button variant="secondary" onClick={() => setImporting(true)}><FileJson size={16} />JSON 批量导入</Button><NewButton onClick={() => setEdit('new')}>新增默认{info.singular}</NewButton></>} />
    <Banner tone="warning">{syncMessage}</Banner>
    <div className="ea-admin-toolbar"><div className="ea-admin-filter"><span className="ea-admin-mini-icon"><Icon size={18} /></span><span>{resource.data.length} 个平台模板</span>{filters.length > 0 && <Select label="资源状态或类型" compact value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部' }, ...filters]} />}</div><SearchInput value={search} onChange={setSearch} placeholder={`搜索${info.singular}名称、描述或地址…`} /></div>
    <SelectionBar selection={selection} visible={filtered.map(item => item.id)} total={resource.data.length} disabled={resource.loading || Boolean(resource.error)}><Button variant="secondary" className="button-small" disabled={!selection.ids.length} onClick={() => setBatching(true)}><Pencil size={14} />批量修改</Button><Button variant="danger" className="button-small" disabled={!selection.ids.length} onClick={() => remove(selection.ids)}><Trash2 size={14} />批量删除</Button></SelectionBar>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}
    {resource.loading ? <Loading text="读取平台默认资源…" /> : resource.error ? null : !filtered.length ? <div className="panel"><EmptyState compact icon={Icon} title={resource.data.length ? '没有匹配的资源' : `尚未配置默认${info.singular}`} description={resource.data.length ? '请调整关键词或筛选条件。已选项目可跨筛选保留，操作前请核对计数。' : '通过页头新增完整配置，或使用 JSON 一次导入多项。保存后会自动同步所有普通用户。'} /></div> : <div className="ea-admin-resource-grid">{filtered.map(item => <article className={`ea-admin-resource-card${selection.ids.includes(item.id) ? ' is-selected' : ''}`} key={item.id} data-resource-kind={kind} data-resource-id={item.id}>
      <div className="ea-admin-resource-top"><CheckBox label={`选择 ${item.name}`} checked={selection.ids.includes(item.id)} onChange={() => selection.toggle(item.id)} /><span className="ea-admin-resource-icon" style={item.color ? { color: item.color } : undefined}><Icon size={22} /></span><span className="ea-admin-shared-label">全员默认</span>{hasEnabled && <span className={`ea-admin-pill${item.enabled ? ' is-enabled' : ''}`}>{item.enabled ? '已启用' : '已停用'}</span>}</div>
      <h2>{item.name}</h2><p className="ea-admin-resource-description">{item.description || item.prompt || (kind === 'providers' ? '统一的 OpenAI 兼容模型配置' : '未填写描述')}</p>
      <ResourceSummary kind={kind} item={item} />
      {kind === 'providers' && item.model_sync && item.model_sync.status !== 'ok' && <Banner tone="warning">{item.model_sync.status === 'error' ? '模型同步失败。' : item.model_sync.status === 'empty' ? '模型同步未返回可用模型。' : '供应商配置已变更，模型目录需要重新同步。'}可点击“同步模型”重试，或编辑后手动填写模型。</Banner>}
      <div className="ea-admin-resource-actions">{kind === 'knowledge' && <Button variant="secondary" className="button-small" onClick={() => setDocuments(item)}><FileText size={14} />文档管理</Button>}{kind === 'providers' && <AsyncButton variant="secondary" className="button-small" action={() => syncModels(item)}><RefreshCw size={14} />同步模型</AsyncButton>}{hasEnabled && <AsyncButton variant="ghost" className="button-small" action={async () => { await api.patch(`${path}/${item.id}`, { enabled: !item.enabled }); changed(item.enabled ? '已停用并同步' : '已启用并同步'); }}>{item.enabled ? '停用' : '启用'}</AsyncButton>}<div className="card-footer-spacer" /><Button variant="ghost" className="button-small" onClick={() => setEdit(item)}><Pencil size={14} />编辑</Button><button className="icon-button danger-text" type="button" aria-label={`删除 ${item.name}`} onClick={() => remove([item.id])}><Trash2 size={15} /></button></div>
    </article>)}</div>}
    {ordering && kind === 'agents' && <DefaultAgentOrderDialog agents={resource.data} onClose={() => setOrdering(false)} />}
    {edit && <ResourceForm key={edit === 'new' ? 'new' : edit.id} kind={kind} item={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={response => {
      dataChanged();
      if (kind !== 'providers' || edit !== 'new') notify('默认配置已保存，并自动同步所有普通用户');
      else if (response.model_sync?.status === 'ok') notify(`默认供应商配置已保存，已自动同步 ${response.model_sync.count ?? response.models?.length ?? 0} 个模型，并同步所有普通用户`);
      else if (response.model_sync?.status === 'error') notify('默认供应商配置已保存并同步所有普通用户，但自动同步模型失败；可点击“同步模型”重试，或编辑后手动填写模型。', 'error');
      else if (response.model_sync?.status === 'empty') notify('默认供应商配置已保存并同步所有普通用户，但自动同步未返回可用模型；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
      else if (response.model_sync?.status === 'stale') notify('默认供应商配置已保存并同步所有普通用户，但配置已变更，自动同步结果未应用；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
      else notify('默认供应商配置已保存并同步所有普通用户，但未收到自动同步结果；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    }} />}
    {batching && <AdminForm title={`批量修改 ${selection.ids.length} 个默认${info.singular}`} description="只更新明确选择的字段，其他字段与已有凭据保持不变。" onClose={() => setBatching(false)} scope={syncMessage} onSubmit={async form => {
      const changes: Record<string, unknown> = {};
      if (hasDescription && form.has('apply_description')) changes.description = formString(form, 'description');
      const enabled = formString(form, 'enabled'); if (enabled) changes.enabled = enabled === 'true';
      const status = formString(form, 'status'); if (status) changes.status = status;
      if (kind === 'providers' && form.has('apply_models')) {
        const models = listFromText(formString(form, 'models'));
        const defaultModel = formString(form, 'default_model');
        if (defaultModel && !models.includes(defaultModel)) throw new Error('默认模型必须来自模型列表；也可以留空。');
        changes.models = models; changes.default_model = defaultModel;
      }
      if (!Object.keys(changes).length) throw new Error('请至少选择一项需要修改的字段。');
      await api.post(`${path}/batch`, { ids: selection.ids, action: 'update', changes }); selection.clear(); changed('批量配置已保存并同步');
    }}>
      {hasEnabled && <Field label="统一启停"><Select name="enabled" label="统一启停" defaultValue="" options={[{ value: '', label: '保持不变' }, { value: 'true', label: '全部启用' }, { value: 'false', label: '全部停用' }]} /></Field>}
      {kind === 'projects' && <Field label="项目状态"><Select name="status" label="统一项目状态" defaultValue="" options={[{ value: '', label: '保持不变' }, { value: 'active', label: '全部设为进行中' }, { value: 'archived', label: '全部归档' }]} /></Field>}
      {hasDescription && <><Switch name="apply_description" label="统一替换描述（留空表示清空描述）" /><Field label="新的统一描述"><textarea name="description" rows={4} maxLength={kind === 'agents' ? 300 : 10000} placeholder="仅在勾选统一替换描述时更新" /></Field></>}
      {kind === 'providers' && <><Switch name="apply_models" label="统一替换模型列表与默认模型" /><Field label="新的模型列表" hint="可留空。每行一个或逗号分隔；勾选后会替换全部所选供应商的模型目录，不自动同步。"><textarea name="models" rows={5} className="mono" /></Field><Field label="新的默认模型" hint="可留空；列表非空时，后端会选用首个模型。填写时必须来自上方列表。"><input name="default_model" /></Field></>}
      {kind === 'schedules' && <Banner tone="warning">启用会为所有普通用户开启真实自动调度，请先核实模型、服务器、时区与控制等级。</Banner>}
      <p className="ea-admin-caption">当前选择 {selection.ids.length} 项，包含可能被当前筛选隐藏的已选项目。</p>
    </AdminForm>}
    {importing && <ResourceImport kind={kind} onClose={() => setImporting(false)} onSaved={() => changed('批量导入完成，默认资源已同步')} />}
    {documents && <KnowledgeDocuments knowledge={documents} onClose={() => setDocuments(null)} />}
    {dialog}
  </div>;
}
function DefaultAgentOrderDialog({ agents, onClose }: { agents: DefaultResource[]; onClose: () => void }) {
  const [order, setOrder] = useState(() => [...agents]);
  const [pending, setPending] = useState(false);
  const saving = useRef(false);
  const draggedId = useRef<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [announcement, setAnnouncement] = useState('');
  const notify = useToast();

  const move = (id: string, targetId: string) => {
    if (saving.current || id === targetId) return;
    const from = order.findIndex(agent => agent.id === id);
    const to = order.findIndex(agent => agent.id === targetId);
    if (from < 0 || to < 0) return;
    const next = [...order];
    const [agent] = next.splice(from, 1);
    next.splice(to, 0, agent);
    setOrder(next);
    setAnnouncement(`${agent.name}已移至第 ${to + 1} 位，共 ${next.length} 个默认智能体。`);
  };
  const endDrag = () => { draggedId.current = null; setDragging(null); setDropTarget(null); };
  const save = async () => {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setError('');
    endDrag();
    try {
      await api.post<{ ok: true; count: number }>('/admin/defaults/agents/reorder', { agent_ids: order.map(agent => agent.id) });
      dataChanged();
      notify('默认智能体排序已保存');
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      saving.current = false;
      setPending(false);
    }
  };

  return <Modal title="调整默认智能体排序" description="拖动列表，或使用上移、下移按钮；保存后才会更新平台默认顺序。普通用户仍可维护自己的显示顺序。" onClose={onClose} preventClose={pending}>
    <div className="ea-agent-order ea-admin-agent-order" aria-busy={pending}>
      <div className="ea-agent-order-body">
        <p className="ea-agent-order-hint">全部 {order.length} 个默认智能体，不受页面搜索、类型筛选或勾选范围影响。新增智能体默认追加到末尾。</p>
        <ol className="ea-agent-order-list" aria-label="全部默认智能体排序列表">
          {order.map((agent, index) => <li
            key={agent.id}
            className="ea-agent-order-row"
            aria-label={`第 ${index + 1} 位：${agent.name}，${agent.kind === 'remote' ? '远程' : '本地'}智能体`}
            data-agent-id={agent.id}
            data-dragging={dragging === agent.id || undefined}
            data-drop-target={dropTarget === agent.id && dragging !== agent.id || undefined}
            draggable={!pending}
            onDragStart={event => {
              if (saving.current) { event.preventDefault(); return; }
              draggedId.current = agent.id;
              event.dataTransfer.effectAllowed = 'move';
              event.dataTransfer.setData('text/plain', agent.id);
              setDragging(agent.id);
            }}
            onDragOver={event => {
              if (saving.current || !draggedId.current) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
              setDropTarget(agent.id);
            }}
            onDrop={event => {
              if (saving.current || !draggedId.current) return;
              event.preventDefault();
              move(draggedId.current, agent.id);
              endDrag();
            }}
            onDragEnd={endDrag}
          >
            <span className="ea-agent-order-grip" aria-hidden="true"><GripVertical size={18} /></span>
            <span className="ea-agent-order-number" aria-hidden="true">{index + 1}</span>
            <strong className="ea-agent-order-name">{agent.name}</strong>
            <span className={`ea-agent-kind${agent.kind === 'remote' ? ' ea-agent-kind-remote' : ''}`}>{agent.kind === 'remote' ? '远程' : '本地'}</span>
            <div className="ea-agent-order-controls">
              <button type="button" className="icon-button" aria-label={`上移 ${agent.name}`} title={`上移 ${agent.name}`} disabled={pending || index === 0} onClick={() => move(agent.id, order[index - 1].id)}><ArrowUp size={16} /></button>
              <button type="button" className="icon-button" aria-label={`下移 ${agent.name}`} title={`下移 ${agent.name}`} disabled={pending || index === order.length - 1} onClick={() => move(agent.id, order[index + 1].id)}><ArrowDown size={16} /></button>
            </div>
          </li>)}
        </ol>
        <span className="ea-agent-order-announcement" role="status" aria-live="polite">{announcement}</span>
        {error && <div className="inline-error ea-admin-agent-order-error" role="alert">{error}</div>}
      </div>
      <div className="modal-footer ea-agent-order-footer">
        <span className="small muted">{pending ? '正在保存排序，请勿重复提交…' : '仅在保存后生效；取消将放弃本次调整'}</span>
        <Button type="button" variant="secondary" data-admin-action="reorder-cancel" disabled={pending} onClick={onClose}>取消</Button>
        <Button type="button" data-admin-action="reorder-save" busy={pending} onClick={() => { void save(); }}><Check size={16} />保存排序</Button>
      </div>
    </div>
  </Modal>;
}
function ResourceSummary({ kind, item }: { kind: ResourceKind; item: DefaultResource }) {
  let rows: [string, string][] = [];
  if (kind === 'agents') rows = item.kind === 'remote' ? [['类型', '远程 · 仅保存访问 URL'], ['访问地址', item.url || '未配置']] : [['类型', '本地智能体'], ['能力关联', `${item.skill_ids?.length || 0} 项技能 · ${item.knowledge_ids?.length || 0} 个知识库`], ['模型', item.model || '沿用对话选择']];
  if (kind === 'skills') rows = [['技能正文', `${item.content?.length || 0} 字符 · 可信指令上下文`]];
  if (kind === 'knowledge') rows = [['已收录', `${item.document_count || 0} 份文档 · ${item.chunk_count || 0} 个片段`]];
  if (kind === 'projects') rows = [['状态', item.status === 'archived' ? '已归档' : '进行中'], ['关联资源', `${item.server_ids?.length || 0} 台服务器 · ${item.knowledge_ids?.length || 0} 个知识库 · ${item.skill_ids?.length || 0} 项技能`]];
  if (kind === 'servers') rows = [['连接类型', item.kind === 'kubernetes' ? 'Kubernetes' : 'SSH'], ['连接地址', item.kind === 'kubernetes' ? '独立 kubeconfig' : `${item.username || '—'}@${item.host || '—'}:${item.port || 22}`], ['凭据', item.has_credentials ? '已安全保存，不回显' : '尚未配置']];
  if (kind === 'providers') rows = [['接口地址', item.base_url || '未配置'], ['默认模型', item.default_model || '未设置'], ['可选模型', `${item.models?.length || 0} 个 · ${item.has_api_key ? '密钥已保存' : '无密钥'}`]];
  if (kind === 'schedules') rows = [['Cron', item.cron || '未配置'], ['时区', item.timezone || 'Asia/Shanghai'], ['执行模型', item.model || '使用默认模型']];
  return <dl className="ea-admin-resource-meta">{rows.map(([label, text]) => <div key={label}><dt>{label}</dt><dd title={text}>{text}</dd></div>)}{['agents', 'knowledge', 'skills'].includes(kind) && <div className="ea-admin-resource-usage" data-usage-kind={kind} data-usage-state={typeof item.usage_count === 'number' ? 'available' : 'unavailable'}><dt>调用次数</dt><dd className="ea-admin-resource-usage-value" title={defaultUsageScopeMessage}>{usageCount(item.usage_count)}</dd></div>}</dl>;
}

function useDefaultRelations(enabled: boolean) {
  const skills = useResource<Skill[]>(enabled ? '/admin/defaults/skills' : null, []);
  const knowledge = useResource<Knowledge[]>(enabled ? '/admin/defaults/knowledge' : null, []);
  const servers = useResource<Server[]>(enabled ? '/admin/defaults/servers' : null, []);
  const providers = useResource<Provider[]>(enabled ? '/admin/defaults/providers' : null, []);
  const agents = useResource<Agent[]>(enabled ? '/admin/defaults/agents' : null, []);
  const projects = useResource<Project[]>(enabled ? '/admin/defaults/projects' : null, []);
  const resources = [skills, knowledge, servers, providers, agents, projects];
  return { skills: skills.data, knowledge: knowledge.data, servers: servers.data, providers: providers.data, agents: agents.data, loading: resources.some(resource => resource.loading), error: resources.map(resource => resource.error).filter(Boolean).join('；'), reload: () => Promise.all(resources.map(resource => resource.reload())) };
}
function ResourceForm({ kind, item, onClose, onSaved }: { kind: ResourceKind; item: DefaultResource | null; onClose: () => void; onSaved: (response: DefaultResource) => void }) {
  const [agentKind, setAgentKind] = useState(item?.kind === 'remote' ? 'remote' : 'local');
  const [serverKind, setServerKind] = useState(item?.kind === 'kubernetes' ? 'kubernetes' : 'ssh');
  const [auth, setAuth] = useState(item?.auth_type || 'key');
  const [trust, setTrust] = useState(item?.trust_on_first_use ?? true);
  const [providerId, setProviderId] = useState(item?.provider_id || '');
  const [model, setModel] = useState(item?.model || '');
  const [models, setModels] = useState<string[]>(item?.models?.length ? [...item.models] : ['']);
  const [defaultModel, setDefaultModel] = useState(item?.default_model || '');
  const needsRelations = (kind === 'agents' && agentKind === 'local') || kind === 'projects' || kind === 'schedules';
  const relations = useDefaultRelations(needsRelations);
  const provider = relations.providers.find(value => value.id === providerId);
  const credentialRequired = !item?.has_credentials || item.kind !== serverKind || (serverKind === 'ssh' && item.auth_type !== auth);
  const submit = async (form: FormData) => {
    const payload: Record<string, unknown> = { name: formString(form, 'name') };
    if (!['providers', 'schedules'].includes(kind)) payload.description = formString(form, 'description');
    if (kind === 'agents') {
      Object.assign(payload, { kind: agentKind, icon: formString(form, 'icon') || 'Bot', color: formString(form, 'color') });
      if (agentKind === 'remote') {
        const url = formString(form, 'url');
        let valid = false;
        try { const parsed = new URL(url); valid = ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.hostname); } catch { valid = false; }
        if (!valid) throw new Error('远程智能体只接受有效的 HTTP / HTTPS 地址。');
        payload.url = url;
      } else Object.assign(payload, { url: '', system_prompt: formString(form, 'system_prompt'), skill_ids: formList(form, 'skill_ids'), knowledge_ids: formList(form, 'knowledge_ids'), provider_id: providerId || null, model: model || null, control_level: formString(form, 'control_level') });
    }
    if (kind === 'skills') Object.assign(payload, { content: String(form.get('content') || ''), enabled: form.has('enabled') });
    if (kind === 'projects') Object.assign(payload, { color: formString(form, 'color'), status: formString(form, 'status'), server_ids: formList(form, 'server_ids'), knowledge_ids: formList(form, 'knowledge_ids'), skill_ids: formList(form, 'skill_ids') });
    if (kind === 'servers') {
      Object.assign(payload, { kind: serverKind, tags: listFromText(formString(form, 'tags')) });
      if (serverKind === 'ssh') {
        Object.assign(payload, { host: formString(form, 'host'), port: Number(formString(form, 'port')), username: formString(form, 'username'), auth_type: auth, fingerprint: formString(form, 'fingerprint'), trust_on_first_use: trust });
        const secretField = auth === 'password' ? 'password' : 'private_key';
        if (formString(form, secretField)) payload[secretField] = formString(form, secretField);
      } else if (formString(form, 'kubeconfig')) payload.kubeconfig = formString(form, 'kubeconfig');
    }
    if (kind === 'providers') {
      const clean = models.map(value => value.trim()).filter(Boolean);
      if (new Set(clean).size !== clean.length) throw new Error('模型标识不能重复，请修改或删除重复行。');
      if (defaultModel && !clean.includes(defaultModel)) throw new Error('默认模型必须来自上方模型列表；也可以留空。');
      Object.assign(payload, { base_url: formString(form, 'base_url').replace(/\/+$/, ''), models: clean, default_model: defaultModel, enabled: form.has('enabled') });
      if (formString(form, 'api_key')) payload.api_key = formString(form, 'api_key');
    }
    if (kind === 'schedules') {
      const cron = formString(form, 'cron');
      if (cron.split(/\s+/).length !== 5) throw new Error('Cron 需要 5 个字段：分钟 小时 日 月 星期。');
      Object.assign(payload, { prompt: formString(form, 'prompt'), cron, timezone: formString(form, 'timezone'), enabled: form.has('enabled'), server_id: formString(form, 'server_id') || null, agent_id: formString(form, 'agent_id') || null, provider_id: providerId || null, model: model || null, control_level: formString(form, 'control_level') });
    }
    const path = `/admin/defaults/${kind}`;
    const response = await (item ? api.patch<DefaultResource>(`${path}/${item.id}`, payload) : api.post<DefaultResource>(path, payload));
    onSaved(response);
  };
  const providerFields = <div className="form-grid"><Field label="模型供应商"><Select label="模型供应商" value={providerId} onChange={value => { setProviderId(value); setModel(''); }} searchable options={[{ value: '', label: kind === 'agents' ? '在对话中选择' : '使用默认供应商' }, ...relations.providers.map(value => ({ value: value.id, label: value.name, description: value.enabled ? '已启用' : '已停用' }))]} /></Field><Field label="偏好模型" hint="模型名称必须与供应商实际支持的标识一致。"><Select label="偏好模型" value={model} onChange={setModel} searchable allowCustom options={[{ value: '', label: provider?.default_model ? `沿用默认：${provider.default_model}` : '沿用默认模型' }, ...(provider?.models || []).map(value => ({ value, label: value }))]} /></Field></div>;
  return <AdminForm title={`${item ? '编辑' : '新增'}默认${resourceInfo[kind].singular}`} description="逐项配置真实字段；关系选项来自平台默认目录，不依赖用户资源目录。" onClose={onClose} onSubmit={submit} scope={syncMessage} submitDisabled={needsRelations && (relations.loading || Boolean(relations.error))}>
    {needsRelations && relations.loading && <p className="ea-admin-caption" role="status">正在读取默认资源关联…</p>}
    {needsRelations && relations.error && <ErrorState message={relations.error} retry={relations.reload} />}
    <Field label={`${resourceInfo[kind].singular}名称`} required><input name="name" required maxLength={100} defaultValue={item?.name} placeholder={`为默认${resourceInfo[kind].singular}取一个清晰的名称`} /></Field>
    {!['providers', 'schedules'].includes(kind) && <Field label={kind === 'agents' ? '职责描述' : '资源描述'}><textarea name="description" rows={2} maxLength={kind === 'agents' ? 300 : 10000} defaultValue={item?.description} placeholder="适用范围、维护约定与安全边界" /></Field>}
    {kind === 'agents' && <>
      <Field label="智能体类型"><Select label="智能体类型" value={agentKind} onChange={setAgentKind} options={[{ value: 'local', label: '本地智能体', description: '在 EarthAI 中配置能力并执行', icon: <Bot size={16} /> }, { value: 'remote', label: '远程智能体', description: '仅保存 URL，通过独立站点使用', icon: <Globe size={16} /> }]} /></Field>
      <div className="form-grid"><Field label="头像文字" hint="留空使用内置机器人图标，无外链图标。"><input name="icon" defaultValue={item?.icon === 'Bot' ? '' : item?.icon} maxLength={4} placeholder="简短文字，或留空" /></Field><Field label="标识颜色" hint="六位十六进制颜色，如 #087f69。"><input name="color" pattern="#[0-9a-fA-F]{6}" required defaultValue={item?.color || '#087f69'} /></Field></div>
      <p className="ea-admin-caption">显示顺序请通过页头「调整排序」单独管理；新增智能体默认追加到末尾。</p>
      {agentKind === 'remote' ? <><Field label="远程智能体 URL" required hint="仅支持 http:// 或 https://。不会把本地凭据或对话上下文发送到该地址。"><input name="url" type="url" pattern="[Hh][Tt][Tt][Pp][Ss]?://.+" required defaultValue={item?.url || ''} placeholder="https://agent.example.com" /></Field><Banner>远程智能体只配置访问入口与展示信息，不配置本地系统指令、模型、技能、知识库或执行权限。</Banner></> : <>
        <Field label="系统指令" required hint="会真实注入所有使用此智能体的任务上下文。请审阅外部文本，防止不可信指令。"><textarea name="system_prompt" required className="mono" rows={8} defaultValue={item?.system_prompt} placeholder="定义角色、步骤、输出结构与禁止的操作…" /></Field>
        {providerFields}<Field label="默认控制等级"><ControlSelect defaultValue={item?.control_level || 'approve'} /></Field>
        <MultiSelect label="关联默认技能" name="skill_ids" options={relations.skills} selected={item?.skill_ids} />
        <MultiSelect label="关联默认知识库" name="knowledge_ids" options={relations.knowledge} selected={item?.knowledge_ids} />
      </>}
    </>}
    {kind === 'skills' && <><Field label="技能指令正文" required hint="支持纯文本和 Markdown。它是可信指令上下文，不是上传后自动执行的代码。"><textarea name="content" required rows={14} className="mono" defaultValue={item?.content} placeholder="# 适用范围\n\n# 执行步骤\n\n# 安全约束" /></Field><Switch label="启用该默认技能" name="enabled" defaultChecked={item?.enabled ?? true} /></>}
    {kind === 'knowledge' && <Banner>保存知识库后，使用卡片上的「文档管理」新增、阅读、编辑或批量删除文档。正文与索引会随默认知识库同步给所有普通用户。</Banner>}
    {kind === 'projects' && <><div className="form-grid"><Field label="标识颜色"><input name="color" required pattern="#[0-9a-fA-F]{6}" defaultValue={item?.color || '#087f69'} /></Field><Field label="项目状态"><Select label="项目状态" name="status" defaultValue={item?.status || 'active'} options={[{ value: 'active', label: '进行中' }, { value: 'archived', label: '已归档' }]} /></Field></div><MultiSelect label="关联默认服务器" name="server_ids" options={relations.servers} selected={item?.server_ids} /><MultiSelect label="关联默认知识库" name="knowledge_ids" options={relations.knowledge} selected={item?.knowledge_ids} /><MultiSelect label="关联默认技能" name="skill_ids" options={relations.skills} selected={item?.skill_ids} /></>}
    {kind === 'servers' && <>
      <Field label="连接类型"><Select label="连接类型" value={serverKind} onChange={setServerKind} options={[{ value: 'ssh', label: 'SSH 服务器' }, { value: 'kubernetes', label: 'Kubernetes 集群' }]} /></Field>
      {serverKind === 'ssh' ? <>
        <div className="form-grid form-grid-host"><Field label="主机地址" required><input name="host" required defaultValue={item?.host} placeholder="内网 IP 或主机名" /></Field><Field label="端口" required><input name="port" type="number" min={1} max={65535} defaultValue={item?.port || 22} required /></Field></div>
        <div className="form-grid"><Field label="SSH 用户名" required><input name="username" required defaultValue={item?.username} placeholder="专用的最小权限账户" /></Field><Field label="认证方式"><Select label="认证方式" value={auth} onChange={value => setAuth(value as 'key' | 'password')} options={[{ value: 'key', label: 'SSH 私钥' }, { value: 'password', label: '密码' }]} /></Field></div>
        {auth === 'key' ? <Field label="私钥内容" required={credentialRequired} hint="只写不读。编辑留空保留原私钥；更换类型或认证方式时请重新填写。"><textarea name="private_key" required={credentialRequired} rows={6} className="mono" autoComplete="off" spellCheck={false} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" /></Field> : <Field label="SSH 密码" required={credentialRequired} hint="只写不读。编辑留空保留原密码。"><input name="password" type="password" required={credentialRequired} autoComplete="new-password" placeholder={item?.has_credentials ? '已保存，留空不更改' : '请输入远程账户密码'} /></Field>}
        <Switch label="首次连接自动信任并固定主机指纹（TOFU）" checked={trust} onChange={setTrust} />
        <Field label="可信主机指纹" required={!trust} hint={trust ? '可留空：首次连接记录，后续指纹变化会拒绝连接。也可预填已核实指纹。' : '必须从独立可信渠道核对 SHA256 指纹，不能忽略校验。'}><input name="fingerprint" className="mono" pattern="SHA256:.+" required={!trust} defaultValue={item?.fingerprint} placeholder="SHA256:…" /></Field>
        <Banner tone="warning">TOFU 不能独立证明第一次连接的主机身份。请核实网络与地址；指纹变化时先排查主机更换或中间人风险，不要盲目替换。</Banner>
      </> : <><Field label="独立 kubeconfig" required={credentialRequired} hint="只写不读。编辑留空保留原值。必须包含 token 或嵌入式证书与密钥，不支持本地路径和 exec 凭据插件。"><textarea name="kubeconfig" required={credentialRequired} rows={12} className="mono" autoComplete="off" spellCheck={false} placeholder="apiVersion: v1\nkind: Config\nclusters: …" /></Field><Banner tone="warning">默认凭据会用于所有普通用户的对应默认资源。请使用经过授权、权限最小化的服务账户，谨慎共享生产集群访问能力。</Banner></>}
      <Field label="标签" hint="使用逗号或换行分隔，自动去重。"><input name="tags" defaultValue={item?.tags?.join(', ')} placeholder="生产环境, 只读账户, 华东" /></Field>
    </>}
    {kind === 'providers' && <>
      <Field label="API Base URL" required hint="填写包含 /v1 等版本路径的基础地址，不要追加 /chat/completions。"><input name="base_url" required type="url" defaultValue={item?.base_url} placeholder="https://api.example.com/v1" /></Field>
      <Field label="API Key" required={!item?.has_api_key} hint="只写不读，编辑留空保留原密钥；本地免鉴权服务可按服务要求填写占位值 local。"><input name="api_key" type="password" required={!item?.has_api_key} autoComplete="new-password" placeholder={item?.has_api_key ? '已安全保存，留空保留' : '输入真实的 API Key'} /></Field>
      <fieldset className="ea-admin-model-editor"><legend>可用模型 · 逐行管理</legend><p>模型行可留空；新建保存后自动同步一次 /models，编辑保存不会自动同步。也可手动维护，每行填写一个真实模型标识。</p>{models.map((value, index) => <div className="ea-admin-model-row" key={index}><span>{String(index + 1).padStart(2, '0')}</span><input aria-label={`模型 ${index + 1}`} value={value} onChange={event => { const next = event.target.value; setModels(current => current.map((entry, position) => position === index ? next : entry)); if (defaultModel && defaultModel === value.trim()) setDefaultModel(next.trim()); }} placeholder="model-id" /><button type="button" className="icon-button danger-text" aria-label={`删除模型第 ${index + 1} 行`} onClick={() => { const remaining = models.filter((_, position) => position !== index); setModels(remaining); if (defaultModel && defaultModel === value.trim()) setDefaultModel(remaining.find(entry => entry.trim())?.trim() || ''); }}><Trash2 size={16} /></button></div>)}<Button variant="secondary" type="button" className="button-small" onClick={() => setModels(current => [...current, ''])}><Plus size={14} />添加模型行</Button></fieldset>
      <Field label="默认模型" hint={item ? '可留空；编辑保存不会自动同步模型。模型列表非空时，后端会选用首个模型。' : '可留空；保存后自动同步模型列表，默认使用返回的首个可用模型。'}><Select label="默认模型" value={defaultModel} onChange={setDefaultModel} searchable options={[{ value: '', label: '留空，自动选择首个可用模型' }, ...[...new Set(models.map(value => value.trim()).filter(Boolean))].map(value => ({ value, label: value }))]} placeholder="可留空，或从上方模型中选择" /></Field>
      <Switch label="启用该默认供应商" name="enabled" defaultChecked={item?.enabled ?? true} />
      <Banner tone="warning">所有普通用户可能使用此供应商，模型调用会消耗真实配额。只配置可信端点；密钥不会在读取接口、模型行或预览中回显。</Banner>
    </>}
    {kind === 'schedules' && <>
      <Field label="任务目标" required hint="明确检查范围、报告格式与禁止操作。每次触发都会创建真实任务。"><textarea name="prompt" required rows={5} defaultValue={item?.prompt} placeholder="检查系统负载与磁盘，输出风险摘要，不进行任何变更。" /></Field>
      <div className="form-grid"><Field label="Cron 表达式" required hint="5 个字段：分钟 小时 日 月 星期；例如 0 9 * * *。"><input name="cron" className="mono" required defaultValue={item?.cron || '0 9 * * *'} /></Field><Field label="调度时区" required hint="支持 IANA 时区；可搜索后输入自定义时区。"><Select name="timezone" label="调度时区" required searchable allowCustom defaultValue={item?.timezone || 'Asia/Shanghai'} options={['Asia/Shanghai', 'UTC', 'Asia/Tokyo', 'Asia/Singapore', 'Europe/London', 'America/New_York'].map(value => ({ value, label: value }))} /></Field></div>
      <div className="form-grid"><Field label="目标服务器"><Select name="server_id" label="目标服务器" searchable defaultValue={item?.server_id || ''} options={[{ value: '', label: '不连接服务器' }, ...relations.servers.map(value => ({ value: value.id, label: value.name }))]} /></Field><Field label="执行智能体"><Select name="agent_id" label="执行智能体" searchable defaultValue={item?.agent_id || ''} options={[{ value: '', label: '通用运维助手' }, ...relations.agents.filter(value => value.kind !== 'remote').map(value => ({ value: value.id, label: value.name }))]} /></Field></div>
      {providerFields}<Field label="控制等级"><ControlSelect defaultValue={item?.control_level || 'approve'} /></Field>
      <Switch name="enabled" label="保存后启用全员自动调度" defaultChecked={item?.enabled ?? false} />
      <Banner tone="warning">新建默认任务默认关闭。启用前请核实供应商、模型、凭据和时区；每个普通用户都会继承并调度，可能产生多次真实调用。审批模式下变更可能等待用户确认。</Banner>
    </>}
  </AdminForm>;
}
function ResourceImport({ kind, onClose, onSaved }: { kind: ResourceKind; onClose: () => void; onSaved: () => void }) {
  const notify = useToast();
  const examples: Record<ResourceKind, string> = {
    agents: '[{"name":"巡检助手","kind":"local","description":"只读巡检","system_prompt":"先检查再分析，不进行变更。","skill_ids":[],"knowledge_ids":[],"control_level":"observe","icon":"Bot","color":"#087f69"}]',
    skills: '[{"name":"只读巡检","description":"巡检规范","content":"先检查负载、内存与磁盘，不执行变更。","enabled":true}]',
    knowledge: '[{"name":"运维手册","description":"经审阅的业务知识"}]',
    projects: '[{"name":"业务项目","description":"默认业务上下文","server_ids":[],"knowledge_ids":[],"skill_ids":[],"status":"active","color":"#087f69"}]',
    servers: '[{"name":"只读主机","kind":"ssh","host":"192.168.1.10","port":22,"username":"ops","auth_type":"key","private_key":"请填写真实私钥","trust_on_first_use":true,"tags":[]}]',
    providers: '[{"name":"团队模型","base_url":"https://api.example.com/v1","api_key":"请填写真实密钥","models":["model-id"],"default_model":"model-id","enabled":true}]',
    schedules: '[{"name":"每日巡检","prompt":"仅检查并报告，不做变更","cron":"0 9 * * *","timezone":"Asia/Shanghai","control_level":"observe","enabled":false}]',
  };
  return <AdminForm title={`批量导入${resourceInfo[kind].name}`} description="粘贴 1–200 个资源对象的 JSON 数组，也可使用含 items 数组的对象。这里是新增导入，不按同名覆盖。" scope={syncMessage} onClose={onClose} submitLabel="导入并同步" onSubmit={async form => {
    let value: unknown;
    try { value = JSON.parse(formString(form, 'json')); } catch { throw new Error('JSON 格式有误，请检查双引号、逗号和括号。'); }
    const items: unknown = Array.isArray(value) ? value : value && typeof value === 'object' && 'items' in value ? value.items : null;
    if (!Array.isArray(items) || !items.length || items.length > 200 || items.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error('请提供含 1–200 个资源对象的数组。');
    const payload = kind === 'schedules' ? items.map(item => ({ enabled: false, ...item })) : items;
    const result = await api.post<{ ok: boolean; count: number; warnings?: string[] }>(`/admin/defaults/${kind}/import`, { items: payload });
    onSaved();
    if (result.warnings?.length) notify(`配置已导入，但有 ${result.warnings.length} 个供应商未完成模型同步，请在卡片上重试或手动填写。`, 'error');
  }}><Field label="资源 JSON" required hint="关系字段请使用默认目录中的资源 ID；密钥只用于写入，请勿将含真实凭据的 JSON 发给他人。"><textarea name="json" required rows={17} className="mono" spellCheck={false} placeholder={JSON.stringify(JSON.parse(examples[kind]), null, 2)} /></Field><Banner>所有对象会由服务端验证；有无效字段或依赖时请修正后再提交。定时任务未填写 enabled 时按关闭导入。</Banner></AdminForm>;
}

function KnowledgeDocuments({ knowledge, onClose }: { knowledge: DefaultResource; onClose: () => void }) {
  const base = `/admin/defaults/knowledge/${knowledge.id}/documents`;
  const docs = useResource<AdminDocument[]>(base, []);
  const [search, setSearch] = useState(''); const [reading, setReading] = useState<AdminDocument | null>(null);
  const [edit, setEdit] = useState<AdminDocument | 'new' | null>(null);
  const selection = useSelection(docs.data); const { confirm, dialog } = useConfirm(); const notify = useToast();
  const filtered = docs.data.filter(doc => `${doc.name} ${doc.content}`.toLowerCase().includes(search.toLowerCase()));
  const remove = (ids: string[]) => confirm(`删除 ${ids.length} 份默认知识文档？`, '正文与检索片段将从仍跟随模板的用户知识库同步移除；已个人定制的知识库保留原内容。删除不能撤销，请先保留必要副本。', async () => { if (ids.length === 1) await api.delete(`${base}/${ids[0]}`); else await api.post(`${base}/batch`, { ids, action: 'delete' }); selection.clear(); dataChanged(); notify('文档已删除并同步'); });
  if (edit) return <AdminForm title={edit === 'new' ? '新增默认知识文档' : '编辑默认知识文档'} description={`所属知识库：${knowledge.name}`} scope={syncMessage} onClose={() => setEdit(null)} onSubmit={async form => {
    const payload = { name: formString(form, 'name'), content: String(form.get('content') || '') };
    if (!payload.content.trim()) throw new Error('文档正文不能为空。');
    await (edit === 'new' ? api.post(base, payload) : api.patch(`${base}/${edit.id}`, payload)); dataChanged(); notify('文档正文与索引已同步');
  }}><Field label="文档名称" required><input name="name" required maxLength={200} defaultValue={edit === 'new' ? '' : edit.name} placeholder="例如：故障响应手册.md" /></Field><Field label="文档正文" required hint="纯文本或 Markdown，不执行正文中的代码。保存后重新生成检索片段。"><textarea name="content" className="mono" rows={20} required maxLength={2000000} defaultValue={edit === 'new' ? '' : edit.content} placeholder="# 文档标题\n\n适用范围、步骤、已验证的业务信息…" /></Field></AdminForm>;
  if (reading) return <Modal title={reading.name} description={`${knowledge.name} · ${reading.content.length} 字符 · 安全 Markdown 预览`} wide onClose={() => setReading(null)}><div className="ea-admin-document-preview"><Content text={reading.content} /></div><div className="modal-footer"><Button variant="secondary" onClick={() => setReading(null)}>返回文档列表</Button><Button onClick={() => { setEdit(reading); setReading(null); }}><Pencil size={15} />编辑正文</Button></div></Modal>;
  return <><Modal title={`文档管理 · ${knowledge.name}`} description="集中维护默认文档；阅读与编辑都使用真实正文，不是摘要。" wide onClose={onClose}>
    <div className="ea-admin-documents"><Banner tone="warning">{syncMessage}</Banner><div className="ea-admin-toolbar"><SearchInput value={search} onChange={setSearch} placeholder="搜索文档名称或正文…" /><NewButton onClick={() => setEdit('new')}>新增文档</NewButton></div>
      <SelectionBar selection={selection} total={docs.data.length} visible={filtered.map(doc => doc.id)} disabled={docs.loading || Boolean(docs.error)}><Button variant="danger" className="button-small" disabled={!selection.ids.length} onClick={() => remove(selection.ids)}><Trash2 size={14} />批量删除文档</Button></SelectionBar>
      {docs.error && <ErrorState message={docs.error} retry={docs.reload} />}{docs.loading ? <Loading text="读取默认知识文档…" /> : filtered.length ? <div className="ea-admin-document-list">{filtered.map(doc => <div key={doc.id}><CheckBox label={`选择文档 ${doc.name}`} checked={selection.ids.includes(doc.id)} onChange={() => selection.toggle(doc.id)} /><FileText size={20} /><div><strong>{doc.name}</strong><span>{doc.content.length.toLocaleString()} 字符</span></div><Button variant="ghost" className="button-small" onClick={() => setReading(doc)}><Eye size={14} />查看</Button><button type="button" className="icon-button" aria-label={`编辑文档 ${doc.name}`} onClick={() => setEdit(doc)}><Pencil size={15} /></button><button type="button" className="icon-button danger-text" aria-label={`删除文档 ${doc.name}`} onClick={() => remove([doc.id])}><Trash2 size={15} /></button></div>)}</div> : <EmptyState compact icon={BookOpen} title="没有匹配的知识文档" description="可新增文本文档，或清除关键词查看全部文档。" />}
    </div><div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭文档管理</Button></div>
  </Modal>{dialog}</>;
}

export function AdminUsersPage() {
  const resource = useResource<AdminUser[]>('/admin/users', []); const { user, retry } = useAuth(); const notify = useToast();
  const [search, setSearch] = useState(''); const [role, setRole] = useState('all'); const [status, setStatus] = useState('all');
  const [edit, setEdit] = useState<AdminUser | 'new' | null>(null); const [batching, setBatching] = useState(false);
  const [applyControlLevels, setApplyControlLevels] = useState(false);
  const [applySpaceModules, setApplySpaceModules] = useState(false);
  const selection = useSelection(resource.data); const { confirm, dialog } = useConfirm();
  const isProtected = (item: AdminUser) => item.id === user?.id || item.email === 'admin';
  const protectedSelected = resource.data.some(item => selection.ids.includes(item.id) && isProtected(item));
  const filtered = resource.data.filter(item => `${item.email} ${item.name}`.toLowerCase().includes(search.toLowerCase()) && (role === 'all' || (item.role || 'user') === role) && (status === 'all' || Boolean(item.disabled) === (status === 'disabled')));
  const changed = (message: string) => { dataChanged(); notify(message); };
  const remove = (ids: string[]) => confirm(`删除 ${ids.length} 个账户及其数据？`, '账户的私有资源与相关数据会被永久删除，活跃任务会停止。此操作不是关闭空间模块或停用账户，无法撤销。团队所有者需先转交团队空间，才能删除账户。初始 admin、当前管理员以及最后一个可用管理员不能删除。', async () => { if (ids.length === 1) await api.delete(`/admin/users/${ids[0]}`); else await api.post('/admin/users/batch', { ids, action: 'delete', changes: {} }); selection.clear(); changed('账户已删除'); });
  return <div className="page ea-admin-page">
    <PageHeader eyebrow="ACCESS & ACCOUNTS" title="账户与权限" description="管理平台成员、账户可用性、角色、开放空间与可用控制模式。新账户默认仅开放个人空间、授权观察模式，并自动继承系统默认资源。" action={<NewButton onClick={() => setEdit('new')}>创建账户</NewButton>} />
    <Banner tone="warning">初始 admin 首次登录必须修改密码；系统会保留初始 admin 与至少一个可用管理员。不能删除、停用或降级当前登录管理员。管理员维护平台配置，普通用户管理自己的执行与私有资源。</Banner>
    <div className="ea-admin-toolbar"><div className="ea-admin-filter"><Select label="账户角色筛选" compact value={role} onChange={setRole} options={[{ value: 'all', label: '全部角色' }, { value: 'user', label: '普通用户' }, { value: 'admin', label: '管理员' }]} /><Select label="账户状态筛选" compact value={status} onChange={setStatus} options={[{ value: 'all', label: '全部状态' }, { value: 'active', label: '可用账户' }, { value: 'disabled', label: '已停用' }]} /></div><SearchInput value={search} onChange={setSearch} placeholder="搜索账户或姓名…" /></div>
    <SelectionBar selection={selection} total={resource.data.length} visible={filtered.map(item => item.id)} disabled={resource.loading || Boolean(resource.error)}><Button variant="secondary" className="button-small" disabled={!selection.ids.length} onClick={() => { setApplyControlLevels(false); setApplySpaceModules(false); setBatching(true); }}><Pencil size={14} />批量账户配置</Button><Button variant="danger" className="button-small" disabled={!selection.ids.length || protectedSelected} title={protectedSelected ? '已选账户包含受保护管理员' : undefined} onClick={() => remove(selection.ids)}><Trash2 size={14} />批量删除</Button></SelectionBar>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading text="读取平台账户…" /> : !filtered.length ? <EmptyState compact icon={Users} title="没有匹配的账户" description="请调整角色、状态或搜索关键词。" /> : <div className="ea-admin-user-list">{filtered.map(item => <article className="ea-admin-user-row" key={item.id}>
      <CheckBox label={`选择账户 ${item.email}`} checked={selection.ids.includes(item.id)} onChange={() => selection.toggle(item.id)} /><span className="ea-admin-user-avatar">{initials(item.name)}</span><div className="ea-admin-user-identity"><strong>{item.name || '未命名用户'}{item.id === user?.id && <span>当前账户</span>}</strong><p>{item.email}</p><div className="ea-admin-user-control-levels" aria-label="已授权控制模式"><span>授权模式</span>{(item.allowed_control_levels ?? allControlLevels).map(level => <span className="ea-admin-pill is-enabled" key={level}>{controlLabels[level]}</span>)}{item.role === 'admin' && <span className="ea-admin-user-control-note">管理员不执行任务</span>}</div><div className="ea-admin-user-space-modules" aria-label="已开放空间模块"><span>开放空间</span>{(item.space_modules ?? defaultSpaceModules).map(module => <span className="ea-admin-pill is-enabled" key={module} data-space-module={module}>{spaceModuleLabels[module]}</span>)}{!(item.space_modules ?? defaultSpaceModules).length && <span className="ea-admin-pill is-warning">全部暂停</span>}{item.team_invites_blocked && <span className="ea-admin-user-space-note">团队邀请已阻止，需管理员重新开放</span>}</div>{item.created_at && <small>创建于 {dateTime(item.created_at)}</small>}</div><div className="ea-admin-user-badges"><span className={`ea-admin-pill${item.role === 'admin' ? ' is-enabled' : ''}`}>{item.role === 'admin' ? '管理员' : '普通用户'}</span><span className={`ea-admin-pill${item.disabled ? ' is-danger' : ''}`}>{item.disabled ? '已停用' : '可登录'}</span>{item.must_change_password && <span className="ea-admin-pill is-warning"><KeyRound size={12} />待强制改密</span>}</div><div className="ea-admin-row-actions"><Button variant="ghost" className="button-small" onClick={() => setEdit(item)}><Pencil size={14} />编辑</Button><button type="button" className="icon-button danger-text" disabled={isProtected(item)} title={isProtected(item) ? '初始 admin 或当前管理员不可删除' : '删除账户及其数据'} aria-label={`删除账户 ${item.email}`} onClick={() => remove([item.id])}><Trash2 size={16} /></button></div>
    </article>)}</div>}
    {edit && <UserForm item={edit === 'new' ? null : edit} protectedAccount={edit !== 'new' && isProtected(edit)} onClose={() => setEdit(null)} onSaved={async () => { changed('账户配置已保存'); if (edit !== 'new' && edit.id === user?.id) await retry(); }} />}
    {batching && <AdminForm title={`批量修改 ${selection.ids.length} 个账户`} scope="账户角色、停用状态、授权控制模式与开放空间会立即生效。授权与空间的统一修改开关相互独立，未勾选则保持各账户原值。停用、删除或转为管理员可能中止普通用户运行；团队所有者需先转交团队空间，才能转为管理员。关闭空间模块不删除个人文件或团队资源，可重新开放恢复访问。" onClose={() => setBatching(false)} submitLabel="保存账户变更" onSubmit={async form => {
      const nextRole = formString(form, 'role'); const disabled = formString(form, 'disabled');
      const applyPermissions = form.has('apply_control_levels'); const allowedControlLevels = formList(form, 'allowed_control_levels');
      const applyModules = form.has('apply_space_modules');
      if (!nextRole && !disabled && !applyPermissions && !applyModules) throw new Error('请选择要修改的角色、账户状态、授权控制模式或开放空间。');
      if (applyPermissions && !allowedControlLevels.length) throw new Error('请至少授权一种控制模式。');
      if (protectedSelected && ((nextRole && nextRole !== 'admin') || disabled === 'true')) throw new Error('所选账户包含初始 admin 或当前管理员，不能停用或降级，请调整选择。');
      const changes = { ...(nextRole ? { role: nextRole } : {}), ...(disabled ? { disabled: disabled === 'true' } : {}), ...(applyPermissions ? { allowed_control_levels: allowedControlLevels } : {}), ...(applyModules ? { space_modules: formList(form, 'space_modules') } : {}) };
      await api.post('/admin/users/batch', { ids: selection.ids, action: 'update', changes }); selection.clear(); changed('账户批量变更已保存');
    }}>
      <Field label="统一角色"><Select label="统一角色" name="role" defaultValue="" options={[{ value: '', label: '保持原角色' }, { value: 'user', label: '普通用户' }, { value: 'admin', label: '管理员' }]} /></Field>
      <Field label="统一账户状态"><Select label="统一账户状态" name="disabled" defaultValue="" options={[{ value: '', label: '保持原状态' }, { value: 'false', label: '全部启用登录' }, { value: 'true', label: '全部停用登录' }]} /></Field>
      <Switch label="统一修改授权控制模式" name="apply_control_levels" checked={applyControlLevels} onChange={setApplyControlLevels} />
      <ControlLevelPermissions disabled={!applyControlLevels} />
      <div className="ea-admin-space-batch">
        <Switch label="统一修改开放空间（未勾选保持不变）" name="apply_space_modules" checked={applySpaceModules} onChange={setApplySpaceModules} />
        <SpaceModulePermissions disabled={!applySpaceModules} />
      </div>
      {protectedSelected && <Banner tone="warning">选择中包含受保护管理员，可保留或启用，但不能停用、降级或删除。仍可保存授权控制模式与开放空间，管理员不执行任务。服务端还会校验至少保留一位可用管理员。</Banner>}
    </AdminForm>}
    {dialog}
  </div>;
}
function UserForm({ item, protectedAccount, onClose, onSaved }: { item: AdminUser | null; protectedAccount: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  return <AdminForm title={item ? '编辑账户' : '创建账户'} description="支持账号、姓名、密码、角色、停用状态、开放空间与授权控制模式。密码不会回显。" onClose={onClose} scope="这是平台账户管理，不是个人设置。新账户默认仅开放个人空间、授权观察模式并继承默认资源；旧账户缺少空间配置时按仅个人空间显示，明确关闭全部空间则保留关闭状态。旧账户缺少模式授权时按三种模式显示；授权不改变个人默认控制等级。团队所有者需先转交团队空间，才能转为管理员或永久删除账户。" submitLabel={item ? '保存账户' : '创建账户'} onSubmit={async form => {
    const password = String(form.get('password') || '');
    if ((!item || password) && password.length < 8) throw new Error('密码至少需要 8 个字符。');
    const allowedControlLevels = formList(form, 'allowed_control_levels');
    if (!allowedControlLevels.length) throw new Error('请至少授权一种控制模式。');
    const payload = { email: formString(form, 'email'), name: formString(form, 'name'), role: protectedAccount ? 'admin' : formString(form, 'role'), disabled: protectedAccount ? false : form.has('disabled'), allowed_control_levels: allowedControlLevels, space_modules: formList(form, 'space_modules'), ...(!item || password ? { password } : {}) };
    await (item ? api.patch(`/admin/users/${item.id}`, payload) : api.post('/admin/users', payload)); await onSaved();
  }}>
    <div className="form-grid"><Field label="登录账号 / 邮箱" required hint={item?.email === 'admin' ? '初始 admin 账号不可更名。' : '普通账号请使用有效邮箱，登录时使用此账号。'}><input name="email" type="text" inputMode="email" required maxLength={254} readOnly={item?.email === 'admin'} defaultValue={item?.email} placeholder="member@example.com" autoComplete="off" /></Field><Field label="显示名称" required><input name="name" required maxLength={80} defaultValue={item?.name} placeholder="成员姓名或团队名称" /></Field></div>
    <Field label={item ? '重设密码' : '初始密码'} required={!item} hint={item ? '至少 8 位；留空不更改。重设后请通过安全渠道告知成员。' : '至少 8 位，请避免复用其他系统的密码。'}><input name="password" type="password" minLength={8} required={!item} autoComplete="new-password" placeholder={item ? '留空保留原密码' : '至少 8 个字符'} /></Field>
    <Field label="角色"><Select label="账户角色" name="role" disabled={protectedAccount} defaultValue={item?.role || 'user'} options={[{ value: 'user', label: '普通用户', description: '使用默认资源并维护自己的工作空间' }, { value: 'admin', label: '管理员', description: '管理平台账户、默认资源、告警与品牌' }]} /></Field>
    <ControlLevelPermissions selected={item ? item.allowed_control_levels ?? allControlLevels : ['observe']} />
    <SpaceModulePermissions selected={item?.space_modules ?? defaultSpaceModules} />
    {item?.team_invites_blocked && <Banner tone="warning">此账户的团队空间已被管理员停用，不能通过邀请自动恢复。重新勾选团队空间并保存后，将解除邀请阻止；原有团队资源不会被删除。</Banner>}
    <fieldset className="ea-admin-plain-fieldset" disabled={protectedAccount}><Switch label="停用此账户的登录与使用" name="disabled" defaultChecked={item?.disabled ?? false} /></fieldset>
    {protectedAccount && <Banner>这是初始 admin 或当前登录管理员，角色与可用状态受保护；仍可维护姓名、密码、开放空间和授权控制模式。</Banner>}{item?.must_change_password && <Banner tone="warning">此账号处于强制改密状态，登录后需完成密码修改才可进入平台。</Banner>}
  </AdminForm>;
}

const severityOptions = [{ value: 'critical', label: '严重 · 影响核心业务' }, { value: 'warning', label: '警告 · 需要关注' }, { value: 'info', label: '提示 · 记录信息' }];
const alertStatusOptions = [{ value: 'open', label: '待处理' }, { value: 'resolved', label: '已解决' }];
export function AdminAlertsPage() {
  const resource = useResource<OwnedAlert[]>('/admin/alerts', []); const notify = useToast();
  const [search, setSearch] = useState(''); const [status, setStatus] = useState('all'); const [severity, setSeverity] = useState('all');
  const [edit, setEdit] = useState<OwnedAlert | null>(null); const [batching, setBatching] = useState(false);
  const selection = useSelection(resource.data); const { confirm, dialog } = useConfirm();
  const filtered = resource.data.filter(item => (status === 'all' || item.status === status) && (severity === 'all' || item.severity === severity) && `${item.title} ${item.description} ${item.source} ${item.owner_email} ${item.owner_id}`.toLowerCase().includes(search.toLowerCase()));
  const changed = (message: string) => { dataChanged(); notify(message); };
  const remove = (ids: string[]) => confirm(`永久删除 ${ids.length} 条告警？`, '这会删除所属用户的原始告警，而不是仅从管理员视图隐藏。需要保留处理轨迹时，建议改为标记已解决。', async () => { if (ids.length === 1) await api.delete(`/admin/alerts/${ids[0]}`); else await api.post('/admin/alerts/batch', { ids, action: 'delete', changes: {} }); selection.clear(); changed('告警已删除'); });
  return <div className="page ea-admin-page"><PageHeader eyebrow="PLATFORM SIGNALS" title="全员告警管理" description="按所属账户统一审阅、编辑和处理真实告警。管理员不在这里发起 AI 诊断或以用户身份执行任务。" />
    <div className="ea-admin-alert-counts">{severityOptions.map(option => <button type="button" className={`ea-admin-alert-stat severity-${option.value}${severity === option.value ? ' is-selected' : ''}`} key={option.value} onClick={() => setSeverity(current => current === option.value ? 'all' : option.value)}><Bell size={20} /><div><strong>{resource.data.filter(item => item.severity === option.value && item.status === 'open').length}</strong><span>{option.label.split(' · ')[0]} · 待处理</span></div></button>)}</div>
    <div className="ea-admin-toolbar"><div className="ea-admin-filter"><Select label="告警状态筛选" compact value={status} onChange={setStatus} options={[{ value: 'all', label: '全部状态' }, ...alertStatusOptions]} /><Select label="告警严重度筛选" compact value={severity} onChange={setSeverity} options={[{ value: 'all', label: '全部严重度' }, ...severityOptions]} /></div><SearchInput value={search} onChange={setSearch} placeholder="搜索标题、内容或所属账户…" /></div>
    <SelectionBar selection={selection} total={resource.data.length} visible={filtered.map(item => item.id)} disabled={resource.loading || Boolean(resource.error)}><Button variant="secondary" className="button-small" disabled={!selection.ids.length} onClick={() => setBatching(true)}><Pencil size={14} />批量状态 / 严重度</Button><Button variant="danger" className="button-small" disabled={!selection.ids.length} onClick={() => remove(selection.ids)}><Trash2 size={14} />批量删除</Button></SelectionBar>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading text="读取全平台告警…" /> : !filtered.length ? <div className="panel"><EmptyState compact icon={Bell} title="当前视图没有告警" description="可调整筛选或搜索。这里不会生成模拟告警或诊断结果。" /></div> : <div className="ea-admin-alert-list">{filtered.map(item => <article className={`ea-admin-alert-row severity-${item.severity}`} key={item.id}><CheckBox label={`选择告警 ${item.title}`} checked={selection.ids.includes(item.id)} onChange={() => selection.toggle(item.id)} /><div className="ea-admin-alert-main"><div><h2>{item.title}</h2><span className={`severity-label severity-${item.severity}`}>{({ critical: '严重', warning: '警告', info: '提示' })[item.severity]}</span><StatusBadge status={item.status} /></div><p>{item.description || '未填写问题描述'}</p><div className="ea-admin-alert-owner"><Users size={13} /><strong>{item.owner_email}</strong><span title={`owner_id: ${item.owner_id}`}>所属用户 ID：{item.owner_id}</span></div><small>{item.source || '未注明来源'} · {dateTime(item.created_at)}</small></div><div className="ea-admin-alert-actions"><AsyncButton variant="secondary" className="button-small" action={async () => { await api.patch(`/admin/alerts/${item.id}`, { status: item.status === 'open' ? 'resolved' : 'open' }); changed(item.status === 'open' ? '告警已标记解决' : '告警已重新打开'); }}><CheckCircle2 size={14} />{item.status === 'open' ? '标记解决' : '重新打开'}</AsyncButton><Button variant="ghost" className="button-small" onClick={() => setEdit(item)}><Pencil size={14} />编辑</Button><button type="button" className="icon-button danger-text" aria-label={`删除告警 ${item.title}`} onClick={() => remove([item.id])}><Trash2 size={15} /></button></div></article>)}</div>}
    {edit && <AdminForm title="编辑用户告警" description={`所属账户：${edit.owner_email} · ${edit.owner_id}`} scope="保存会直接修改所属用户的真实告警。不会改变所属账户、来源或运行关联，也不会发起诊断。" onClose={() => setEdit(null)} submitLabel="保存告警" onSubmit={async form => { await api.patch(`/admin/alerts/${edit.id}`, { title: formString(form, 'title'), description: formString(form, 'description'), severity: formString(form, 'severity'), status: formString(form, 'status') }); changed('告警已更新'); }}><Field label="告警标题" required><input name="title" required maxLength={160} defaultValue={edit.title} /></Field><div className="form-grid"><Field label="严重度"><Select name="severity" label="告警严重度" defaultValue={edit.severity} options={severityOptions} /></Field><Field label="处理状态"><Select name="status" label="告警处理状态" defaultValue={edit.status} options={alertStatusOptions} /></Field></div><Field label="问题描述"><textarea name="description" rows={7} maxLength={60000} defaultValue={edit.description} /></Field></AdminForm>}
    {batching && <AdminForm title={`批量修改 ${selection.ids.length} 条告警`} scope="所有修改会直接反映在所属用户的告警中。只更新已选择的字段，不运行任何诊断。" onClose={() => setBatching(false)} submitLabel="应用批量修改" onSubmit={async form => {
      const changes: Record<string, string> = {}; const nextStatus = formString(form, 'status'); const nextSeverity = formString(form, 'severity');
      if (nextStatus) changes.status = nextStatus; if (nextSeverity) changes.severity = nextSeverity;
      if (form.has('apply_description')) changes.description = formString(form, 'description');
      if (!Object.keys(changes).length) throw new Error('请至少选择状态、严重度或替换描述中的一项。');
      await api.post('/admin/alerts/batch', { ids: selection.ids, action: 'update', changes }); selection.clear(); changed('告警批量修改已保存');
    }}><Field label="统一状态"><Select name="status" label="统一告警状态" defaultValue="" options={[{ value: '', label: '保持不变' }, ...alertStatusOptions]} /></Field><Field label="统一严重度"><Select name="severity" label="统一告警严重度" defaultValue="" options={[{ value: '', label: '保持不变' }, ...severityOptions]} /></Field><Switch name="apply_description" label="统一替换描述（留空清空）" /><Field label="新的描述"><textarea name="description" rows={4} maxLength={60000} /></Field></AdminForm>}
    {dialog}
  </div>;
}

interface Branding {
  name: string; subtitle: string; tagline: string; icon_url: string; favicon_url: string;
  title_font_family: string; title_font_size: number; title_color: string;
  subtitle_font_family: string; subtitle_font_size: number; subtitle_color: string;
}
const brandingDefaults: Branding = { name: 'EarthAI', subtitle: 'WORKSPACE', tagline: '智能运维 · 可靠执行', icon_url: '', favicon_url: '/favicon.ico', title_font_family: 'DM Sans', title_font_size: 23, title_color: '#253c34', subtitle_font_family: 'DM Sans', subtitle_font_size: 8, subtitle_color: '#76837b' };
const brandingFonts = ['DM Sans', 'Noto Sans SC', 'system-ui', 'serif', 'monospace'];
function validateBranding(value: unknown): Branding {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('品牌配置必须是完整的 JSON 对象。');
  const data = value as Record<string, unknown>;
  const keys = Object.keys(brandingDefaults);
  if (Object.keys(data).some(key => !keys.includes(key)) || keys.some(key => !(key in data))) throw new Error('请导入完整的品牌配置，字段必须与导出的 JSON 一致。');
  for (const [key, maximum] of [['name', 40], ['subtitle', 40], ['tagline', 120]] as const) if (typeof data[key] !== 'string' || !data[key].trim() || data[key].length > maximum) throw new Error(`${key} 不能为空，最多 ${maximum} 个字符。`);
  for (const key of ['title_font_family', 'subtitle_font_family']) if (typeof data[key] !== 'string' || !brandingFonts.includes(data[key])) throw new Error('字体只能选择内置字体或系统字体。');
  for (const [key, minimum, maximum] of [['title_font_size', 14, 40], ['subtitle_font_size', 6, 24]] as const) if (typeof data[key] !== 'number' || !Number.isInteger(data[key]) || data[key] < minimum || data[key] > maximum) throw new Error(`${key} 必须为 ${minimum}–${maximum} 的整数。`);
  for (const key of ['title_color', 'subtitle_color']) if (typeof data[key] !== 'string' || !/^#[\da-f]{6}$/i.test(data[key])) throw new Error('颜色必须为 # 加六位十六进制数。');
  for (const key of ['icon_url', 'favicon_url']) if (typeof data[key] !== 'string' || (data[key] !== '' && data[key] !== '/favicon.ico' && !/^\/api\/branding\/assets\/[a-f0-9-]+\.(png|ico|webp|jpg)$/.test(data[key]))) throw new Error('图标只允许本机已上传的品牌资源，禁止外链、SVG 和 data URL。');
  return data as unknown as Branding;
}
export function BrandingPage() {
  const resource = useResource<Branding | null>('/branding', null);
  return <div className="page ea-admin-page"><PageHeader eyebrow="YOUR PLATFORM, YOUR IDENTITY" title="界面与品牌" description="在一处维护平台名称、字体、颜色与本地图标。整套配置保存后对登录页与所有账户生效。" />{resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading && !resource.data ? <Loading text="读取品牌配置…" /> : resource.data && <BrandingEditor key={JSON.stringify(resource.data)} initial={resource.data} onSaved={resource.setData} />}</div>;
}
function BrandingEditor({ initial, onSaved }: { initial: Branding; onSaved: (value: Branding) => void }) {
  const [draft, setDraft] = useState<Branding>({ ...initial }); const [busy, setBusy] = useState(false); const [uploading, setUploading] = useState('');
  const [error, setError] = useState(''); const [importing, setImporting] = useState(false); const notify = useToast();
  const { confirm, dialog } = useConfirm(); const formRef = useRef<HTMLFormElement>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const set = <K extends keyof Branding,>(key: K, value: Branding[K]) => setDraft(current => ({ ...current, [key]: value }));
  const persist = async (value: Branding) => {
    const valid = validateBranding(value); const next = await api.patch<Branding>('/admin/branding', valid);
    window.dispatchEvent(new CustomEvent('earthai:branding-changed', { detail: next })); onSaved(next); notify('整套品牌配置已保存，对所有账户生效');
  };
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('');
    try { await persist(draft); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  const upload = async (key: 'icon_url' | 'favicon_url', file: File) => {
    setError(''); setUploading(key);
    try {
      if (!file.size || file.size > 2 * 1024 * 1024 || !/\.(png|ico|jpe?g|webp)$/i.test(file.name)) throw new Error('请选择不超过 2MB 的 PNG、ICO、JPEG 或 WebP 文件。');
      const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer());
      const png = [137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value);
      const ico = [0, 0, 1, 0].every((value, index) => bytes[index] === value);
      const jpg = bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
      const webp = String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP';
      if (!png && !ico && !jpg && !webp) throw new Error('文件内容不是支持的图片格式，不接受重命名的 SVG 或脚本。');
      const result = await api.upload<{ url: string }>('/admin/branding/assets', file);
      validateBranding({ ...draft, [key]: result.url }); set(key, result.url); notify('本地图标已上传，保存整套配置后全员生效');
    } catch (err) { setError(errorMessage(err)); }
    finally { setUploading(''); }
  };
  const exportJson = () => {
    try {
      const value = validateBranding(draft); const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'earthai-branding.json'; document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); notify('已导出当前整套草稿；图片文件仍保存在本机');
    } catch (err) { setError(errorMessage(err)); }
  };
  const fontStyle = (font: string) => font === 'DM Sans' || font === 'Noto Sans SC' ? `'${font}', 'Noto Sans SC', sans-serif` : font;
  return <>
    <Banner>所有品牌字段作为一整套配置管理。预览和 JSON 导入仅修改草稿；点击「保存整套配置」后全员生效。图片只从本机上传，不访问外部图标或字体服务。</Banner>
    <div className="ea-branding-batch"><span><Palette size={18} /><strong>整套配置</strong><small>{dirty ? '有未保存的修改' : '已与平台同步'}</small></span><div><Button variant="secondary" className="button-small" disabled={busy || Boolean(uploading)} onClick={() => setImporting(true)}><Upload size={14} />JSON 导入</Button><Button variant="secondary" className="button-small" onClick={exportJson}><Download size={14} />JSON 导出</Button><Button variant="ghost" className="button-small" disabled={busy || Boolean(uploading)} onClick={() => confirm('恢复平台默认品牌？', '将恢复 EarthAI 名称、默认字体、颜色与内置图标，并立即保存到平台，对所有账户生效。当前未保存草稿会被替换，上传过的图片不会在此操作中删除。', () => persist({ ...brandingDefaults }))}><RotateCcw size={14} />恢复默认</Button></div></div>
    <form ref={formRef} className="ea-branding-grid" onSubmit={event => { void save(event); }}>
      <div className="ea-branding-fields"><fieldset className="panel ea-admin-panel" disabled={busy || Boolean(uploading)}><SectionTitle title="品牌文字" subtitle="名称、副标题与宣传语会出现在平台的品牌区域。" /><div className="form-grid"><Field label="平台名称" required><input value={draft.name} required maxLength={40} onChange={event => set('name', event.target.value)} /></Field><Field label="品牌副标题" required><input value={draft.subtitle} required maxLength={40} onChange={event => set('subtitle', event.target.value)} /></Field></div><Field label="宣传语" required><input value={draft.tagline} required maxLength={120} onChange={event => set('tagline', event.target.value)} /></Field></fieldset>
      <fieldset className="panel ea-admin-panel" disabled={busy || Boolean(uploading)}><SectionTitle title="字体与颜色" subtitle="仅提供已内置或系统字体，无需访问外部字体站点。" /><div className="ea-branding-type-group"><h3>主标题</h3><div className="form-grid"><Field label="标题字体"><Select label="标题字体" value={draft.title_font_family} onChange={value => set('title_font_family', value)} options={brandingFonts.map(value => ({ value, label: value }))} /></Field><Field label="标题字号（14–40 px）"><input type="number" min={14} max={40} step={1} required value={draft.title_font_size} onChange={event => set('title_font_size', Number(event.target.value))} /></Field></div><Field label="标题颜色" hint="格式：#RRGGBB，必须填写完整六位颜色。"><div className="ea-branding-color"><span style={{ background: /^#[\da-f]{6}$/i.test(draft.title_color) ? draft.title_color : 'transparent' }} /><input value={draft.title_color} required pattern="#[0-9a-fA-F]{6}" maxLength={7} onChange={event => set('title_color', event.target.value)} aria-label="标题六位十六进制颜色" /></div></Field></div><div className="ea-branding-type-group"><h3>副标题</h3><div className="form-grid"><Field label="副标题字体"><Select label="副标题字体" value={draft.subtitle_font_family} onChange={value => set('subtitle_font_family', value)} options={brandingFonts.map(value => ({ value, label: value }))} /></Field><Field label="副标题字号（6–24 px）"><input type="number" min={6} max={24} step={1} required value={draft.subtitle_font_size} onChange={event => set('subtitle_font_size', Number(event.target.value))} /></Field></div><Field label="副标题颜色"><div className="ea-branding-color"><span style={{ background: /^#[\da-f]{6}$/i.test(draft.subtitle_color) ? draft.subtitle_color : 'transparent' }} /><input value={draft.subtitle_color} required pattern="#[0-9a-fA-F]{6}" maxLength={7} onChange={event => set('subtitle_color', event.target.value)} aria-label="副标题六位十六进制颜色" /></div></Field></div></fieldset>
      <fieldset className="panel ea-admin-panel" disabled={busy || Boolean(uploading)}><SectionTitle title="本地图标" subtitle="PNG / ICO / JPEG / WebP，单个文件不超过 2MB；不支持 SVG 或外部 URL。" />{(['icon_url', 'favicon_url'] as const).map(key => <div className="ea-branding-asset" key={key}><span className="ea-branding-asset-image">{draft[key] ? <img src={draft[key]} alt={key === 'icon_url' ? '当前平台图标' : '当前网站图标'} /> : <Activity size={25} />}</span><div><strong>{key === 'icon_url' ? '平台图标' : '浏览器网站图标（Favicon）'}</strong><p>{draft[key] || '使用内置 EarthAI 图标'}</p><label className="button button-secondary button-small ea-branding-upload"><Upload size={14} />{uploading === key ? '正在上传…' : '选择本地图片'}<input type="file" accept=".png,.ico,.jpg,.jpeg,.webp,image/png,image/x-icon,image/vnd.microsoft.icon,image/jpeg,image/webp" aria-label={key === 'icon_url' ? '上传平台图标' : '上传网站图标'} disabled={busy || Boolean(uploading)} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(key, file); }} /></label></div><button type="button" className="icon-button" aria-label={key === 'icon_url' ? '恢复内置平台图标' : '恢复内置网站图标'} onClick={() => set(key, brandingDefaults[key])}><X size={16} /></button></div>)}</fieldset>
      {error && <div className="inline-error" role="alert">{error}</div>}<div className="ea-branding-save"><span>{dirty ? '草稿尚未应用到其他账户' : '整套配置已保存'}{uploading && ' · 正在上传图片'}</span><Button type="submit" busy={busy} disabled={Boolean(uploading)}><Save size={16} />保存整套配置</Button></div></div>
      <aside className="ea-branding-preview"><div className="ea-branding-preview-heading"><Eye size={16} /><span>实时预览</span><small>保存前仅你可见</small></div><div className="ea-branding-browser"><span>{draft.favicon_url ? <img src={draft.favicon_url} alt="网站图标预览" /> : <Globe size={13} />}{draft.name || '平台名称'}</span><i /><i /><i /></div><div className="ea-branding-preview-surface"><div className="ea-branding-preview-brand"><span className="ea-branding-preview-logo">{draft.icon_url ? <img src={draft.icon_url} alt="平台图标预览" /> : <Activity size={34} />}</span><div><strong style={{ fontFamily: fontStyle(draft.title_font_family), fontSize: draft.title_font_size, color: draft.title_color }}>{draft.name || '平台名称'}</strong><span style={{ fontFamily: fontStyle(draft.subtitle_font_family), fontSize: draft.subtitle_font_size, color: draft.subtitle_color }}>{draft.subtitle || '副标题'}</span></div></div><div className="ea-branding-preview-divider" /><span className="eyebrow">WELCOME TO YOUR WORKSPACE</span><h2>专业的工具，<br />有自己的表达。</h2><p>{draft.tagline || '品牌宣传语'}</p><div className="ea-branding-preview-skeleton"><span /><span /><span /></div><div className="ea-branding-preview-note"><ShieldCheck size={15} />本地图标 · 本地字体 · 全员一致</div></div><p className="ea-admin-caption">此处预览品牌效果，不会提交登录或创建账户。深浅主题下请分别检查文字对比度；浏览器网站图标可能有缓存。</p></aside>
    </form>
    {importing && <AdminForm title="导入整套品牌配置" description="粘贴此前导出的完整 JSON。图标资源须已存在于本机；跨服务器迁移时请重新上传图片。" scope="导入只替换本页草稿，不会立即改变平台。预览确认后需点击保存整套配置。" onClose={() => setImporting(false)} submitLabel="导入到草稿" onSubmit={async form => { let value: unknown; try { value = JSON.parse(formString(form, 'json')); } catch { throw new Error('JSON 格式错误，请检查引号、逗号与括号。'); } setDraft({ ...validateBranding(value) }); setError(''); notify('整套配置已导入草稿，请预览后保存'); }}><Field label="品牌配置 JSON" required><textarea name="json" required rows={16} className="mono" spellCheck={false} placeholder={JSON.stringify(brandingDefaults, null, 2)} /></Field></AdminForm>}
    {dialog}
  </>;
}
