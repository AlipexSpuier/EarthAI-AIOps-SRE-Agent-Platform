import { useLayoutEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowDown, ArrowRight, ArrowUp, ArrowUpDown, ArrowUpRight, Blocks, BookOpen, Bot, Check, Eye, FileCode2, FolderKanban, Globe, GripVertical, Pencil, Server, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useCatalog } from '../context/CatalogContext';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api, errorMessage } from '../lib/api';
import { colorChoices, controlLabels } from '../lib/format';
import { canUseControl } from '../lib/controlAccess';
import { dataChanged, useResource } from '../lib/hooks';
import type { Agent, Project, Skill } from '../types';
import { UserResourceImportButton } from '../components/UserResourceImport';
import { Select } from '../components/Select';
import { Banner, Button, ControlBadge, ControlSelect, EmptyState, ErrorState, Field, FormDialog, Loading, Modal, MultiSelect, NewButton, PageHeader, SearchInput, StatusBadge, Switch, formList, formString, useConfirm } from '../components/ui';
import './Agents.css';
import './ResourcePermissions.css';
import './LibraryWorkbench.css';
import './ExecutionPermissions.css';

export function AgentsPage() {
  const resource = useResource<Agent[]>('/agents', []);
  const { user } = useAuth();
  const [edit, setEdit] = useState<Agent | 'new' | null>(null);
  const [view, setView] = useState<Agent | null>(null);
  const [search, setSearch] = useState('');
  const [ordering, setOrdering] = useState(false);
  const { confirm, dialog } = useConfirm();
  const notify = useToast();
  const filtered = resource.data.filter(agent => `${agent.name} ${agent.description}`.toLowerCase().includes(search.toLowerCase()));
  const reportRemoteOpen = async (agent: Agent) => {
    try {
      await api.post(`/agents/${agent.id}/open`);
      resource.setData(agents => agents.map(item => item.id === agent.id && typeof item.usage_count === 'number' ? { ...item, usage_count: item.usage_count + 1 } : item));
    } catch (err) {
      notify(`“${agent.name}”的点击记录上报失败：${errorMessage(err)}。外部链接由浏览器处理，无法确认是否打开。`, 'error');
    }
  };

  return <div className="page ea-agents-page">
    <PageHeader eyebrow="YOUR AI TEAM" title="让专业，有专属的伙伴" description="定制本地智能体的专业能力，或接入远程智能体，让协作更合拍。" action={<>
      <Button variant="secondary" onClick={() => setOrdering(true)} disabled={resource.loading || Boolean(resource.error) || resource.data.length < 2}><ArrowUpDown size={16} />调整排序</Button>
      <UserResourceImportButton kind="agents" label="智能体" />
      <NewButton onClick={() => setEdit('new')}>创建智能体</NewButton>
    </>} />
    <div className="list-toolbar"><span className="muted small">{resource.data.length} 个专属智能体</span><SearchInput value={search} onChange={setSearch} placeholder="搜索智能体名称或职责…" /></div>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}
    {resource.loading ? <Loading /> : !resource.data.length ? <div className="panel"><EmptyState compact icon={Bot} title="组建你的 AI 运维团队" description="为本地助手配置指令、知识和技能，或添加远程智能体的访问地址。" /></div> : !filtered.length ? <EmptyState compact icon={Bot} title="没有找到智能体" description="请调整搜索关键词。排序始终包含全部智能体。" /> : <div className="agent-grid">
      {filtered.map(agent => {
        const remote = agent.kind === 'remote';
        const executable = remote || (user?.role !== 'admin' && canUseControl(user, agent.control_level));
        const reason = user?.role === 'admin' ? '管理员账户不能执行本地任务。' : `管理员未授权${controlLabels[agent.control_level]}，可编辑个人配置改为已授权等级。`;
        return <article className={`agent-card${executable ? '' : ' control-permission-disabled'}`} key={agent.id} data-agent-id={agent.id} data-control-blocked={!executable || undefined}>
          <div className="agent-card-top">
            <span className="agent-avatar" style={{ background: `${agent.color}15`, color: agent.color }}>{['Bot', 'bot', ''].includes(agent.icon) ? remote ? <Globe size={27} /> : <Bot size={27} /> : agent.icon}</span>
            <div className="ea-agent-card-badges"><span className={`ea-agent-kind${remote ? ' ea-agent-kind-remote' : ''}`}>{remote ? '远程' : '本地'}</span>{!remote && <ControlBadge level={agent.control_level} />}<ResourceOrigin resource={agent} /></div>
          </div>
          <h3>{agent.name}</h3>
          <p>{agent.description || (remote ? '通过独立站点提供服务的远程智能体。' : '一个等待被赋予使命的专属运维助手。')}</p>
          {remote ? <>
            <div className="ea-agent-remote-address"><Globe size={14} /><span>{agent.url}</span></div>
            <div className="ea-agent-remote-note">在新窗口中访问独立站点</div>
          </> : <>
            <div className="agent-abilities"><span><Blocks size={13} />{agent.skill_ids.length} 项技能</span><span><BookOpen size={13} />{agent.knowledge_ids.length} 个知识库</span></div>
            <div className="agent-model"><Sparkles size={12} />{agent.model || '在对话中选择模型'}</div>
          </>}
          {typeof agent.usage_count === 'number' && <div className="ea-resource-usage">调用 {agent.usage_count} 次</div>}
          {!executable && <p className="control-permission-note">{reason}</p>}
          <div className="resource-card-footer">
            {remote ? <a className="button button-secondary button-small ea-agent-remote-open" href={agent.url} target="_blank" rel="noopener noreferrer" onClick={event => { if (event.button === 0) void reportRemoteOpen(agent); }} onAuxClick={event => { if (event.button === 1) void reportRemoteOpen(agent); }}><Globe size={14} />打开远程智能体<ArrowUpRight size={13} /></a> : executable ? <Link className="button button-secondary button-small" to={`/chat?agent=${agent.id}`}><MessageIcon />与它对话<ArrowUpRight size={13} /></Link> : <Button variant="secondary" className="button-small control-permission-disabled" disabled title={reason}><MessageIcon />与它对话<ArrowUpRight size={13} /></Button>}
            <div className="card-footer-spacer" />
            {agent.read_only ? <Button variant="ghost" className="button-small" onClick={() => setView(agent)}><Eye size={15} />查看配置</Button> : <>
              <button className="icon-button" aria-label="编辑智能体" onClick={() => setEdit(agent)}><Pencil size={15} /></button>
              <button className="icon-button danger-text" aria-label="删除智能体" onClick={() => confirm('删除智能体？', `“${agent.name}”的专属配置将被删除，已有执行记录不会因此被伪造或修改。`, async () => { if (agent.read_only) return; await api.delete(`/agents/${agent.id}`); dataChanged(); notify('智能体已删除'); })}><Trash2 size={15} /></button>
            </>}
          </div>
        </article>;
      })}
    </div>}
    {edit && (edit === 'new' || !edit.read_only) && <AgentForm value={edit} onClose={() => setEdit(null)} />}
    {view && <AgentDetails agent={resource.data.find(agent => agent.id === view.id) || view} onClose={() => setView(null)} />}
    {ordering && <AgentOrderDialog agents={resource.data} onClose={() => setOrdering(false)} />}
    {dialog}
  </div>;
}

function ResourceOrigin({ resource }: { resource: { read_only?: boolean; default_template_id?: string; personal_override?: boolean } }) {
  if (resource.read_only) return <span className="ea-resource-read-only">系统默认 · 只读</span>;
  if (!resource.default_template_id && !resource.personal_override) return null;
  return <span className="ea-resource-origin" title={resource.personal_override ? '已保存为个人定制副本，与系统模板独立；修改和删除仅影响当前账户，删除后不会重新出现。' : '这是当前账户的默认副本，可编辑或删除；保存后与系统模板独立，不影响其他用户，删除后不会重新出现。'}>{resource.personal_override ? '默认来源 · 已个人定制' : '系统默认 · 可编辑'}</span>;
}

function AgentDetails({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const catalog = useCatalog();
  return <Modal title={`查看配置 · ${agent.name}`} description="系统默认智能体配置由管理员维护；本地对话需获控制等级授权，远程访问和个人排序不受影响。" onClose={onClose} wide>
    <div className="ea-resource-details">
      <span className="ea-resource-read-only">系统默认 · 只读</span>
      <dl>
        <div><dt>智能体名称</dt><dd>{agent.name}</dd></div>
        <div><dt>职责描述</dt><dd>{agent.description || '未添加描述'}</dd></div>
        <div><dt>智能体类型</dt><dd>{agent.kind === 'remote' ? '远程智能体' : '本地智能体'}</dd></div>
        {typeof agent.usage_count === 'number' && <div><dt>调用次数</dt><dd>调用 {agent.usage_count} 次</dd></div>}
        <div><dt>头像标识与颜色</dt><dd>{agent.icon || 'Bot'} · {agent.color}</dd></div>
        {agent.kind === 'remote' ? <div><dt>远程智能体 URL</dt><dd>{agent.url}</dd></div> : <>
          <div><dt>系统指令</dt><dd>{agent.system_prompt || '未配置系统指令'}</dd></div>
          <div><dt>模型供应商</dt><dd>{agent.provider_id ? catalog.providers.find(provider => provider.id === agent.provider_id)?.name || '已移除资源' : '在对话中选择'}</dd></div>
          <div><dt>偏好模型</dt><dd>{agent.model || '沿用对话选择'}</dd></div>
          <div><dt>默认控制等级</dt><dd><ControlBadge level={agent.control_level} /></dd></div>
          <div><dt>关联技能</dt><dd>{agent.skill_ids.length ? <div className="tag-row">{agent.skill_ids.map(id => <span className="resource-tag" key={id}>{catalog.skills.find(skill => skill.id === id)?.name || '已移除资源'}</span>)}</div> : '未关联技能'}</dd></div>
          <div><dt>关联知识库</dt><dd>{agent.knowledge_ids.length ? <div className="tag-row">{agent.knowledge_ids.map(id => <span className="resource-tag" key={id}>{catalog.knowledge.find(knowledge => knowledge.id === id)?.name || '已移除资源'}</span>)}</div> : '未关联知识库'}</dd></div>
        </>}
      </dl>
    </div>
    <div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭</Button></div>
  </Modal>;
}

function AgentOrderDialog({ agents, onClose }: { agents: Agent[]; onClose: () => void }) {
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
    setAnnouncement(`${agent.name}已移至第 ${to + 1} 位，共 ${next.length} 个智能体。`);
  };
  const endDrag = () => { draggedId.current = null; setDragging(null); setDropTarget(null); };
  const save = async () => {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setError('');
    try {
      await api.post('/agents/reorder', { agent_ids: order.map(agent => agent.id) });
      dataChanged();
      notify('智能体排序已保存');
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      saving.current = false;
      setPending(false);
    }
  };

  return <Modal title="调整智能体排序" description="拖动列表，或使用上移、下移按钮。保存后，所有设备都会沿用此顺序。" onClose={onClose} preventClose={pending}>
    <div className="ea-agent-order" aria-busy={pending}>
      <div className="ea-agent-order-body">
        <p className="ea-agent-order-hint">全部 {order.length} 个智能体，不受页面搜索影响。新增智能体默认排在末尾。</p>
        <ol className="ea-agent-order-list" aria-label="全部智能体排序列表">
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
        {error && <div className="inline-error" role="alert"><AlertCircle size={17} />{error}</div>}
      </div>
      <div className="modal-footer ea-agent-order-footer">
        <span className="small muted">{pending ? '正在保存排序…' : '仅在保存后生效'}</span>
        <Button type="button" variant="secondary" disabled={pending} onClick={onClose}>取消</Button>
        <Button type="button" busy={pending} onClick={() => { void save(); }}><Check size={16} />保存排序</Button>
      </div>
    </div>
  </Modal>;
}

function MessageIcon() { return <Sparkles size={14} />; }
function ColorPicker({ defaultValue }: { defaultValue?: string }) { return <fieldset className="color-picker"><legend>标识颜色</legend>{colorChoices.map(color => <label key={color} style={{ '--choice-color': color } as React.CSSProperties}><input type="radio" name="color" value={color} defaultChecked={(defaultValue || colorChoices[0]) === color} /><span /></label>)}</fieldset>; }
function AgentForm({ value, onClose }: { value: Agent | 'new'; onClose: () => void }) {
  const item = value === 'new' ? null : value;
  const catalog = useCatalog();
  const { user } = useAuth();
  const notify = useToast();
  const [providerId, setProviderId] = useState(item?.provider_id || '');
  const [kind, setKind] = useState<'local' | 'remote'>(item?.kind === 'remote' ? 'remote' : 'local');
  const provider = catalog.providers.find(provider => provider.id === providerId);
  const inheritedLocal = Boolean(item?.default_template_id && item.kind !== 'remote');

  return <FormDialog title={item ? '编辑智能体' : '创建专属智能体'} description="配置本地助手的专业能力，或添加远程智能体的独立访问入口。" onClose={onClose} wide onSubmit={async form => {
    if (item?.read_only) throw new Error('系统默认资源为只读，无法修改。');
    const url = kind === 'remote' ? formString(form, 'url') : '';
    if (kind === 'remote') {
      let valid = false;
      try { const parsed = new URL(url); valid = ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.hostname); } catch { valid = false; }
      if (!valid) throw new Error('请输入有效的 http:// 或 https:// 智能体地址。');
    }
    const level = formString(form, 'control_level');
    if (kind === 'local' && !canUseControl(user, level)) throw new Error('管理员未授权此控制等级，请选择已授权等级后保存。');
    const shared = { name: formString(form, 'name'), description: formString(form, 'description'), icon: formString(form, 'icon') || 'Bot', color: formString(form, 'color'), kind, url };
    const payload = kind === 'remote' ? shared : { ...shared, system_prompt: formString(form, 'system_prompt'), skill_ids: formList(form, 'skill_ids'), knowledge_ids: formList(form, 'knowledge_ids'), provider_id: providerId || null, model: formString(form, 'model') || null, control_level: level };
    await (item ? api.patch(`/agents/${item.id}`, payload) : api.post('/agents', payload));
    dataChanged();
    notify('智能体已保存');
  }}>
    <div className="ea-agent-form">
      {item?.default_template_id && <Banner>这是当前账户的默认副本。保存后成为与系统模板独立的个人配置，修改不影响其他用户；删除后不会重新出现。</Banner>}
      <Field label="智能体类型" hint={inheritedLocal ? '默认本地智能体可定制，但不能转换为远程智能体。' : kind === 'remote' ? '远程智能体通过新窗口访问，不使用本地模型、技能或执行上下文。' : '本地智能体在 EarthAI 中对话，使用此处配置的指令和能力。'}>
        {inheritedLocal ? <div className="ea-resource-fixed-type"><Bot size={16} /><span>本地智能体</span><input type="hidden" name="kind" value="local" /></div> : <Select name="kind" label="智能体类型" value={kind} onChange={next => setKind(next as 'local' | 'remote')} options={[
          { value: 'local', label: '本地智能体', description: '在 EarthAI 中配置并执行', icon: <Bot size={16} /> },
          { value: 'remote', label: '远程智能体', description: '通过 HTTP / HTTPS 地址访问独立站点', icon: <Globe size={16} /> },
        ]} />}
      </Field>
      <div className="form-grid"><Field label="智能体名称" required><input name="name" required defaultValue={item?.name} placeholder="例如：生产巡检助手" maxLength={100} /></Field><Field label="头像标识" hint="支持 1–2 个文字或简短符号"><input name="icon" defaultValue={item?.icon === 'Bot' ? '' : item?.icon} maxLength={4} placeholder="留空使用机器人图标" /></Field></div>
      {kind === 'remote' && <Field label="远程智能体 URL" required hint="请输入完整的 http:// 或 https:// 地址。点击卡片将在新窗口中打开。"><input name="url" type="url" required pattern="[Hh][Tt][Tt][Pp][Ss]?://.+" defaultValue={item?.url || ''} placeholder="https://agent.example.com" autoComplete="url" /></Field>}
      <ColorPicker defaultValue={item?.color} />
      <Field label="职责描述"><input name="description" defaultValue={item?.description} placeholder="简要说明它擅长什么，以及适合的任务" maxLength={300} /></Field>
      {kind === 'local' ? <div className="ea-agent-local-fields">
        <Field label="系统指令" required hint="定义角色、工作方式、业务约束和安全边界。这些内容会真实注入智能体执行上下文。"><textarea name="system_prompt" className="instruction-editor" rows={7} required defaultValue={item?.system_prompt} placeholder="你是一位谨慎的运维专家。优先执行只读检查，先规划再行动。对变更操作说明风险…" /></Field>
        <div className="form-grid"><Field label="模型供应商"><Select label="模型供应商" value={providerId} onChange={setProviderId} searchable options={[{ value: '', label: '在对话中选择' }, ...catalog.providers.map(provider => ({ value: provider.id, label: provider.name }))]} /></Field><Field label="偏好模型"><Select label="偏好模型" name="model" defaultValue={item?.model || ''} searchable allowCustom options={[{ value: '', label: provider?.default_model || '沿用对话选择' }, ...(provider?.models || []).map(model => ({ value: model, label: model }))]} /></Field></div>
        <Field label="默认控制等级"><ControlSelect defaultValue={item?.control_level || user?.control_level} /></Field>
        <MultiSelect label="关联技能" name="skill_ids" options={catalog.skills} selected={item?.skill_ids} hint="先到技能库添加可信指令，再为智能体关联。" />
        <MultiSelect label="关联知识库" name="knowledge_ids" options={catalog.knowledge} selected={item?.knowledge_ids} />
        <Banner>技能和知识库会作为可信上下文参与真实执行。请勿将未经审阅的外部文本写入系统指令。</Banner>
      </div> : <Banner>远程智能体的对话与执行由目标站点负责。这里只保存名称、访问地址和展示信息，不会向该地址发送本地凭据或执行请求。</Banner>}
    </div>
  </FormDialog>;
}
export function SkillsPage() {
  const resource = useResource<Skill[]>('/skills', []);
  const [search, setSearch] = useState('');
  const [edit, setEdit] = useState<Skill | 'new' | null>(null);
  const [view, setView] = useState<Skill | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const documentRef = useRef<HTMLElement>(null);
  const { confirm, dialog } = useConfirm();
  const notify = useToast();
  const filtered = resource.data.filter(skill => `${skill.name} ${skill.description}`.toLowerCase().includes(search.toLowerCase()));
  const active = filtered.find(skill => skill.id === selected) || filtered[0];

  useLayoutEffect(() => {
    if (documentRef.current) documentRef.current.scrollTop = 0;
  }, [active?.id]);

  return <div className="page skills-page">
    <PageHeader eyebrow="REUSABLE EXPERTISE" title="把经验，变成可复用的能力" description="将排查手册与运维规范沉淀为技能，给每个智能体专业的行动指南。" action={<><UserResourceImportButton kind="skills" label="技能" /><NewButton onClick={() => setEdit('new')}>创建技能</NewButton></>} />
    <div className="list-toolbar">
      <div className="skill-explainer"><Blocks size={16} /><span>技能是可信的指令上下文，不是可执行的上传代码。</span></div>
      <SearchInput value={search} onChange={setSearch} placeholder="查找技能…" />
    </div>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}
    {resource.loading ? <Loading /> : !resource.data.length ? <div className="panel">
      <EmptyState compact icon={Blocks} title="每一份经验，都值得复用" description="写下一套诊断步骤或业务规范，在智能体中启用它，让专业经验融入每一次执行。" />
    </div> : <div className="skills-workbench">
      <aside className="skill-list" role="region" aria-label="技能目录" tabIndex={0}>
        <div className="skill-list-label">全部技能 <span>{filtered.length}</span></div>
        {filtered.map(skill => <button key={skill.id} className={active?.id === skill.id ? 'selected' : ''} aria-pressed={active?.id === skill.id} onClick={() => setSelected(skill.id)}>
          <span className="skill-list-icon"><FileCode2 size={19} /></span>
          <span><strong>{skill.name}</strong><small>{skill.description || '可信运维指令'}</small></span>
          <i className={skill.enabled ? 'enabled-dot' : 'disabled-dot'} />
        </button>)}
      </aside>
      {active ? <article ref={documentRef} className="skill-document" role="region" aria-label="技能正文" tabIndex={0} data-skill-id={active.id}>
        <div className="skill-document-header">
          <div><span className="document-kicker">SKILL DOCUMENT</span><h2>{active.name}</h2><p>{active.description || '未添加技能描述'}</p></div>
          <div className="ea-resource-actions">
            <ResourceOrigin resource={active} />
            {active.read_only ? <Button variant="ghost" className="button-small" onClick={() => setView(active)}><Eye size={15} />查看配置</Button> : <>
              <button className="icon-button" aria-label="编辑技能" onClick={() => setEdit(active)}><Pencil size={16} /></button>
              <button className="icon-button danger-text" aria-label="删除技能" onClick={() => confirm('删除技能？', `移除“${active.name}”后，依赖它的智能体将不再获得这项指令。`, async () => {
                if (active.read_only) return;
                await api.delete(`/skills/${active.id}`);
                dataChanged();
                notify('技能已删除');
              })}><Trash2 size={16} /></button>
            </>}
          </div>
        </div>
        <div className="skill-document-meta">
          <span><ShieldCheck size={14} />可信指令上下文</span>
          {typeof active.usage_count === 'number' && <span className="ea-resource-usage">调用 {active.usage_count} 次</span>}
          {active.read_only ? <span className="ea-resource-state">{active.enabled ? '技能已启用' : '技能已停用'}</span> : <Switch label={active.enabled ? '技能已启用' : '技能已停用'} checked={active.enabled} onChange={enabled => {
            if (active.read_only) return;
            void api.patch(`/skills/${active.id}`, { enabled }).then(() => dataChanged()).catch(err => notify(errorMessage(err), 'error'));
          }} />}
        </div>
        <pre className="skill-source">{active.content}</pre>
        <div className="skill-document-footer"><span>{active.content.length} 字符</span></div>
      </article> : <EmptyState compact title="没有找到技能" description="请调整搜索关键词。" />}
    </div>}
    {edit && (edit === 'new' || !edit.read_only) && <FormDialog title={edit === 'new' ? '创建技能' : '编辑技能'} description="写清适用范围、操作步骤与安全约束。技能内容作为指令提供给模型，不会直接执行。" onClose={() => setEdit(null)} wide onSubmit={async form => {
      if (edit !== 'new' && edit.read_only) throw new Error('系统默认资源为只读，无法修改。');
      const payload = { name: formString(form, 'name'), description: formString(form, 'description'), content: formString(form, 'content'), enabled: form.has('enabled') };
      await (edit === 'new' ? api.post('/skills', payload) : api.patch(`/skills/${edit.id}`, payload));
      dataChanged();
      notify('技能已保存');
    }}>
      {edit !== 'new' && edit.default_template_id && <Banner>这是当前账户的默认技能副本。保存后与系统模板独立，修改或停用不影响其他用户；删除后不会重新出现。</Banner>}
      <Field label="技能名称" required><input name="name" required defaultValue={edit === 'new' ? '' : edit.name} maxLength={120} placeholder="例如：Linux 只读健康巡检" /></Field>
      <Field label="技能描述"><input name="description" defaultValue={edit === 'new' ? '' : edit.description} placeholder="说明适用场景与能力边界" /></Field>
      <Field label="技能指令" required hint="支持纯文本或 Markdown。代码片段仅作为阅读上下文，是否执行由工具与控制模式决定。"><textarea name="content" className="mono instruction-editor" rows={14} required defaultValue={edit === 'new' ? '' : edit.content} placeholder={'# 适用场景\n\n# 检查步骤\n1. 查看…\n2. 分析…\n\n# 安全约束\n不执行破坏性变更。'} /></Field>
      <Switch name="enabled" label="启用该技能" defaultChecked={edit === 'new' || edit.enabled} />
    </FormDialog>}
    {view && <SkillDetails skill={view} onClose={() => setView(null)} />}
    {dialog}
  </div>;
}
function SkillDetails({ skill, onClose }: { skill: Skill; onClose: () => void }) {
  return <Modal title={`查看配置 · ${skill.name}`} description="系统默认技能由管理员维护；完整指令可查看，并可关联到自建智能体使用。" onClose={onClose} wide>
    <div className="ea-resource-details">
      <span className="ea-resource-read-only">系统默认 · 只读</span>
      <dl>
        <div><dt>技能名称</dt><dd>{skill.name}</dd></div>
        <div><dt>技能描述</dt><dd>{skill.description || '未添加描述'}</dd></div>
        <div><dt>启用状态</dt><dd>{skill.enabled ? '已启用' : '已停用'}</dd></div>
        {typeof skill.usage_count === 'number' && <div><dt>调用次数</dt><dd>调用 {skill.usage_count} 次</dd></div>}
        <div><dt>技能指令</dt><dd>{skill.content || '未配置技能指令'}</dd></div>
      </dl>
    </div>
    <div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭</Button></div>
  </Modal>;
}
export function ProjectsPage() {
  const resource = useResource<Project[]>('/projects', []); const catalog = useCatalog(); const [edit, setEdit] = useState<Project | 'new' | null>(null); const [view, setView] = useState<Project | null>(null); const [search, setSearch] = useState(''); const [filter, setFilter] = useState('active'); const { confirm, dialog } = useConfirm(); const notify = useToast();
  const filtered = resource.data.filter(project => (filter === 'all' || project.status === filter) && `${project.name} ${project.description}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="page"><PageHeader eyebrow="CONTEXT THAT CONNECTS" title="以业务，组织你的世界" description="把服务器与知识聚合进项目，让每次对话都拥有完整上下文。" action={<><UserResourceImportButton kind="projects" label="项目" /><NewButton onClick={() => setEdit('new')}>创建项目</NewButton></>} /><div className="list-toolbar"><div className="segment-control">{[{ value: 'active', label: '进行中' }, { value: 'archived', label: '已归档' }, { value: 'all', label: '全部项目' }].map(option => <button key={option.value} className={filter === option.value ? 'selected' : ''} onClick={() => setFilter(option.value)}>{option.label}</button>)}</div><SearchInput value={search} onChange={setSearch} placeholder="搜索项目名称…" /></div>{resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading /> : !resource.data.length ? <div className="panel"><EmptyState compact icon={FolderKanban} title="给业务一个专属空间" description="将相关资源纳入同一个项目，为你的应用、环境或团队建立清晰的运维边界。" /></div> : <div className="project-grid">{filtered.map(project => <article className="project-card" key={project.id} style={{ '--project-color': project.color || '#087f69' } as React.CSSProperties}><div className="project-card-heading"><span className="project-icon"><FolderKanban size={23} /></span><StatusBadge status={project.status} />{project.read_only && <span className="ea-resource-read-only">系统默认 · 只读</span>}</div><h3>{project.name}</h3><p>{project.description || '还没有为这个项目添加描述。'}</p><div className="project-resources"><div><Server size={16} /><strong>{project.server_ids.length}</strong><span>服务器</span></div><div><BookOpen size={16} /><strong>{project.knowledge_ids.length}</strong><span>知识库</span></div></div><div className="project-resource-names">{project.server_ids.slice(0, 3).map(id => <span className="resource-tag" key={id}>{catalog.servers.find(server => server.id === id)?.name || '已移除资源'}</span>)}</div><div className="resource-card-footer"><Link className="text-link" to={`/chat?project=${project.id}`}>进入项目对话<ArrowRight size={15} /></Link><div className="card-footer-spacer" />{project.read_only ? <Button variant="ghost" className="button-small" onClick={() => setView(project)}><Eye size={15} />查看配置</Button> : <><button className="icon-button" aria-label="编辑项目" onClick={() => setEdit(project)}><Pencil size={15} /></button><button className="icon-button danger-text" aria-label="删除项目" onClick={() => confirm('删除项目？', `仅删除“${project.name}”的项目配置，不会删除关联的服务器或知识库。`, async () => { if (project.read_only) return; await api.delete(`/projects/${project.id}`); dataChanged(); notify('项目已删除'); })}><Trash2 size={15} /></button></>}</div></article>)}</div>}{resource.data.length > 0 && !filtered.length && <EmptyState compact icon={FolderKanban} title="当前视图下没有项目" description="试试切换项目状态，或创建一个新项目。" />}{edit && (edit === 'new' || !edit.read_only) && <ProjectForm value={edit} onClose={() => setEdit(null)} />}{view && <ProjectDetails project={view} onClose={() => setView(null)} />}{dialog}</div>;
}
function ProjectDetails({ project, onClose }: { project: Project; onClose: () => void }) {
  const catalog = useCatalog();
  return <Modal title={`查看配置 · ${project.name}`} description="系统默认项目由管理员维护；关联资源仍可作为对话上下文使用。" onClose={onClose} wide>
    <div className="ea-resource-details">
      <span className="ea-resource-read-only">系统默认 · 只读</span>
      <dl>
        <div><dt>项目名称</dt><dd>{project.name}</dd></div>
        <div><dt>项目描述</dt><dd>{project.description || '未添加描述'}</dd></div>
        <div><dt>标识颜色</dt><dd>{project.color}</dd></div>
        <div><dt>项目状态</dt><dd><StatusBadge status={project.status} /></dd></div>
        <div><dt>关联服务器</dt><dd>{project.server_ids.length ? <div className="tag-row">{project.server_ids.map(id => <span className="resource-tag" key={id}>{catalog.servers.find(server => server.id === id)?.name || '已移除资源'}</span>)}</div> : '未关联服务器'}</dd></div>
        <div><dt>关联技能</dt><dd>{(project.skill_ids || []).length ? <div className="tag-row">{(project.skill_ids || []).map(id => <span className="resource-tag" key={id}>{catalog.skills.find(skill => skill.id === id)?.name || '已移除资源'}</span>)}</div> : '未关联技能'}</dd></div>
        <div><dt>关联知识库</dt><dd>{project.knowledge_ids.length ? <div className="tag-row">{project.knowledge_ids.map(id => <span className="resource-tag" key={id}>{catalog.knowledge.find(knowledge => knowledge.id === id)?.name || '已移除资源'}</span>)}</div> : '未关联知识库'}</dd></div>
      </dl>
    </div>
    <div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭</Button></div>
  </Modal>;
}
function ProjectForm({ value, onClose }: { value: Project | 'new'; onClose: () => void }) {
  const item = value === 'new' ? null : value; const catalog = useCatalog(); const notify = useToast();
  return <FormDialog title={item ? '编辑项目' : '创建项目空间'} description="项目不复制资源，只组织上下文与关联关系。" onClose={onClose} wide onSubmit={async form => { if (item?.read_only) throw new Error('系统默认资源为只读，无法修改。'); const payload = { name: formString(form, 'name'), description: formString(form, 'description'), color: formString(form, 'color'), server_ids: formList(form, 'server_ids'), skill_ids: formList(form, 'skill_ids'), knowledge_ids: formList(form, 'knowledge_ids'), status: formString(form, 'status') }; await (item ? api.patch(`/projects/${item.id}`, payload) : api.post('/projects', payload)); dataChanged(); notify('项目已保存'); }}><Field label="项目名称" required><input name="name" required defaultValue={item?.name} maxLength={120} placeholder="例如：核心业务 · 生产环境" /></Field><ColorPicker defaultValue={item?.color} /><Field label="项目描述"><textarea name="description" defaultValue={item?.description} rows={3} placeholder="业务背景、系统职责和运维约定" /></Field><Field label="项目状态"><Select label="项目状态" name="status" defaultValue={item?.status || 'active'} options={[{ value: 'active', label: '进行中' }, { value: 'archived', label: '已归档' }]} /></Field><MultiSelect label="关联服务器" name="server_ids" options={catalog.servers} selected={item?.server_ids} /><MultiSelect label="关联技能" name="skill_ids" options={catalog.skills} selected={item?.skill_ids || []} /><MultiSelect label="关联知识库" name="knowledge_ids" options={catalog.knowledge} selected={item?.knowledge_ids} /></FormDialog>;
}
