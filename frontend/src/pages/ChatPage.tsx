import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Bot, FileSearch, FolderKanban, Globe2, History, Lightbulb, MessageSquare, Network, Pencil, Server, ShieldCheck, Sparkles, Terminal, Trash2, WandSparkles, X } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useBranding } from '../context/BrandingContext';
import { useCatalog } from '../context/CatalogContext';
import { useExecutions } from '../context/ExecutionContext';
import { useToast } from '../context/ToastContext';
import { api, errorMessage } from '../lib/api';
import { controlDescriptions, controlLabels, dateTime, initials, isActive, relativeTime } from '../lib/format';
import { dataChanged, useResource } from '../lib/hooks';
import { canUseControl, fallbackControl } from '../lib/controlAccess';
import type { ChatPreferences, Conversation, ConversationDetail, ControlLevel, Run } from '../types';
import { Button, EmptyState, ErrorState, Field, FormDialog, Loading, Modal, SearchInput, useConfirm } from '../components/ui';
import { Select } from '../components/Select';
import { Content } from '../components/Content';
import { RunCard } from '../components/RunCard';

const prompts = [
  { icon: Terminal, title: '基础设施体检', description: '检查负载、磁盘与关键服务', prompt: '请对所选服务器做一次只读健康检查，检查系统负载、磁盘、内存与关键服务，汇总风险和建议。不要执行变更操作。' },
  { icon: FileSearch, title: '排查服务异常', description: '从故障现象逐步定位根因', prompt: '我需要排查一个服务异常。请先询问我故障现象、影响范围和发生时间，再制定只读排查计划。' },
  { icon: Network, title: '分析集群状态', description: '发现异常工作负载与事件', prompt: '请检查所选 Kubernetes 集群的节点、工作负载与事件，列出异常状态和建议。保持只读，不做修改。' },
  { icon: Lightbulb, title: '查阅运维知识', description: '用已有经验制定行动计划', prompt: '请先检索已关联的知识库，结合我的运维目标给出分步计划。在执行前说明风险与需要确认的事项。' },
];

export function ChatPage() {
  const { id } = useParams();
  const [query] = useSearchParams();
  const navigate = useNavigate();
  const { user, loadChatPreferences, saveChatPreferences } = useAuth();
  const brand = useBranding();
  const catalog = useCatalog();
  const { runs: snapshots, register, watch } = useExecutions();
  const notify = useToast();
  const detail = useResource<ConversationDetail | null>(id ? `/conversations/${id}` : null, null);
  const history = useResource<Conversation[]>('/conversations', []);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [rename, setRename] = useState<Conversation | null>(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const [settings, setSettings] = useState<ChatPreferences>({ server_id: null, provider_id: null, model: '', agent_id: null, project_id: null, control_level: fallbackControl(user, user?.control_level) || 'observe' });
  const selection = useRef(settings);
  const [preferences, setPreferences] = useState<ChatPreferences | null>(null);
  const [preferencesLoading, setPreferencesLoading] = useState(true);
  const [preferencesKey, setPreferencesKey] = useState('');
  const [configurationReady, setConfigurationReady] = useState(false);
  const serverId = settings.server_id || '';
  const providerId = settings.provider_id || '';
  const model = settings.model;
  const agentId = settings.agent_id || '';
  const projectId = settings.project_id || '';
  const control = settings.control_level;
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const initialized = useRef<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const timeline = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const { confirm, dialog } = useConfirm();
  const currentDetail = detail.data?.conversation.id === id ? detail.data : null;
  const selectedProvider = catalog.providers.find(provider => provider.id === providerId);
  const selectedAgent = catalog.agents.find(agent => agent.id === agentId);
  const controlAllowed = canUseControl(user, control);
  const agentAllowed = !agentId || Boolean(selectedAgent && selectedAgent.kind !== 'remote' && canUseControl(user, selectedAgent.control_level));
  const executionBlocked = user?.role === 'admin' ? '管理员账户不能执行本地任务。' : !controlAllowed ? '管理员未授权当前控制等级，暂时无法发送任务。' : !agentAllowed ? '所选智能体已移除、改为远程或其控制等级管理员未授权，请重新选择。' : '';
  const conversationRuns = [...new Map([...(currentDetail?.runs || []), ...Object.values(snapshots).map(item => item.run).filter(run => run.conversation_id === id)].map(run => [run.id, run])).values()];
  const activeRun = conversationRuns.find(run => isActive(snapshots[run.id]?.run.status || run.status));
  const navigationKey = `${user?.id || ''}:${id || 'new'}:${query.get('agent') ?? '<absent>'}:${query.get('project') ?? '<absent>'}:${query.get('server') ?? '<absent>'}`;
  const modelOptions = selectedProvider ? [...new Set([...selectedProvider.models, selectedProvider.default_model, model].filter(Boolean))].map(name => ({
    value: name, label: name, description: name === selectedProvider.default_model ? '默认模型' : undefined, icon: <Sparkles size={15} />,
  })) : [];

  const applySettings = useCallback((values: ChatPreferences) => { selection.current = values; setSettings(values); }, []);

  useEffect(() => {
    initialized.current = null; setConfigurationReady(false); setInput(''); setSendError(''); setAwayFromBottom(false); stickToBottom.current = true;
  }, [navigationKey]);

  useEffect(() => {
    let cancelled = false;
    setPreferencesLoading(true); setPreferences(null);
    void loadChatPreferences().then(values => { if (!cancelled) setPreferences(values); }).catch(err => {
      if (!cancelled) notify(`新会话配置加载失败：${errorMessage(err)}。当前使用临时配置，未覆盖已保存设置。`, 'error');
    }).finally(() => { if (!cancelled) { setPreferencesLoading(false); setPreferencesKey(navigationKey); } });
    return () => { cancelled = true; };
  }, [navigationKey, loadChatPreferences, notify]);

  useEffect(() => {
    if (initialized.current === navigationKey) return;
    if (catalog.loading) return;
    let next: ChatPreferences;
    if (id) {
      if (!currentDetail) return;
      const conv = currentDetail.conversation;
      next = { server_id: conv.server_id || null, provider_id: conv.provider_id || null, model: conv.model || '', agent_id: conv.agent_id || null, project_id: conv.project_id || null, control_level: conv.control_level || user?.control_level || 'observe' };
    } else {
      if (preferencesLoading || preferencesKey !== navigationKey) return;
      const provider = catalog.providers.find(item => item.enabled);
      next = preferences ? { ...preferences } : { server_id: null, provider_id: provider?.id || null, model: provider?.default_model || provider?.models[0] || '', agent_id: null, project_id: null, control_level: user?.control_level || 'observe' };
      if (next.server_id && !catalog.servers.some(item => item.id === next.server_id)) next.server_id = null;
      if (next.project_id && !catalog.projects.some(item => item.id === next.project_id)) next.project_id = null;
      if (next.provider_id && !catalog.providers.some(item => item.id === next.provider_id && item.enabled)) { next.provider_id = null; next.model = ''; }
      if (query.has('server')) next.server_id = catalog.servers.find(item => item.id === query.get('server'))?.id || null;
      if (query.has('project')) next.project_id = catalog.projects.find(item => item.id === query.get('project'))?.id || null;
      if (query.has('agent')) {
        const agent = catalog.agents.find(item => item.id === query.get('agent') && item.kind !== 'remote' && canUseControl(user, item.control_level));
        next.agent_id = agent?.id || null;
        if (agent) {
          if (next.control_level !== 'observe' || agent.control_level === 'observe') next.control_level = agent.control_level;
          const linkedProvider = catalog.providers.find(item => item.id === agent.provider_id && item.enabled);
          if (linkedProvider) { next.provider_id = linkedProvider.id; next.model = agent.model || linkedProvider.default_model || linkedProvider.models[0] || ''; }
          else if (agent.model && !agent.provider_id) next.model = agent.model;
        }
      }
    }
    next.control_level = fallbackControl(user, next.control_level) || 'observe';
    if (next.agent_id && !catalog.agents.some(item => item.id === next.agent_id && item.kind !== 'remote' && canUseControl(user, item.control_level))) next.agent_id = null;
    applySettings(next);
    initialized.current = navigationKey; setConfigurationReady(true);
  }, [navigationKey, id, currentDetail, catalog, preferencesLoading, preferencesKey, preferences, query, user, applySettings]);

  useEffect(() => {
    if (!configurationReady || catalog.loading) return;
    const current = selection.current;
    const level = fallbackControl(user, current.control_level) || 'observe';
    const agent = current.agent_id ? catalog.agents.find(item => item.id === current.agent_id && item.kind !== 'remote' && canUseControl(user, item.control_level)) : null;
    const nextAgentId = agent?.id || null;
    if (level !== current.control_level || nextAgentId !== current.agent_id) applySettings({ ...current, control_level: level, agent_id: nextAgentId });
  }, [user, catalog.agents, catalog.loading, configurationReady, applySettings]);

  useEffect(() => { if (currentDetail) currentDetail.runs.forEach(run => { void watch(run.id).catch(() => undefined); }); }, [currentDetail?.runs, watch]);
  const eventCount = conversationRuns.reduce((total, run) => total + (snapshots[run.id]?.events.length || 0), 0);
  useEffect(() => { if (stickToBottom.current && timeline.current) timeline.current.scrollTo({ top: timeline.current.scrollHeight, behavior: 'smooth' }); }, [currentDetail?.messages.length, conversationRuns.length, eventCount, sending]);
  useEffect(() => {
    const focusRun = query.get('run');
    if (focusRun && currentDetail) {
      const timer = window.setTimeout(() => document.getElementById(`run-${focusRun}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 200);
      return () => window.clearTimeout(timer);
    }
  }, [query, currentDetail?.conversation.id]);
  useEffect(() => {
    if (textarea.current) {
      const element = textarea.current;
      element.style.height = '0px';
      element.style.height = `${Math.max(64, Math.min(element.scrollHeight, 144))}px`;
    }
  }, [input]);

  const changeSettings = (changes: Partial<ChatPreferences>) => {
    if (!configurationReady || activeRun) return;
    if (changes.control_level !== undefined && !canUseControl(user, changes.control_level)) { notify('管理员未授权此控制等级。', 'error'); return; }
    if (changes.agent_id && !catalog.agents.some(agent => agent.id === changes.agent_id && agent.kind !== 'remote' && canUseControl(user, agent.control_level))) { notify('管理员未授权此智能体的控制等级。', 'error'); return; }
    applySettings({ ...selection.current, ...changes });
    void saveChatPreferences(changes).catch(err => notify(`新会话配置保存失败：${errorMessage(err)}，请重新选择后重试。`, 'error'));
  };
  const changeAgent = (value: string) => {
    const changes: Partial<ChatPreferences> = { agent_id: value || null };
    const agent = catalog.agents.find(item => item.id === value && item.kind !== 'remote');
    if (value && (!agent || !canUseControl(user, agent.control_level))) { notify('管理员未授权此智能体的控制等级。', 'error'); return; }
    if (agent) {
      changes.control_level = agent.control_level;
      const provider = catalog.providers.find(item => item.id === agent.provider_id && item.enabled);
      if (provider) { changes.provider_id = provider.id; changes.model = agent.model || provider.default_model || provider.models[0] || ''; }
      else if (agent.model && !agent.provider_id) { changes.provider_id = selection.current.provider_id; changes.model = agent.model; }
    }
    changeSettings(changes);
  };
  const changeProvider = (value: string) => {
    if (value === selection.current.provider_id) return;
    const provider = catalog.providers.find(item => item.id === value && item.enabled);
    if (provider) changeSettings({ provider_id: provider.id, model: provider.default_model || provider.models[0] || '' });
  };
  const changeModel = (value: string) => {
    if (selectedProvider?.enabled) changeSettings({ provider_id: selectedProvider.id, model: value });
  };
  const send = useCallback(async () => {
    const content = input.trim();
    if (!content || sending || activeRun || !configurationReady) return;
    if (user?.role === 'admin' || !canUseControl(user, control)) {
      setSendError(user?.role === 'admin' ? '管理员账户不能执行本地任务。' : '管理员未授权当前控制等级，请选择已授权等级。');
      return;
    }
    if (agentId) {
      const agent = catalog.agents.find(item => item.id === agentId);
      if (!agent || agent.kind === 'remote' || !canUseControl(user, agent.control_level)) {
        setSendError('所选智能体已移除、改为远程或其控制等级管理员未授权，请重新选择本地智能体。');
        return;
      }
    }
    setSending(true); setSendError(''); stickToBottom.current = true;
    let conversationId = id;
    const settings = { server_id: serverId || null, provider_id: providerId || null, model: model || null, control_level: control, agent_id: agentId || null };
    try {
      if (!conversationId) {
        const created = await api.post<Conversation>('/conversations', { title: content.slice(0, 40), ...settings, project_id: projectId || null });
        conversationId = created.id;
      } else await api.patch(`/conversations/${conversationId}`, { ...settings, project_id: projectId || null });
      const run = await api.post<Run>(`/conversations/${conversationId}/messages`, { content, ...settings });
      setInput(''); navigate(`/chat/${conversationId}`);
      await register(run).catch(err => notify(`任务已提交，但状态同步暂时失败：${errorMessage(err)}`, 'info'));
      dataChanged();
    } catch (err) { setSendError(errorMessage(err)); if (conversationId) { navigate(`/chat/${conversationId}`); dataChanged(); } }
    finally { setSending(false); textarea.current?.focus(); }
  }, [input, sending, activeRun, configurationReady, id, serverId, providerId, model, control, agentId, projectId, navigate, register, notify, catalog.agents, user]);
  const removeConversation = (conv: Conversation) => confirm('删除这段对话？', `“${conv.title}”及其历史记录将被永久删除。运行中的任务请先停止。`, async () => {
    await api.delete(`/conversations/${conv.id}`); if (conv.id === id) navigate('/chat'); dataChanged(); notify('对话已删除');
  });
  const messages = currentDetail?.messages || [];
  const timelineItems = [
    ...messages.filter(message => message.role === 'user' || (message.role === 'assistant' && !conversationRuns.some(run => run.id === message.run_id && (snapshots[run.id]?.events.some(event => event.type === 'assistant' || event.type === 'assistant_delta') || snapshots[run.id]?.run.summary || run.summary)))).map(message => ({ kind: 'message' as const, time: message.created_at, id: message.id, message })),
    ...conversationRuns.map(run => ({ kind: 'run' as const, time: run.created_at, id: run.id, run })),
  ].sort((a, b) => a.time.localeCompare(b.time) || (a.kind === 'message' ? -1 : 1));

  return <div className={`chat-page ${!id ? 'chat-is-new' : ''}`}>
    <div className="chat-topline"><div className="chat-title"><span className="chat-title-icon"><MessageSquare size={18} /></span><div><strong>{currentDetail?.conversation.title || (id ? '加载对话…' : '新对话')}</strong><span>执行记录自动保存，切换页面持续运行</span></div></div><Button variant="ghost" className="button-small" onClick={() => setHistoryOpen(true)}><History size={16} /><span>历史对话</span></Button></div>
    <div className="chat-scroll" ref={timeline} onScroll={() => {
      const element = timeline.current;
      if (element) { const away = element.scrollHeight - element.scrollTop - element.clientHeight > 180; stickToBottom.current = !away; setAwayFromBottom(away); }
    }}>
      {!id ? <div className="chat-welcome">
        <div className="welcome-logo"><Sparkles size={28} strokeWidth={1.6} /></div>
        <h1>今天想解决什么？</h1>
        <p className="welcome-description">描述你的运维目标，交给 {brand.name} 规划、执行与验证。</p>
        <div className="prompt-grid">{prompts.map(prompt => <button type="button" className="prompt-card" key={prompt.title} onClick={() => { setInput(prompt.prompt); textarea.current?.focus(); }}><span className="prompt-icon"><prompt.icon size={19} /></span><div><h3>{prompt.title}</h3><p>{prompt.description}</p></div><ArrowUp size={14} /></button>)}</div>
        {!catalog.loading && !catalog.providers.some(provider => provider.enabled) && <p className="chat-setup-note"><Sparkles size={14} />请先在左侧「模型供应商」配置 API 地址与密钥。</p>}
      </div> : <div className="conversation-timeline">
        {detail.loading && !currentDetail ? <Loading text="正在恢复对话与执行记录…" /> : detail.error ? <ErrorState message={detail.error} retry={detail.reload} /> : timelineItems.length ? timelineItems.map(item => item.kind === 'run'
          ? <div className="timeline-run" key={`run-${item.id}`} id={`run-${item.id}`}><span className="assistant-avatar"><Sparkles size={18} /></span><div><div className="message-author">{brand.name}<span>运维执行引擎</span></div><RunCard run={item.run} /></div></div>
          : <div className={`message message-${item.message.role}`} key={item.id}><span className={item.message.role === 'user' ? 'message-avatar' : 'assistant-avatar'}>{item.message.role === 'user' ? user?.avatar || initials(user?.name || '') : <Bot size={18} />}</span><div className="message-body"><div className="message-author">{item.message.role === 'user' ? user?.name || '你' : brand.name}<span>{dateTime(item.message.created_at, true)}</span></div><div className="message-content"><Content text={item.message.content} /></div></div></div>)
          : <EmptyState compact icon={MessageSquare} title="对话已准备好" description="描述你想完成的任务，智能体会先规划再执行。" />}
        {sending && <div className="sending-indicator"><span /><span /><span />正在提交任务…</div>}
        {awayFromBottom && <button className="scroll-bottom" onClick={() => { stickToBottom.current = true; timeline.current?.scrollTo({ top: timeline.current.scrollHeight, behavior: 'smooth' }); }} aria-label="回到最新消息"><ArrowDown size={15} /></button>}
      </div>}
    </div>
    <div className="composer-region"><div className="composer-inner">
      {activeRun && <div className="active-conversation-run"><span><span className="live-dot" />任务在后台执行中，执行卡片中可审批或停止</span></div>}
      {executionBlocked && <div className="control-permission-hint" role="status">{executionBlocked}</div>}
      {sendError && <div className="inline-error" role="alert">{sendError}<button className="icon-button" onClick={() => setSendError('')} aria-label="关闭错误"><X size={14} /></button></div>}
      <form className={`composer ${activeRun ? 'composer-busy' : ''}`} onSubmit={event => { event.preventDefault(); void send(); }}>
        <div className="composer-context-row">
          <Select label="选择智能体" compact searchable placement="top" icon={<WandSparkles size={15} />} value={agentId} onChange={changeAgent} disabled={Boolean(activeRun) || !configurationReady} options={[{ value: '', label: '通用运维助手', description: '使用当前会话配置', icon: <Bot size={16} /> }, ...catalog.agents.filter(agent => agent.kind !== 'remote').map(agent => ({ value: agent.id, label: agent.name, description: canUseControl(user, agent.control_level) ? agent.description : `管理员未授权${controlLabels[agent.control_level]}`, disabled: !canUseControl(user, agent.control_level), icon: <Bot size={16} /> }))]} />
          <Select label="项目上下文" compact searchable placement="top" icon={<FolderKanban size={15} />} value={projectId} onChange={value => changeSettings({ project_id: value || null })} disabled={Boolean(activeRun) || !configurationReady} options={[{ value: '', label: '不关联项目', description: '使用独立会话上下文' }, ...catalog.projects.filter(project => project.status === 'active' || project.id === projectId).map(project => ({ value: project.id, label: project.name, description: project.description }))]} />
          <span className="composer-online"><ShieldCheck size={13} />变更受控</span>
        </div>
        <textarea ref={textarea} value={input} onChange={event => setInput(event.target.value)} placeholder={activeRun ? '任务执行中，可以先构思下一条消息…' : '描述目标，或提出一个运维问题…'} aria-label="消息内容" rows={2} maxLength={32000} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
        <div className="composer-toolbar"><div className="composer-controls">
          <Select label="选择服务器" compact searchable placement="top" icon={<Server size={15} />} value={serverId} onChange={value => changeSettings({ server_id: value || null })} disabled={Boolean(activeRun) || !configurationReady} options={[{ value: '', label: '不连接服务器', description: '仅使用对话、知识与个人文件' }, ...catalog.servers.map(server => ({ value: server.id, label: server.name, description: server.kind === 'ssh' ? `${server.host}:${server.port}${server.status === 'offline' ? ' · 最近连接失败' : ''}` : 'Kubernetes 集群', keywords: server.host }))]} />
          <Select label="选择供应商" compact searchable placement="top" className="composer-provider-picker" icon={<Globe2 size={15} />} value={providerId} onChange={changeProvider} disabled={Boolean(activeRun) || !configurationReady} options={catalog.providers.filter(provider => provider.enabled || provider.id === providerId).map(provider => ({ value: provider.id, label: provider.name, description: provider.enabled ? `${provider.models.length} 个可选模型` : '已停用', disabled: !provider.enabled }))} placeholder="选择供应商" emptyText="暂无供应商，请先配置 API 地址和密钥" />
          <Select label="选择模型" compact searchable allowCustom={Boolean(selectedProvider?.enabled)} placement="top" className="composer-model-picker" icon={<Sparkles size={15} />} value={model} onChange={changeModel} disabled={Boolean(activeRun) || !configurationReady || !selectedProvider?.enabled} options={modelOptions} placeholder={selectedProvider ? '选择模型' : '先选择供应商'} emptyText="当前供应商暂无模型，可搜索并填写自定义模型名" />
        </div><div className="composer-send-controls">
          <Select label="控制等级" compact placement="top" className={`level-${control}`} icon={<ShieldCheck size={15} />} value={controlAllowed ? control : ''} placeholder="暂无已授权等级" onChange={value => changeSettings({ control_level: value as ControlLevel })} disabled={Boolean(activeRun) || !configurationReady} options={Object.entries(controlLabels).map(([value, label]) => ({ value, label, disabled: !canUseControl(user, value), description: canUseControl(user, value) ? controlDescriptions[value as ControlLevel] : `管理员未授权 · ${controlDescriptions[value as ControlLevel]}` }))} />
          <Button type="submit" className="send-button" busy={sending} disabled={!configurationReady || !input.trim() || Boolean(activeRun) || Boolean(id && !currentDetail) || Boolean(executionBlocked)} title={executionBlocked || undefined} aria-label="发送消息">{!sending && <ArrowUp size={20} />}</Button>
        </div></div>
      </form>
      <div className="composer-caption"><span>{selectedProvider ? `${selectedProvider.name} · ` : ''}AI 可能出错，请核实关键操作。</span><span><kbd>Enter</kbd> 发送 · <kbd>Shift ↵</kbd> 换行</span></div>
      {catalog.error && <div className="small muted">资源目录加载异常：{catalog.error}</div>}
    </div></div>
    {historyOpen && <Modal title="历史对话" description={`${history.data.length} 段对话，保留完整执行记录。`} onClose={() => setHistoryOpen(false)} wide><div className="history-content"><SearchInput value={historySearch} onChange={setHistorySearch} placeholder="搜索对话标题…" />{history.error && <ErrorState message={history.error} retry={history.reload} />}{history.loading ? <Loading /> : history.data.length ? <div className="history-list">{history.data.filter(conv => conv.title.toLowerCase().includes(historySearch.toLowerCase())).map(conv => <div className="history-item" key={conv.id}><button type="button" className="history-open-conversation" onClick={() => { navigate(`/chat/${conv.id}`); setHistoryOpen(false); }}><span className="history-item-icon"><MessageSquare size={18} /></span><div><strong>{conv.title || '未命名对话'}</strong><span>{relativeTime(conv.updated_at)} · {conv.model || '未选模型'}</span></div></button><button className="icon-button" aria-label="重命名对话" onClick={() => { setHistoryOpen(false); setRename(conv); }}><Pencil size={15} /></button><button className="icon-button danger-text" aria-label="删除对话" onClick={() => { setHistoryOpen(false); removeConversation(conv); }}><Trash2 size={15} /></button></div>)}</div> : <EmptyState compact icon={History} title="还没有历史对话" description="每一次对话与任务都会自动保存在这里。" />}</div></Modal>}
    {rename && <FormDialog title="重命名对话" onClose={() => setRename(null)} onSubmit={async form => { await api.patch(`/conversations/${rename.id}`, { title: String(form.get('title')).trim() }); dataChanged(); }}><Field label="对话标题" required><input name="title" required defaultValue={rename.title} maxLength={120} /></Field></FormDialog>}
    {dialog}
  </div>;
}
