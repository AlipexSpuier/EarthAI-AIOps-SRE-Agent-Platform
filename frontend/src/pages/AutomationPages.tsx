import { useEffect, useState } from 'react';
import { Bell, CalendarClock, Check, CheckCircle2, ChevronRight, Clock3, Eye, History, Pencil, Play, Server, ShieldCheck, Sparkles, Trash2, TriangleAlert } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useCatalog } from '../context/CatalogContext';
import { useExecutions } from '../context/ExecutionContext';
import { useToast } from '../context/ToastContext';
import { api, errorMessage } from '../lib/api';
import { dateTime, relativeTime } from '../lib/format';
import { canUseControl, fallbackControl } from '../lib/controlAccess';
import { dataChanged, useResource } from '../lib/hooks';
import type { Agent, Alert, ControlLevel, RunLaunch, Schedule, User } from '../types';
import { UserResourceImportButton } from '../components/UserResourceImport';
import { Select } from '../components/Select';
import { AsyncButton, Banner, Button, ControlBadge, ControlSelect, EmptyState, ErrorState, Field, FormDialog, Loading, Modal, NewButton, PageHeader, SearchInput, StatusBadge, Switch, formString, useConfirm } from '../components/ui';
import './ResourcePermissions.css';
import './ExecutionPermissions.css';

function scheduleExecutionReason(user: User | null, schedule: Pick<Schedule, 'control_level' | 'agent_id'>, agents: Agent[]): string {
  if (user?.role === 'admin') return '管理员账户不能执行本地任务。';
  if (!canUseControl(user, schedule.control_level)) return '管理员未授权此任务的控制等级，可编辑为已授权等级。';
  if (schedule.agent_id) {
    const agent = agents.find(item => item.id === schedule.agent_id);
    if (!agent || agent.kind === 'remote') return '关联智能体已移除或属于远程智能体，请编辑任务重新选择。';
    if (!canUseControl(user, agent.control_level)) return '管理员未授权关联智能体的控制等级，请编辑任务重新选择。';
  }
  return '';
}

export function SchedulesPage() {
  const resource = useResource<Schedule[]>('/schedules', []); const catalog = useCatalog(); const { user } = useAuth();
  const [edit, setEdit] = useState<Schedule | 'new' | null>(null); const [view, setView] = useState<Schedule | null>(null); const [search, setSearch] = useState('');
  const { confirm, dialog } = useConfirm(); const notify = useToast(); const navigate = useNavigate(); const { watch } = useExecutions();
  const blockedReason = (schedule: Schedule) => catalog.loading ? '正在检查智能体控制等级授权…' : scheduleExecutionReason(user, schedule, catalog.agents);
  const launch = async (schedule: Schedule) => {
    const reason = blockedReason(schedule);
    if (reason) throw new Error(reason);
    const result = await api.post<RunLaunch>(`/schedules/${schedule.id}/run`);
    await watch(result.run_id).catch(() => undefined); dataChanged(); navigate(`/chat/${result.conversation_id}?run=${result.run_id}`);
  };
  return <div className="page">
    <PageHeader eyebrow="AUTOMATION, WITH INTENTION" title="把规律的事，放心交给时间" description="以 Cron 计划调度真实智能体任务，重复工作也能有条不紊。" action={<><UserResourceImportButton kind="schedules" label="定时任务" /><NewButton onClick={() => setEdit('new')}>创建定时任务</NewButton></>} />
    <div className="schedule-summary"><div className="schedule-summary-count"><strong>{resource.data.filter(schedule => schedule.enabled).length}</strong><span>个任务已启用</span></div><div className="schedule-timezone"><Clock3 size={15} />Asia/Shanghai</div></div>
    <div className="list-toolbar"><span className="muted small">{resource.data.length} 个计划任务 · 所有时间按本地浏览器显示</span><SearchInput value={search} onChange={setSearch} placeholder="搜索任务名称…" /></div>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}
    {resource.loading ? <Loading /> : !resource.data.length ? <div className="panel"><EmptyState compact icon={CalendarClock} title="把第一件重复工作自动化" description="创建一个定时巡检，让智能体在指定时间检查服务状态，保留可审阅的真实执行记录。" /></div> : <div className="schedule-list">{resource.data.filter(schedule => `${schedule.name} ${schedule.prompt}`.toLowerCase().includes(search.toLowerCase())).map(schedule => {
      const reason = blockedReason(schedule);
      return <article className={`schedule-card ${schedule.enabled ? '' : 'schedule-disabled'}${reason ? ' control-permission-disabled' : ''}`} key={schedule.id} data-schedule-id={schedule.id} data-control-blocked={Boolean(reason) || undefined}>
        <div className="schedule-card-aside"><CalendarClock size={23} /><span>{schedule.enabled ? '已启用' : '已暂停'}</span></div>
        <div className="schedule-card-main">
          <div className="schedule-card-title"><h3>{schedule.name}</h3><ControlBadge level={schedule.control_level} />{schedule.read_only ? <span className="ea-resource-read-only">系统默认 · 只读</span> : <fieldset className={`control-permission-switch${!schedule.enabled && reason ? ' control-permission-disabled' : ''}`} disabled={!schedule.enabled && Boolean(reason)} title={reason || undefined}><Switch checked={schedule.enabled} label={schedule.enabled ? '启用中' : '已停用'} onChange={enabled => {
            if (schedule.read_only) return;
            if (enabled && blockedReason(schedule)) { notify(blockedReason(schedule), 'error'); return; }
            void api.patch(`/schedules/${schedule.id}`, { enabled }).then(() => { dataChanged(); notify(enabled ? '调度已开启' : '调度已暂停'); }).catch(err => notify(errorMessage(err), 'error'));
          }} /></fieldset>}</div>
          {reason && <p className="control-permission-note">{reason}{schedule.enabled && !schedule.read_only ? '仍可停用此任务。' : ''}</p>}
          <p className="schedule-prompt">{schedule.prompt}</p>
          <div className="schedule-metadata"><code>{schedule.cron}</code><span><Clock3 size={12} />{schedule.timezone}</span><span><Server size={12} />{catalog.servers.find(server => server.id === schedule.server_id)?.name || '不连接服务器'}</span><span><Sparkles size={12} />{schedule.model || '使用默认模型'}</span></div>
          <div className="schedule-timing"><span>下次执行 <strong>{schedule.enabled ? dateTime(schedule.next_run_at) : '已暂停'}</strong></span><span>上次执行 <strong>{dateTime(schedule.last_run_at)}</strong></span></div>
        </div>
        <div className="schedule-card-actions">
          <AsyncButton variant="secondary" className="button-small" disabled={Boolean(reason)} title={reason || undefined} action={() => launch(schedule)}><Play size={14} />立即运行</AsyncButton>
          {schedule.last_run_id && <Link to={`/chat?run=${schedule.last_run_id}`} onClick={event => { event.preventDefault(); void api.get<{ run: { conversation_id: string } }>(`/runs/${schedule.last_run_id}`).then(detail => navigate(`/chat/${detail.run.conversation_id}?run=${schedule.last_run_id}`)).catch(err => notify(errorMessage(err), 'error')); }} className="text-link small"><History size={13} />上次记录</Link>}
          {schedule.read_only ? <Button variant="ghost" className="button-small" onClick={() => setView(schedule)}><Eye size={15} />查看配置</Button> : <div><button className="icon-button" aria-label="编辑定时任务" onClick={() => setEdit(schedule)}><Pencil size={15} /></button><button className="icon-button danger-text" aria-label="删除定时任务" onClick={() => confirm('删除定时任务？', `“${schedule.name}”将不再自动调度。已提交的运行不会因此停止。`, async () => { if (schedule.read_only) return; await api.delete(`/schedules/${schedule.id}`); dataChanged(); notify('定时任务已删除'); })}><Trash2 size={15} /></button></div>}
        </div>
      </article>;
    })}</div>}
    {edit && (edit === 'new' || !edit.read_only) && <ScheduleForm value={edit} onClose={() => setEdit(null)} />}
    {view && <ScheduleDetails schedule={view} onClose={() => setView(null)} />}{dialog}
    <Banner>定时任务会按选择的控制模式执行。审批模式下，高风险步骤可能等待你确认；请为无人值守任务设置合适的安全边界。</Banner>
  </div>;
}
function ScheduleDetails({ schedule, onClose }: { schedule: Schedule; onClose: () => void }) {
  const catalog = useCatalog();
  return <Modal title={`查看配置 · ${schedule.name}`} description="系统默认调度配置由管理员维护；获执行授权后可立即运行，历史记录始终可查看。" onClose={onClose} wide>
    <div className="ea-resource-details">
      <span className="ea-resource-read-only">系统默认 · 只读</span>
      <dl>
        <div><dt>任务名称</dt><dd>{schedule.name}</dd></div>
        <div><dt>任务目标</dt><dd>{schedule.prompt}</dd></div>
        <div><dt>Cron 表达式</dt><dd><code>{schedule.cron}</code></dd></div>
        <div><dt>时区</dt><dd>{schedule.timezone}</dd></div>
        <div><dt>自动调度</dt><dd>{schedule.enabled ? '已启用' : '已暂停'}</dd></div>
        <div><dt>目标服务器</dt><dd>{schedule.server_id ? catalog.servers.find(server => server.id === schedule.server_id)?.name || '已移除资源' : '不连接服务器'}</dd></div>
        <div><dt>执行智能体</dt><dd>{schedule.agent_id ? catalog.agents.find(agent => agent.id === schedule.agent_id)?.name || '已移除资源' : '通用运维助手'}</dd></div>
        <div><dt>模型供应商</dt><dd>{schedule.provider_id ? catalog.providers.find(provider => provider.id === schedule.provider_id)?.name || '已移除资源' : '使用默认供应商'}</dd></div>
        <div><dt>模型</dt><dd>{schedule.model || '使用默认模型'}</dd></div>
        <div><dt>控制等级</dt><dd><ControlBadge level={schedule.control_level} /></dd></div>
        <div><dt>下次执行</dt><dd>{schedule.enabled ? dateTime(schedule.next_run_at) : '已暂停'}</dd></div>
        <div><dt>上次执行</dt><dd>{dateTime(schedule.last_run_at)}</dd></div>
      </dl>
    </div>
    <div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭</Button></div>
  </Modal>;
}
function ScheduleForm({ value, onClose }: { value: Schedule | 'new'; onClose: () => void }) {
  const item = value === 'new' ? null : value; const catalog = useCatalog(); const { user } = useAuth(); const notify = useToast(); const [cron, setCron] = useState(item?.cron || '0 9 * * *'); const [providerId, setProviderId] = useState(item?.provider_id || ''); const provider = catalog.providers.find(provider => provider.id === providerId);
  const [level, setLevel] = useState<ControlLevel | undefined>(item?.control_level || user?.control_level);
  const safeLevel = fallbackControl(user, level);
  const [agentId, setAgentId] = useState(() => catalog.agents.some(agent => agent.id === item?.agent_id && agent.kind !== 'remote' && canUseControl(user, agent.control_level)) ? item?.agent_id || '' : '');
  const [enabled, setEnabled] = useState(item?.enabled ?? true);
  const reason = catalog.loading ? '正在检查智能体控制等级授权…' : scheduleExecutionReason(user, { control_level: safeLevel || 'observe', agent_id: agentId || null }, catalog.agents);
  useEffect(() => {
    if (!catalog.loading && agentId && !catalog.agents.some(agent => agent.id === agentId && agent.kind !== 'remote' && canUseControl(user, agent.control_level))) setAgentId('');
  }, [user, agentId, catalog.agents, catalog.loading]);
  return <FormDialog title={item ? '编辑定时任务' : '安排一个定时任务'} description="任务由后台智能体引擎执行，不是本机 shell cron。时区固定为 Asia/Shanghai。" onClose={onClose} wide onSubmit={async form => {
    if (item?.read_only) throw new Error('系统默认资源为只读，无法修改。');
    if (cron.trim().split(/\s+/).length !== 5) throw new Error('Cron 表达式需要 5 个字段：分钟 小时 日 月 星期');
    const selectedLevel = formString(form, 'control_level');
    const selectedAgentId = formString(form, 'agent_id') || null;
    if (!canUseControl(user, selectedLevel)) throw new Error('管理员未授权此控制等级，请选择已授权等级后保存。');
    if (selectedAgentId && !catalog.agents.some(agent => agent.id === selectedAgentId && agent.kind !== 'remote' && canUseControl(user, agent.control_level))) throw new Error('关联智能体不可执行，请选择控制等级已获授权的本地智能体。');
    if (form.has('enabled')) {
      const blocked = scheduleExecutionReason(user, { control_level: selectedLevel, agent_id: selectedAgentId }, catalog.agents);
      if (blocked) throw new Error(blocked);
    }
    const payload = { name: formString(form, 'name'), prompt: formString(form, 'prompt'), cron: cron.trim(), timezone: 'Asia/Shanghai', enabled: form.has('enabled'), server_id: formString(form, 'server_id') || null, provider_id: providerId || null, model: formString(form, 'model') || null, agent_id: selectedAgentId, control_level: selectedLevel };
    await (item ? api.patch(`/schedules/${item.id}`, payload) : api.post('/schedules', payload)); dataChanged(); notify('定时任务已保存');
  }}><Field label="任务名称" required><input name="name" required maxLength={120} defaultValue={item?.name} placeholder="例如：每日生产环境健康巡检" /></Field><Field label="任务目标" required hint="明确需要检查的内容、报告要求和禁止的操作。每次触发会创建独立的真实对话与运行。"><textarea name="prompt" required rows={4} defaultValue={item?.prompt} placeholder="每天检查服务负载、内存、磁盘与关键进程，输出风险报告。不要进行任何变更。" /></Field><Field label="Cron 表达式" required hint="顺序：分钟 小时 日 月 星期。例如 0 9 * * * 表示每天北京时间 09:00。"><input className="mono" value={cron} onChange={event => setCron(event.target.value)} required placeholder="0 9 * * *" /></Field><div className="cron-presets">{[{ value: '0 9 * * *', label: '每天 09:00' }, { value: '0 */2 * * *', label: '每两小时' }, { value: '0 9 * * 1-5', label: '工作日 09:00' }, { value: '0 9 * * 1', label: '每周一 09:00' }].map(preset => <button key={preset.value} type="button" className={cron === preset.value ? 'selected' : ''} onClick={() => setCron(preset.value)}>{preset.label}</button>)}</div><div className="form-grid"><Field label="目标服务器"><Select label="目标服务器" name="server_id" defaultValue={item?.server_id || ''} searchable options={[{ value: '', label: '不连接服务器' }, ...catalog.servers.map(server => ({ value: server.id, label: server.name }))]} /></Field><Field label="执行智能体"><Select label="执行智能体" name="agent_id" value={agentId} onChange={next => { if (!next || catalog.agents.some(agent => agent.id === next && agent.kind !== 'remote' && canUseControl(user, agent.control_level))) setAgentId(next); }} searchable options={[{ value: '', label: '通用运维助手' }, ...catalog.agents.filter(agent => agent.kind !== 'remote').map(agent => ({ value: agent.id, label: agent.name, disabled: !canUseControl(user, agent.control_level), description: canUseControl(user, agent.control_level) ? undefined : '管理员未授权此智能体的控制等级' }))]} /></Field></div><div className="form-grid"><Field label="模型供应商"><Select label="模型供应商" value={providerId} onChange={setProviderId} searchable options={[{ value: '', label: '使用默认供应商' }, ...catalog.providers.filter(provider => provider.enabled || provider.id === providerId).map(provider => ({ value: provider.id, label: provider.name }))]} /></Field><Field label="模型"><Select label="模型" name="model" defaultValue={item?.model || ''} searchable allowCustom options={[{ value: '', label: provider?.default_model || '使用默认模型' }, ...(provider?.models || []).map(model => ({ value: model, label: model }))]} /></Field></div><Field label="控制等级"><ControlSelect value={safeLevel} onChange={setLevel} defaultValue={item?.control_level || user?.control_level} /></Field>{item?.agent_id && agentId !== item.agent_id && <Banner>原关联智能体已移除、为远程或控制等级未获授权；当前改用通用运维助手，保存后才会修改任务。</Banner>}<fieldset className={`control-permission-switch${!enabled && reason ? ' control-permission-disabled' : ''}`} disabled={!enabled && Boolean(reason)} title={reason || undefined}><Switch name="enabled" label="保存后启用自动调度" checked={enabled} onChange={next => { if (!next || !reason) setEnabled(next); }} /></fieldset>{reason && <p className="control-permission-note">{reason}</p>}</FormDialog>;
}
export function AlertsPage() {
  const { user } = useAuth();
  const diagnosticReason = user?.role === 'admin' ? '管理员账户不能执行本地任务。' : canUseControl(user, 'observe') ? '' : 'AI 诊断使用观察模式，管理员未授权此控制等级。';
  const resource = useResource<Alert[]>('/alerts', []); const catalog = useCatalog(); const [create, setCreate] = useState(false); const [search, setSearch] = useState(''); const [filter, setFilter] = useState('open'); const [severity, setSeverity] = useState('all'); const notify = useToast(); const { watch } = useExecutions(); const navigate = useNavigate();
  const filtered = resource.data.filter(alert => (filter === 'all' || alert.status === filter) && (severity === 'all' || alert.severity === severity) && `${alert.title} ${alert.description} ${alert.source}`.toLowerCase().includes(search.toLowerCase()));
  const diagnose = async (alert: Alert) => { if (diagnosticReason) throw new Error(diagnosticReason); const result = await api.post<RunLaunch>(`/alerts/${alert.id}/diagnose`); await watch(result.run_id).catch(() => undefined); dataChanged(); navigate(`/chat/${result.conversation_id}?run=${result.run_id}`); };
  return <div className="page"><PageHeader eyebrow="SIGNAL, NOT NOISE" title="重要的问题，不被错过" description="汇总真实告警，借助智能体分析根因，让每个问题都有回应。" action={<><UserResourceImportButton kind="alerts" label="告警" /><NewButton onClick={() => setCreate(true)}>记录告警</NewButton></>} /><div className="alert-metrics">{[{ severity: 'critical', label: '严重告警', color: 'red' }, { severity: 'warning', label: '警告', color: 'amber' }, { severity: 'info', label: '提示', color: 'blue' }].map(item => <button className={`alert-metric ${severity === item.severity ? 'selected' : ''}`} key={item.severity} onClick={() => setSeverity(severity === item.severity ? 'all' : item.severity)}><span className={`metric-icon ${item.color}`}><Bell size={20} /></span><div><strong>{resource.data.filter(alert => alert.severity === item.severity && alert.status === 'open').length}</strong><span>{item.label} · 待处理</span></div><ChevronRight size={17} /></button>)}<div className="alert-resolved"><CheckCircle2 size={23} /><div><strong>{resource.data.filter(alert => alert.status === 'resolved').length}</strong><span>已解决</span></div></div></div><div className="list-toolbar"><div className="segment-control">{[{ value: 'open', label: '待处理' }, { value: 'resolved', label: '已解决' }, { value: 'all', label: '全部记录' }].map(option => <button className={filter === option.value ? 'selected' : ''} onClick={() => setFilter(option.value)} key={option.value}>{option.label}</button>)}</div><SearchInput value={search} onChange={setSearch} placeholder="搜索标题、来源或描述…" /></div>{resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading /> : !filtered.length ? <div className="panel"><EmptyState compact icon={resource.data.length ? CheckCircle2 : Bell} title={resource.data.length ? '当前视图下没有告警' : '保持平静，也保持关注'} description={resource.data.length ? '可以调整状态或严重级别筛选，查看其他告警记录。' : '这里还没有告警记录。你可以手动记录问题，关联服务器后让智能体进一步诊断。'} /></div> : <div className="alert-list">{filtered.map(alert => <article className={`alert-card alert-${alert.severity}`} key={alert.id}><div className="alert-severity-icon">{alert.severity === 'critical' ? <TriangleAlert size={21} /> : <Bell size={21} />}</div><div className="alert-card-main"><div className="alert-title-row"><h3>{alert.title}</h3><span className={`severity-label severity-${alert.severity}`}>{({ critical: '严重', warning: '警告', info: '提示' })[alert.severity]}</span><StatusBadge status={alert.status} /></div><p>{alert.description || '未提供详细描述'}</p><div className="alert-meta"><span>{alert.source || '手动记录'}</span><i>·</i><span>{catalog.servers.find(server => server.id === alert.server_id)?.name || '未关联服务器'}</span><i>·</i><time title={dateTime(alert.created_at)}>{relativeTime(alert.created_at)}</time></div></div><div className="alert-card-actions"><AsyncButton variant="secondary" className="button-small" disabled={Boolean(diagnosticReason)} title={diagnosticReason || undefined} action={() => diagnose(alert)}><Sparkles size={14} />AI 诊断</AsyncButton><AsyncButton variant="ghost" className="button-small" action={async () => { await api.patch(`/alerts/${alert.id}`, { status: alert.status === 'open' ? 'resolved' : 'open' }); dataChanged(); notify(alert.status === 'open' ? '告警已标记解决' : '告警已重新打开'); }}><Check size={14} />{alert.status === 'open' ? '标记解决' : '重新打开'}</AsyncButton></div></article>)}</div>}{create && <FormDialog title="记录一个告警" description="将观察到的问题记下来，关联服务器后可发起真实 AI 诊断。" onClose={() => setCreate(false)} onSubmit={async form => { await api.post('/alerts', { title: formString(form, 'title'), severity: formString(form, 'severity'), description: formString(form, 'description'), source: formString(form, 'source') || '手动记录', server_id: formString(form, 'server_id') || null, status: 'open' }); dataChanged(); notify('告警已记录'); }}><Field label="告警标题" required><input name="title" required maxLength={160} placeholder="简要描述问题" /></Field><div className="form-grid"><Field label="严重级别"><Select label="严重级别" name="severity" defaultValue="warning" options={[{ value: 'critical', label: '严重 · 影响核心业务' }, { value: 'warning', label: '警告 · 需要关注' }, { value: 'info', label: '提示 · 记录信息' }]} /></Field><Field label="来源"><input name="source" defaultValue="手动记录" placeholder="手动记录 / 监控系统" /></Field></div><Field label="关联服务器"><Select label="关联服务器" name="server_id" defaultValue="" searchable options={[{ value: '', label: '不关联服务器' }, ...catalog.servers.map(server => ({ value: server.id, label: server.name }))]} /></Field><Field label="问题描述" hint="建议包含现象、发生时间、影响范围与已采取的措施。"><textarea name="description" rows={5} placeholder="详细描述观察到的异常…" /></Field></FormDialog>}{diagnosticReason && <p className="control-permission-note">{diagnosticReason}</p>}<div className="bottom-note"><ShieldCheck size={15} />诊断会创建独立的真实运维任务。控制等级与安全审批规则同样适用。</div></div>;
}
