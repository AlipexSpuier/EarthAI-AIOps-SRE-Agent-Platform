import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Activity, RefreshCw } from 'lucide-react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { CatalogProvider } from './context/CatalogContext';
import { ExecutionProvider } from './context/ExecutionContext';
import { ToastProvider } from './context/ToastContext';
import { Layout } from './components/Layout';
import { AuthPage } from './pages/AuthPage';
import { ChatPage } from './pages/ChatPage';
import { OverviewPage } from './pages/OverviewPage';
import { ServersPage, ProvidersPage } from './pages/InfrastructurePages';
import { AgentsPage, ProjectsPage, SkillsPage } from './pages/WorkspacePages';
import { KnowledgePage, SpacePage } from './pages/KnowledgePages';
import { AlertsPage, SchedulesPage } from './pages/AutomationPages';
import { SettingsPage } from './pages/SettingsPage';
import { Button } from './components/ui';
import { BrandingProvider } from './context/BrandingContext';
import { Brand } from './components/Brand';
import { AdminLayout } from './components/AdminLayout';
import { AdminAlertsPage, AdminOverviewPage, AdminResourcePage, AdminUsersPage, BrandingPage } from './pages/AdminPages';
import { HelpPage } from './pages/HelpPage';
import { AdminGuidesPage } from './pages/AdminGuidesPage';
import { TeamSpacesPage, AdminTeamSpacesPage } from './pages/TeamSpacesPage';
import { canUseSpace } from './lib/spaceAccess';
import type { SpaceModule } from './types';
import { PasswordChangePage } from './pages/PasswordChangePage';

function SpaceRoute({ module, children }: { module: SpaceModule; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!canUseSpace(user, module)) return <div className="page"><div className="panel"><h1>{module === 'personal' ? '个人空间暂未开启' : '团队空间暂未开启'}</h1><p className="muted">请联系管理员开启此模块。关闭入口不会删除原文件、团队或成员关系；重新开启后仍可按权限访问。</p></div></div>;
  return children;
}

function AppRoutes() {
  const { user, loading } = useAuth();
  if (loading) return <div className="boot-screen"><Brand /><p>正在准备你的工作空间</p><span className="boot-progress" /></div>;
  if (!user) return <AuthPage />;
  if (user.must_change_password) return <PasswordChangePage />;
  if (user.role === 'admin') return <Routes><Route element={<AdminLayout />}><Route path="admin/overview" element={<AdminOverviewPage />} /><Route path="admin/team-spaces" element={<AdminTeamSpacesPage />} /><Route path="admin/users" element={<AdminUsersPage />} /><Route path="admin/alerts" element={<AdminAlertsPage />} /><Route path="admin/branding" element={<BrandingPage />} /><Route path="admin/guides" element={<AdminGuidesPage />} />{['agents', 'knowledge', 'skills', 'projects', 'servers', 'providers', 'schedules'].map(kind => <Route key={kind} path={`admin/${kind}`} element={<AdminResourcePage key={kind} kind={kind} />} />)}<Route path="help" element={<HelpPage />} /><Route path="help/:section" element={<HelpPage />} /><Route path="*" element={<Navigate to="/admin/overview" replace />} /></Route></Routes>;
  return <CatalogProvider><ExecutionProvider><Routes><Route element={<Layout />}><Route index element={<Navigate to="/chat" replace />} /><Route path="chat" element={<ChatPage />} /><Route path="chat/:id" element={<ChatPage />} /><Route path="overview" element={<OverviewPage />} /><Route path="servers" element={<ServersPage />} /><Route path="providers" element={<ProvidersPage />} /><Route path="agents" element={<AgentsPage />} /><Route path="space" element={<SpaceRoute module="personal"><SpacePage /></SpaceRoute>} /><Route path="team-spaces" element={<SpaceRoute module="team"><TeamSpacesPage /></SpaceRoute>} /><Route path="knowledge" element={<KnowledgePage />} /><Route path="skills" element={<SkillsPage />} /><Route path="projects" element={<ProjectsPage />} /><Route path="schedules" element={<SchedulesPage />} /><Route path="alerts" element={<AlertsPage />} /><Route path="settings" element={<SettingsPage />} /><Route path="help" element={<HelpPage />} /><Route path="help/:section" element={<HelpPage />} /><Route path="*" element={<Navigate to="/chat" replace />} /></Route></Routes></ExecutionProvider></CatalogProvider>;
}
export default function App() { return <BrowserRouter><ToastProvider><BrandingProvider><AuthProvider><AppRoutes /></AuthProvider></BrandingProvider></ToastProvider></BrowserRouter>; }
export function FatalError({ reset }: { reset: () => void }) { return <div className="boot-screen"><Activity size={32} /><h1>页面暂时遇到问题</h1><p>已提交的后台任务不受影响。重新加载以恢复执行记录。</p><Button onClick={reset}><RefreshCw size={16} />重新加载页面</Button></div>; }
