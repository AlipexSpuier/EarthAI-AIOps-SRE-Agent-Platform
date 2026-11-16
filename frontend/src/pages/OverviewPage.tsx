import { useId, useState } from 'react';
import type { FormEvent } from 'react';
import { Activity, Bell, BookOpen, CheckCircle2, Database, RefreshCw, Server, ShieldCheck, Terminal } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useResource } from '../lib/hooks';
import type { Audit, Overview } from '../types';
import { pretty, relativeTime } from '../lib/format';
import { Button, EmptyState, ErrorState, Loading, PageHeader, SectionTitle } from '../components/ui';
import { RunLink } from '../components/RunCard';
import { Select } from '../components/Select';
import './OverviewAudit.css';

type AuditRange = '24h' | '7d' | '30d' | 'all' | 'custom';
type AuditFilter = { range: AuditRange; start?: string; end?: string };
const auditRanges: { value: AuditRange; label: string }[] = [
  { value: '24h', label: '最近24小时' },
  { value: '7d', label: '最近7天' },
  { value: '30d', label: '最近30天' },
  { value: 'all', label: '全部时间' },
  { value: 'custom', label: '自定义' },
];

function presetAuditFilter(range: Exclude<AuditRange, 'custom'>): AuditFilter {
  if (range === 'all') return { range };
  const days = { '24h': 1, '7d': 7, '30d': 30 }[range];
  const end = new Date();
  return { range, start: new Date(end.getTime() - days * 86400000).toISOString(), end: end.toISOString() };
}

export function OverviewPage() {
  const { user } = useAuth();
  const resource = useResource<Overview | null>('/overview', null);
  const auditId = useId();
  const [auditRange, setAuditRange] = useState<AuditRange>('24h');
  const [auditFilter, setAuditFilter] = useState<AuditFilter>(() => presetAuditFilter('24h'));
  const [auditStart, setAuditStart] = useState('');
  const [auditEnd, setAuditEnd] = useState('');
  const [auditValidation, setAuditValidation] = useState('');
  const auditParams = new URLSearchParams({ limit: '100' });
  if (auditFilter.start) auditParams.set('start', auditFilter.start);
  if (auditFilter.end) auditParams.set('end', auditFilter.end);
  const auditResource = useResource<Audit[]>(`/audit?${auditParams.toString()}`, []);
  const auditTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const auditTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
  const auditRangeDescription = auditFilter.range === 'all' ? '全部时间' : `${auditFilter.start ? auditTimeFormat.format(new Date(auditFilter.start)) : '不限开始时间'} — ${auditFilter.end ? auditTimeFormat.format(new Date(auditFilter.end)) : '不限结束时间'}`;
  const applyAuditFilter = (next: AuditFilter) => {
    setAuditFilter(next);
    if (next.start === auditFilter.start && next.end === auditFilter.end) void auditResource.reload();
  };
  const queryCustomAudit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const start = auditStart ? new Date(auditStart) : undefined;
    const end = auditEnd ? new Date(auditEnd) : undefined;
    if (!event.currentTarget.checkValidity() || (start && Number.isNaN(start.getTime())) || (end && Number.isNaN(end.getTime()))) {
      setAuditValidation('请输入有效的本地日期和时间。');
      return;
    }
    if (!start && !end) {
      setAuditValidation('请至少填写开始或结束时间；不限制时间请选择「全部时间」。');
      return;
    }
    if (start && end && end.getTime() < start.getTime()) {
      setAuditValidation('结束时间不能早于开始时间。');
      return;
    }
    setAuditValidation('');
    applyAuditFilter({ range: 'custom', start: start?.toISOString(), end: end?.toISOString() });
  };
  const refreshOverview = () => {
    void resource.reload();
    if (auditFilter.range === 'custom') void auditResource.reload();
    else applyAuditFilter(presetAuditFilter(auditFilter.range));
  };
  const data = resource.data;
  if (resource.loading && !data) return <Loading />;
  return <div className="page overview-page">
    <PageHeader eyebrow="系统概览" title="让一切，尽在掌握" description={`${user?.name || '运维伙伴'}，这里是你的基础设施与任务执行概况。`} action={<Button variant="secondary" busy={resource.loading || auditResource.loading} onClick={refreshOverview}><RefreshCw size={15} />刷新</Button>} />
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}
    {data && <>
      <div className="metric-grid">{[
        { key: 'servers' as const, label: '服务器', icon: Server, note: '已配置基础设施', className: 'teal' },
        { key: 'runs' as const, label: '累计执行', icon: Activity, note: `${data.active_runs.length} 个任务运行中`, className: 'blue' },
        { key: 'knowledge' as const, label: '知识库', icon: BookOpen, note: `${data.counts.files} 份个人文件`, className: 'purple' },
        { key: 'alerts' as const, label: '告警记录', icon: Bell, note: `${data.alerts.length} 条近期待处理`, className: 'amber' },
      ].map(metric => <div key={metric.key} className="metric-card"><div className="metric-card-top"><span>{metric.label}</span><span className={`metric-icon ${metric.className}`}><metric.icon size={19} /></span></div><strong>{data.counts[metric.key] ?? 0}<span>{metric.key === 'runs' ? '次' : '个'}</span></strong><div className="metric-card-bottom"><span>{metric.note}</span></div></div>)}</div>
      <div className="overview-columns">
        <div className="overview-main-column">
          <section className="panel"><SectionTitle title="执行动态" subtitle="查看具体任务的结果、步骤与审批记录" />
            {data.active_runs.length > 0 && <div className="active-run-strip"><span className="live-dot" />{data.active_runs.length} 个任务正在后台运行，切换页面不会中断</div>}
            {data.recent_runs.length ? <div className="run-list">{[...new Map([...data.active_runs, ...data.recent_runs].map(run => [run.id, run])).values()].slice(0, 5).map(run => <RunLink key={run.id} run={run} />)}</div> : <EmptyState compact icon={Terminal} title="还没有执行记录" description="在左侧「AI 对话」描述目标，完成后可在这里查看结果。" />}
          </section>
          <section className="panel activity-panel"><SectionTitle title="运行趋势" subtitle="近七天真实执行次数" /><div className="activity-chart">{data.daily_runs.length ? <><div className="chart-bars">{data.daily_runs.map(day => {
            const max = Math.max(...data.daily_runs.map(item => item.count), 1);
            return <div className="chart-bar-group" key={day.date}><span className="chart-value">{day.count}</span><div className="chart-bar-track"><div className="chart-bar" style={{ height: `${day.count / max * 100}%` }} title={`${day.date}：${day.count} 次`} /></div><span className="chart-label">{day.date.slice(5)}</span></div>;
          })}</div><div className="chart-legend"><span />服务端按 UTC 日期统计</div></> : <div className="chart-empty"><Activity size={24} /><span>还没有任务数据</span></div>}</div></section>
          <section className="panel overview-audit" aria-label="审计日志">
            <SectionTitle title="审计日志" subtitle="按时间范围查询真实关键操作，最多显示最近100条" />
            <form className="overview-audit-filters" noValidate onSubmit={queryCustomAudit}>
              <div className="overview-audit-toolbar">
                <div className="field overview-audit-range"><span className="field-label">时间范围</span><Select label="审计日志时间范围" value={auditRange} onChange={value => {
                  const range = value as AuditRange;
                  setAuditRange(range);
                  setAuditValidation('');
                  if (range !== 'custom') applyAuditFilter(presetAuditFilter(range));
                }} options={auditRanges} /></div>
                {auditRange === 'custom' && <>
                  <label className="field overview-audit-date" htmlFor={`${auditId}-start`}><span className="field-label">开始时间（本地）</span><input id={`${auditId}-start`} name="start" type="datetime-local" value={auditStart} aria-describedby={`${auditId}-hint${auditValidation ? ` ${auditId}-validation` : ''}`} aria-invalid={auditValidation ? true : undefined} onChange={event => { setAuditStart(event.target.value); setAuditValidation(''); }} /></label>
                  <label className="field overview-audit-date" htmlFor={`${auditId}-end`}><span className="field-label">结束时间（本地）</span><input id={`${auditId}-end`} name="end" type="datetime-local" value={auditEnd} aria-describedby={`${auditId}-hint${auditValidation ? ` ${auditId}-validation` : ''}`} aria-invalid={auditValidation ? true : undefined} onChange={event => { setAuditEnd(event.target.value); setAuditValidation(''); }} /></label>
                  <Button type="submit" variant="secondary" busy={auditResource.loading}>查询</Button>
                </>}
              </div>
              <p className="overview-audit-hint" id={`${auditId}-hint`}>输入与记录均为浏览器本地时间（{auditTimeZone}），查询时自动转换为 UTC。{auditRange === 'custom' && '可只填开始或结束时间，点击查询后生效。'}</p>
              {auditValidation && <div className="inline-error" id={`${auditId}-validation`} role="alert">{auditValidation}</div>}
            </form>
            <p className="overview-audit-summary">{auditFilter.range === 'custom' ? '自定义' : auditRanges.find(range => range.value === auditFilter.range)?.label} · 当前查询：{auditRangeDescription}{!auditResource.loading && !auditResource.error && ` · 显示 ${auditResource.data.length} 条（每次最多100条）`}</p>
            <div className="overview-audit-results" aria-busy={auditResource.loading}>
              {auditResource.loading ? <Loading text="正在查询审计日志…" /> : auditResource.error ? <ErrorState message={auditResource.error} retry={auditResource.reload} /> : auditResource.data.length ? <div className="audit-list">{auditResource.data.map(audit => <div className="audit-item" key={audit.id}>
                <span className="audit-timeline-dot" />
                <div><strong>{audit.action}</strong><p className="overview-audit-resource">资源：{audit.resource || '—'}</p><p className="overview-audit-detail">{pretty(audit.detail) || '无补充详情'}</p></div>
                <time dateTime={audit.created_at} title={audit.created_at}>{auditTimeFormat.format(new Date(audit.created_at))}</time>
              </div>)}</div> : <p className="panel-empty-note" role="status">所选时间范围内没有审计日志。</p>}
            </div>
          </section>
        </div>
        <div className="overview-side-column">
          <section className="panel health-panel"><SectionTitle title="服务状态" action={<span className="pill emerald">实时状态</span>} /><div className="health-main"><span className="health-ring"><Database size={24} /></span><div><strong>{data.health.status === 'ok' ? '运行正常' : data.health.status}</strong><p>应用服务与数据持久化</p></div></div><div className="health-row"><span>数据库</span><b>{data.health.database}</b></div><div className="health-row"><span>版本</span><b>{data.health.version}</b></div><div className="health-row"><span>模型供应商</span><b>{data.counts.providers} 个</b></div></section>
          <section className="panel"><SectionTitle title="待关注" subtitle="请在左侧告警中心统一处理" />{data.alerts.length ? <div className="overview-alerts">{data.alerts.slice(0, 4).map(alert => <div className="overview-alert" key={alert.id}><span className={`severity-indicator severity-${alert.severity}`} /><div><strong>{alert.title}</strong><span>{relativeTime(alert.created_at)}</span></div></div>)}</div> : <div className="quiet-state"><CheckCircle2 size={27} /><strong>没有待处理告警</strong><p>异常信号会在这里汇总。</p></div>}</section>
          <div className="overview-security-note"><ShieldCheck size={17} /><p>数据来自真实任务记录。新增资源与工作流，请使用左侧对应模块。</p></div>
        </div>
      </div>
    </>}
  </div>;
}
