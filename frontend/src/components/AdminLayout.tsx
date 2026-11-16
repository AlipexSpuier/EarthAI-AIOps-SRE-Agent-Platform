import { useEffect, useRef, useState } from 'react';
import { Bell, Blocks, BookOpen, Bot, CalendarClock, CircleHelp, FolderKanban, LayoutDashboard, LogOut, Menu, Palette, Server, ShieldCheck, Sparkles, Users, UsersRound, X } from 'lucide-react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useBranding } from '../context/BrandingContext';
import { api } from '../lib/api';
import { Brand } from './Brand';
import { Field, FormDialog, useConfirm } from './ui';
import './TopbarHelp.css';

const items = [
  { to: '/admin/overview', label: '系统概览', icon: LayoutDashboard },
  { to: '/admin/agents', label: '智能体管理', icon: Bot },
  { to: '/admin/users', label: '用户管理', icon: Users },
  { to: '/admin/team-spaces', label: '团队空间管理', icon: UsersRound },
  { to: '/admin/knowledge', label: '知识库管理', icon: BookOpen },
  { to: '/admin/skills', label: '技能库管理', icon: Blocks },
  { to: '/admin/projects', label: '项目管理', icon: FolderKanban },
  { to: '/admin/servers', label: '服务器管理', icon: Server },
  { to: '/admin/providers', label: '模型供应商管理', icon: Sparkles },
  { to: '/admin/schedules', label: '定时任务管理', icon: CalendarClock },
  { to: '/admin/alerts', label: '告警管理', icon: Bell },
  { to: '/admin/branding', label: '界面管理', icon: Palette },
];
export function AdminLayout() {
  const { user, logout, retry } = useAuth(); const brand = useBranding(); const location = useLocation();
  const [mobile, setMobile] = useState(false); const [password, setPassword] = useState(false);
  const content = useRef<HTMLDivElement>(null); const menu = useRef<HTMLButtonElement>(null); const sidebar = useRef<HTMLElement>(null);
  const { confirm, dialog } = useConfirm();
  useEffect(() => { setMobile(false); if (content.current) content.current.scrollTop = 0; }, [location.pathname]);
  useEffect(() => {
    if (!mobile) return;
    sidebar.current?.querySelector<HTMLElement>('a')?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setMobile(false); menu.current?.focus(); }
      if (event.key !== 'Tab') return;
      const controls = [...(sidebar.current?.querySelectorAll<HTMLElement>('a,button') || [])];
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus(); }
    };
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key);
  }, [mobile]);
  const title = location.pathname === '/admin/guides' ? '使用指南管理' : items.find(item => location.pathname === item.to)?.label || '管理员使用指南';
  return <div className="app-shell admin-shell">{mobile && <div className="sidebar-overlay" onClick={() => setMobile(false)} />}<aside className={`sidebar ${mobile ? 'sidebar-open' : ''}`} aria-label="管理后台侧栏" ref={sidebar}><div className="brand"><Brand /></div><div className="sidebar-caption">{brand.tagline}</div><nav aria-label="主导航"><div className="nav-section"><div className="nav-label">系统管理</div>{items.map(item => <NavLink to={item.to} key={item.to} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><item.icon size={18} /><span>{item.label}</span></NavLink>)}</div></nav><div className="sidebar-bottom"><div className="admin-account-actions"><button className="text-button" onClick={() => setPassword(true)}>修改密码</button><button className="text-button" onClick={() => confirm('退出管理员账号？', '仅结束当前登录会话，不会删除默认资源。', logout)}><LogOut size={13} />退出登录</button></div><div className="user-bar"><div className="user-info"><span className="user-avatar">{user?.avatar || 'AD'}</span><span><strong>{user?.name}</strong><small>系统管理员</small></span></div><ShieldCheck size={16} /></div></div></aside><div className="app-main" inert={mobile || undefined}><header className="topbar"><div className="topbar-left"><button ref={menu} className="icon-button mobile-menu" aria-label="展开导航" aria-expanded={mobile} onClick={() => setMobile(true)}>{mobile ? <X size={20} /> : <Menu size={20} />}</button><span className="topbar-workspace">管理后台</span><span className="breadcrumb-separator">/</span><span>{title}</span></div><div className="topbar-right"><span className="topbar-security"><ShieldCheck size={14} />管理员操作全程审计</span><Link to="/help" className="topbar-help-link" title="使用指南" aria-label="使用指南"><CircleHelp size={17} /><span>使用指南</span></Link></div></header><main ref={content} className="route-content"><Outlet /></main></div>{password && <FormDialog title="修改管理员密码" onClose={() => setPassword(false)} onSubmit={async form => { if (form.get('new_password') !== form.get('confirm_password')) throw new Error('两次新密码不一致'); await api.post('/auth/password', { current_password: form.get('current_password'), new_password: form.get('new_password') }); await retry(); }}><Field label="当前密码" required><input name="current_password" type="password" required autoComplete="current-password" /></Field><Field label="新密码" required><input name="new_password" type="password" minLength={8} required autoComplete="new-password" /></Field><Field label="确认新密码" required><input name="confirm_password" type="password" minLength={8} required autoComplete="new-password" /></Field></FormDialog>}{dialog}</div>;
}
