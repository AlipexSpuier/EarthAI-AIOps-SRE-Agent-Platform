import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { Activity, ArrowUpRight, Bell, Blocks, BookOpen, Bot, CalendarClock, ChevronLeft, ChevronRight, FileText, FolderKanban, HardDrive, KeyRound, LifeBuoy, List, MessageSquare, Palette, Search, Server, Settings, ShieldCheck, Sparkles, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Banner, Button, EmptyState, ErrorState, Loading, PageHeader, SearchInput } from '../components/ui';
import { Content } from '../components/Content';
import { useResource } from '../lib/hooks';
import './HelpPage.css';

export type GuideAudience = 'admin' | 'user';
export interface Guide {
  id: string;
  audience: GuideAudience;
  title: string;
  summary: string;
  icon: string;
  sort_order: number;
  content: string;
  created_at: string;
  updated_at: string;
}

export const guideIcons: Record<string, LucideIcon> = {
  Activity, ArrowUpRight, Bell, Blocks, BookOpen, Bot, CalendarClock, FileText, FolderKanban, HardDrive,
  KeyRound, LifeBuoy, MessageSquare, Palette, Server, Settings, ShieldCheck, Sparkles, Users,
};
export function guideIcon(name: string): LucideIcon {
  return Object.hasOwn(guideIcons, name) ? guideIcons[name] : BookOpen;
}
function scrollToTop(id: string) {
  const element = document.getElementById(id);
  if (!element) return;
  element.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  element.focus({ preventScroll: true });
}

export function HelpPage() {
  const { user } = useAuth(); const admin = user?.role === 'admin';
  const { section } = useParams<{ section: string }>();
  const resource = useResource<Guide[]>('/guides', []);
  const [search, setSearch] = useState('');
  const contentRef = useRef<HTMLElement>(null);
  const guides = resource.data;
  const filtered = useMemo(() => {
    const terms = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return guides.filter(guide => {
      const text = `${guide.title} ${guide.summary} ${guide.content}`.toLowerCase();
      return terms.every(term => text.includes(term));
    });
  }, [guides, search]);
  const searching = Boolean(search.trim());
  const prefix = admin ? 'help-admin' : 'help-user';
  const currentIndex = guides.findIndex(guide => guide.id === section);
  const currentGuide = guides[currentIndex];
  const previousGuide = guides[currentIndex - 1];
  const nextGuide = currentIndex >= 0 ? guides[currentIndex + 1] : undefined;
  useEffect(() => {
    if (!section || resource.loading) return;
    const frame = window.requestAnimationFrame(() => {
      contentRef.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
      contentRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [prefix, section, resource.loading, currentGuide?.id]);
  if (!section && !resource.loading && !resource.error && guides.length) return <Navigate to={`/help/${guides[0].id}`} replace />;

  return <div className="page ea-help-page" id="help-top" tabIndex={-1}>
    <PageHeader
      eyebrow={admin ? 'ADMINISTRATOR HANDBOOK' : 'YOUR WORKSPACE HANDBOOK'}
      title={admin ? '管理有据，操作有边界' : '从了解，到放心使用'}
      description={admin ? `管理员使用指南由平台统一维护。当前收录 ${guides.length} 节，每节独立阅读，操作以真实权限与服务端校验为准。` : '从对话、默认资源到个人配置，逐模块掌握真实执行、数据权限与安全边界。指南与当前账户角色自动匹配。'}
      action={admin ? <Link className="button button-secondary" to="/admin/guides"><Settings size={16} />管理使用指南</Link> : undefined}
    />
    <section className="ea-help-hero">
      <div className="ea-help-hero-icon">{admin ? <ShieldCheck size={30} /> : <LifeBuoy size={30} />}</div>
      <div><span>{admin ? '平台管理员专用指南' : '普通用户工作空间指南'}</span><h2>{admin ? '一次配置，影响每一位用户。' : '让真实能力，在清晰边界内工作。'}</h2><p>{admin ? '管理员与普通用户拥有各自的指南目录。请在变更共享配置前核对生效范围，维护指南时同步说明真实能力、操作步骤与安全边界。' : '系统默认资源只读但可正常使用；自己的资源可增删改。运行在后台继续，模型流式返回，权限与真实工具结果始终优先。'}</p></div>
      <span className="ea-help-hero-count"><strong>{resource.loading ? '—' : guides.length}</strong>个章节</span>
    </section>
    {resource.loading ? <Loading text="读取使用指南…" /> : resource.error ? <ErrorState message={resource.error} retry={resource.reload} /> : !guides.length ? <div className="panel ea-help-empty"><EmptyState icon={BookOpen} title="当前角色暂无使用指南" description={admin ? '管理员指南目录目前为空。可通过页头“管理使用指南”新建章节，发布后即可在此阅读。' : '管理员尚未发布普通用户指南，或已移除全部章节。请稍后重试或联系管理员。'} action={<Button variant="secondary" onClick={() => { void resource.reload(); }}>刷新指南</Button>} /></div> : <>
      <div className="ea-help-searchbar"><SearchInput value={search} onChange={setSearch} placeholder="搜索模块、字段、操作或常见失败…" /><span role="status" aria-live="polite">{searching ? `在本角色全部 ${guides.length} 节中找到 ${filtered.length} 节，请点击目录跳转；当前正文保持显示。` : '每节独立一页；搜索只筛选目录，不会替换当前正文。'}</span></div>
      <div className="ea-help-layout">
        <aside className="ea-help-toc">
          <div><List size={17} /><h2>{searching ? '搜索结果' : '使用目录'}</h2><span>{filtered.length} / {guides.length}</span></div>
          <nav aria-label={admin ? '管理员指南目录' : '用户指南目录'}>{filtered.map(guide => {
            const Icon = guideIcon(guide.icon);
            return <Link to={`/help/${guide.id}`} key={guide.id} aria-current={currentGuide?.id === guide.id ? 'page' : undefined}><Icon size={16} /><span>{guide.title}</span><ChevronRight size={13} /></Link>;
          })}</nav>
          {!filtered.length && <EmptyState compact icon={Search} title="没有匹配的指南模块" description="尝试更短的关键词，如“模型”“指纹”或“默认”。当前正文不受搜索影响。" action={<Button variant="secondary" onClick={() => setSearch('')}>清除搜索</Button>} />}
          <div className="ea-help-toc-note"><KeyRound size={16} /><p>{admin ? '账号角色决定平台入口；控制等级决定任务执行边界，两者不能互相替代。' : '默认配置问题联系管理员。不要为修复只读提示而把个人密码或密钥发给他人。'}</p></div>
        </aside>
        <main className="ea-help-content" ref={contentRef} tabIndex={-1} aria-label={currentGuide ? `${currentGuide.title}，第 ${currentIndex + 1} / ${guides.length} 节` : '帮助章节选择'}>
          {currentGuide ? <>
            <div className="ea-help-current" aria-live="polite"><div><span>当前章节</span><strong>{currentGuide.title}</strong></div><span>{currentIndex + 1} / {guides.length}</span></div>
            <GuideSection key={`${prefix}-${currentGuide.id}`} guide={currentGuide} id={`${prefix}-${currentGuide.id}`} onTop={() => scrollToTop('help-top')} />
            <nav className="ea-help-pagination" aria-label="帮助章节翻页">
              {previousGuide ? <Link to={`/help/${previousGuide.id}`} rel="prev"><ChevronLeft size={18} /><span><small>上一节</small><strong>{previousGuide.title}</strong></span></Link> : <span className="ea-help-pagination-edge">已是第一节</span>}
              {nextGuide ? <Link to={`/help/${nextGuide.id}`} rel="next"><span><small>下一节</small><strong>{nextGuide.title}</strong></span><ChevronRight size={18} /></Link> : <span className="ea-help-pagination-edge">已是最后一节</span>}
            </nav>
          </> : <div className="panel"><EmptyState icon={BookOpen} title="该章节不存在或已被移除" description="当前地址不在本角色的指南目录中。请选择仍可用的章节，或返回第一节；管理员与普通用户的目录分别维护。" action={<Link className="button button-secondary" to={`/help/${guides[0].id}`} replace>返回第一节：{guides[0].title}</Link>} /></div>}
          <section className="ea-help-network"><span><Server size={23} /></span><div><h2>局域网静态资源与真实服务依赖</h2><p>字体、脚本和图标从平台本机提供，界面正常使用无需外部字体或图标 CDN。但模型接口、SSH 服务器和 Kubernetes API 仍需从 EarthAI 后端实际可达；本地静态资源不等于内置离线大模型。浏览器能打开页面与服务端能访问目标，是两条不同的网络路径。</p></div></section>
          <Banner tone="warning">{admin ? '发布任何默认修改前，请检查共享凭据授权、依赖运行与全员成本。删除需要二次确认；审计只记录真实操作，不替代备份。' : '不要把模型回复当成已经执行的证据。请查看真实工具结果、运行状态与审批；页面切换或关闭不会自动取消已提交的后台任务。'}</Banner>
        </main>
      </div>
    </>}
  </div>;
}
function GuideSection({ guide, id, onTop }: { guide: Guide; id: string; onTop: () => void }) {
  const Icon = guideIcon(guide.icon);
  return <article className="ea-help-module" id={id} tabIndex={-1} aria-label={guide.title} title={guide.title}>
    <header className="ea-help-module-heading"><span className="ea-help-module-icon"><Icon size={25} /></span><div><h2>{guide.title}</h2>{guide.summary && <p>{guide.summary}</p>}</div><Link to={`/help/${guide.id}`} className="ea-help-anchor" aria-label={`链接到${guide.title}`} onClick={() => scrollToTop(id)}>#</Link></header>
    <div className="ea-help-markdown">{guide.content.trim() ? <Content text={guide.content} /> : <Banner>本章节尚未填写正文。请稍后查看，或联系管理员完善内容。</Banner>}</div>
    <footer><span>操作以实际权限、服务端校验及真实运行记录为准</span><button type="button" onClick={onTop}>返回顶部 ↑</button></footer>
  </article>;
}
