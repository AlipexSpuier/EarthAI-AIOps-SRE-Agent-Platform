import { useEffect, useRef, useState } from 'react';
import { Activity, ArrowDownLeft, ArrowUpRight, Bell, Blocks, BookOpen, Bot, CircleHelp, FileBox, FolderKanban, LayoutDashboard, Menu, MessageSquare, Server, Settings2, ShieldCheck, Sparkles, CalendarClock, UsersRound } from 'lucide-react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useExecutions } from '../context/ExecutionContext';
import { controlLabels, initials, isActive } from '../lib/format';
import { Brand } from './Brand';
import { useBranding } from '../context/BrandingContext';
import { Link } from 'react-router-dom';
import { canUseSpace } from '../lib/spaceAccess';
import './TopbarHelp.css';

const navSections = [
  { label: '工作空间', items: [{ to: '/chat', label: 'AI 对话', icon: MessageSquare }, { to: '/overview', label: '系统概览', icon: LayoutDashboard }, { to: '/agents', label: '智能体', icon: Bot }] },
  { label: '知识与协作', items: [{ to: '/space', label: '个人空间', icon: FileBox }, { to: '/team-spaces', label: '团队空间', icon: UsersRound }, { to: '/knowledge', label: '知识库', icon: BookOpen }, { to: '/skills', label: '技能库', icon: Blocks }, { to: '/projects', label: '项目', icon: FolderKanban }] },
  { label: '基础设施', items: [{ to: '/servers', label: '服务器', icon: Server }, { to: '/providers', label: '模型供应商', icon: Sparkles }, { to: '/schedules', label: '定时任务', icon: CalendarClock }, { to: '/alerts', label: '告警中心', icon: Bell }] },
];

export function Layout() {
  const { user } = useAuth();
  const { runs, loading: syncing, error: runError, refresh } = useExecutions();
  const location = useLocation();
  const [mobile, setMobile] = useState(false);
  const brand = useBranding();
  const content = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const activeRuns = Object.values(runs).filter(item => isActive(item.run.status));
  const approvals = activeRuns.reduce((sum, item) => sum + item.approvals.filter(approval => approval.status === 'pending').length, 0);
  const routeTitle = location.pathname.startsWith('/help') ? '使用指南' : navSections.flatMap(section => section.items).find(item => location.pathname.startsWith(item.to))?.label || '偏好设置';

  useEffect(() => {
    setMobile(false);
    if (content.current) content.current.scrollTop = 0;
  }, [location.pathname]);

  useEffect(() => {
    if (!mobile) return;
    const first = sidebar.current?.querySelector<HTMLElement>('a');
    first?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setMobile(false); menu.current?.focus(); }
      if (event.key !== 'Tab' || !sidebar.current) return;
      const items = [...sidebar.current.querySelectorAll<HTMLElement>('a, button:not(:disabled)')];
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mobile]);

  return <div className="app-shell">
    {mobile && <div className="sidebar-overlay" onClick={() => { setMobile(false); menu.current?.focus(); }} />}
    <aside ref={sidebar} className={`sidebar ${mobile ? 'sidebar-open' : ''}`} aria-label="工作空间侧栏">
      <div className="brand"><Brand /></div>
      <div className="sidebar-caption">{brand.tagline}</div>
      <nav aria-label="主导航">{navSections.map(section => <div className="nav-section" key={section.label}>
        <div className="nav-label">{section.label}</div>
        {section.items.filter(item => item.to !== '/space' && item.to !== '/team-spaces' || canUseSpace(user, item.to === '/space' ? 'personal' : 'team')).map(item => <NavLink key={item.to} to={item.to} onClick={() => setMobile(false)} className={({ isActive: active }) => `nav-item ${active ? 'active' : ''}`}>
          <item.icon size={18} strokeWidth={1.7} /><span>{item.label}</span>
          {item.to === '/chat' && activeRuns.length > 0 && <span className="nav-count">{activeRuns.length}</span>}
        </NavLink>)}
      </div>)}</nav>
      <div className={`execution-dock ${activeRuns.length ? 'has-active-runs' : ''}`}>
        <div className="dock-heading"><span><Activity size={14} />执行中心</span><button className="icon-button" onClick={() => { void refresh(); }} title="同步执行状态" aria-label="同步执行状态"><ArrowDownLeft size={14} /></button></div>
        {activeRuns.length ? <>
          <div className="dock-live"><span className="live-dot" />{activeRuns.length} 个任务正在运行{approvals > 0 && <span className="dock-approvals">{approvals} 待审批</span>}</div>
          {activeRuns.slice(0, 2).map(item => <Link key={item.run.id} className="dock-run" to={`/chat/${item.run.conversation_id}?run=${item.run.id}`}><span className={`dock-run-dot ${item.run.status === 'waiting_approval' ? 'amber-dot' : ''}`} /><span>{item.run.goal || '后台运维任务'}</span><ArrowUpRight size={13} /></Link>)}
        </> : <div className="dock-empty"><span className="dock-idle-dot" />{syncing ? '同步运行状态中…' : runError ? '同步失败，请点击右上方重试' : '当前没有运行中的任务'}</div>}
      </div>
      <div className="sidebar-bottom">
        <NavLink to="/settings" onClick={() => setMobile(false)} className={({ isActive: active }) => `nav-item ${active ? 'active' : ''}`}><Settings2 size={18} /><span>偏好设置</span></NavLink>
        <div className="user-bar"><div className="user-info"><span className="user-avatar">{user?.avatar || initials(user?.name || '')}</span><span><strong>{user?.name}</strong><small>{controlLabels[user?.control_level || 'approve']}</small></span></div><ShieldCheck size={16} className="user-security-mark" /></div>
      </div>
    </aside>
    <div className="app-main" inert={mobile || undefined}>
      <header className="topbar">
        <div className="topbar-left"><button ref={menu} className="icon-button mobile-menu" aria-label="展开导航" aria-expanded={mobile} onClick={() => setMobile(true)}><Menu size={21} /></button><span className="topbar-workspace">工作空间</span><span className="breadcrumb-separator">/</span><span>{routeTitle}</span></div>
        <div className="topbar-right"><span className="topbar-security"><ShieldCheck size={14} />操作可控 · 全程留痕</span><Link className="topbar-help-link" title="使用指南" aria-label="使用指南" to="/help"><CircleHelp size={17} /><span>使用指南</span></Link></div>
      </header>
      <main ref={content} className={`route-content ${location.pathname.startsWith('/chat') ? 'chat-route-content' : ''}`}><Outlet /></main>
    </div>
  </div>;
}
