import { useState } from 'react';
import { ArrowRight, CheckCircle2, CircleAlert, Eye, FlaskConical, Globe2, KeyRound, Pencil, Server as ServerIcon, ShieldCheck, Sparkles, Terminal, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { dataChanged, useResource } from '../lib/hooks';
import { dateTime, listFromText, pretty } from '../lib/format';
import { useToast } from '../context/ToastContext';
import { useExecutions } from '../context/ExecutionContext';
import type { Provider, RunLaunch, Server, TestResult } from '../types';
import { UserResourceImportButton } from '../components/UserResourceImport';
import { useAuth } from '../context/AuthContext';
import { canUseControl } from '../lib/controlAccess';
import { Select } from '../components/Select';
import { AsyncButton, Banner, Button, EmptyState, ErrorState, Field, FormDialog, Loading, Modal, NewButton, PageHeader, SearchInput, StatusBadge, Switch, formString, useConfirm } from '../components/ui';
import './ResourcePermissions.css';

export function ServersPage() {
  const { user } = useAuth();
  const canDiagnose = canUseControl(user, 'observe');
  const resource = useResource<Server[]>('/servers', []); const [search, setSearch] = useState(''); const [kindFilter, setKindFilter] = useState('all'); const [edit, setEdit] = useState<Server | 'new' | null>(null); const [view, setView] = useState<Server | null>(null); const [test, setTest] = useState<{ name: string; result: TestResult } | null>(null); const { confirm, dialog } = useConfirm(); const notify = useToast(); const navigate = useNavigate(); const { watch } = useExecutions();
  const filtered = resource.data.filter(server => `${server.name} ${server.host} ${server.tags.join(' ')}`.toLowerCase().includes(search.toLowerCase()) && (kindFilter === 'all' || server.kind === kindFilter));
  const testServer = async (server: Server) => { const result = await api.post<TestResult>(`/servers/${server.id}/test`); setTest({ name: server.name, result }); dataChanged(); };
  const diagnose = async (server: Server) => { const result = await api.post<RunLaunch>(`/servers/${server.id}/diagnose`); await watch(result.run_id).catch(() => undefined); dataChanged(); navigate(`/chat/${result.conversation_id}?run=${result.run_id}`); };
  return <div className="page"><PageHeader eyebrow="INFRASTRUCTURE" title="连接你的工作现场" description="SSH 服务器与 Kubernetes 集群，统一管理，安全连接。" action={<><UserResourceImportButton kind="servers" label="服务器" /><NewButton onClick={() => setEdit('new')}>添加服务器</NewButton></>} /><div className="resource-summary-strip"><div><span className="summary-symbol"><ServerIcon size={20} /></span><strong>{resource.data.length}</strong><span>个基础设施资源</span></div><div><span className="live-dot" /><strong>{resource.data.filter(server => server.status === 'online').length}</strong><span>最近测试正常</span></div></div><div className="list-toolbar"><div className="segment-control">{[{ id: 'all', label: '全部资源' }, { id: 'ssh', label: 'SSH 服务器' }, { id: 'kubernetes', label: 'Kubernetes' }].map(item => <button key={item.id} className={kindFilter === item.id ? 'selected' : ''} onClick={() => setKindFilter(item.id)}>{item.label}</button>)}</div><SearchInput value={search} onChange={setSearch} placeholder="搜索名称、地址或标签…" /></div>{resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading /> : !resource.data.length ? <div className="panel"><EmptyState compact icon={ServerIcon} title="连接第一台服务器" description="你的基础设施不必是一座信息孤岛。通过 SSH 或 kubeconfig，开启真实、可控的 AI 运维。" /><div className="empty-feature-row"><span><ShieldCheck size={16} />凭据加密保存</span><span><KeyRound size={16} />严格主机指纹校验</span><span><Terminal size={16} />真实远程执行</span></div></div> : <div className="server-grid">{filtered.map(server => <article className="server-card" key={server.id}><div className="server-card-top"><span className={`server-type-icon ${server.kind}`}><ServerIcon size={23} /></span><StatusBadge status={server.status} /></div><h3>{server.name}</h3><div className="server-address"><Terminal size={12} />{server.kind === 'ssh' ? `${server.username || '—'}@${server.host}:${server.port}` : 'Kubernetes · 私有集群连接'}</div><p>{server.description || '还没有添加资源描述'}</p><div className="tag-row">{server.read_only && <span className="ea-resource-read-only">系统默认 · 只读</span>}<span className="resource-tag">{server.kind === 'ssh' ? 'SSH' : 'Kubernetes'}</span>{server.tags.map(tag => <span className="resource-tag" key={tag}>{tag}</span>)}{server.has_credentials && <span className="credential-tag"><KeyRound size={11} />已存凭据</span>}</div><div className="server-checked">最近测试 <span>{dateTime(server.last_checked_at, true)}</span></div><div className="resource-card-footer"><AsyncButton variant="secondary" className="button-small" action={() => testServer(server)}><FlaskConical size={14} />测试连接</AsyncButton><AsyncButton variant="ghost" className="button-small" disabled={!canDiagnose} title={!canDiagnose ? '管理员未授权观察模式，无法发起诊断' : undefined} action={() => diagnose(server)}><Sparkles size={14} />诊断</AsyncButton><div className="card-footer-spacer" />{server.read_only ? <Button variant="ghost" className="button-small" onClick={() => setView(server)}><Eye size={15} />查看配置</Button> : <><button className="icon-button" aria-label={`编辑${server.name}`} onClick={() => setEdit(server)}><Pencil size={15} /></button><button className="icon-button danger-text" aria-label={`删除${server.name}`} onClick={() => confirm('移除服务器？', `这会移除“${server.name}”的连接配置，不会删除远程服务器。`, async () => { if (server.read_only) return; await api.delete(`/servers/${server.id}`); dataChanged(); notify('服务器已移除'); })}><Trash2 size={15} /></button></>}</div></article>)}</div>}{resource.data.length > 0 && !filtered.length && <EmptyState compact title="没有找到匹配资源" description="试试其他名称、地址或筛选条件。" />}{edit && (edit === 'new' || !edit.read_only) && <ServerForm value={edit} onClose={() => setEdit(null)} />}{view && <ServerDetails server={view} onClose={() => setView(null)} />}{test && <TestModal title={test.name} result={test.result} onClose={() => setTest(null)} />}{dialog}<div className="bottom-note"><ShieldCheck size={15} />连接状态仅表示最近一次真实测试结果。首次可自动固定 SSH 指纹，后续变化会拒绝连接。</div></div>;
}
function ServerDetails({ server, onClose }: { server: Server; onClose: () => void }) {
  return <Modal title={`查看配置 · ${server.name}`} description="仅展示非敏感连接配置；密码、私钥和 kubeconfig 不会回显。" onClose={onClose} wide>
    <div className="ea-resource-details">
      <span className="ea-resource-read-only">系统默认 · 只读</span>
      <dl>
        <div><dt>资源名称</dt><dd>{server.name}</dd></div>
        <div><dt>资源类型</dt><dd>{server.kind === 'ssh' ? 'SSH 服务器' : 'Kubernetes'}</dd></div>
        <div><dt>资源描述</dt><dd>{server.description || '未添加描述'}</dd></div>
        <div><dt>标签</dt><dd>{server.tags.length ? server.tags.join('、') : '未添加标签'}</dd></div>
        {server.kind === 'ssh' && <>
          <div><dt>主机地址</dt><dd>{server.host}</dd></div>
          <div><dt>端口</dt><dd>{server.port}</dd></div>
          <div><dt>SSH 用户名</dt><dd>{server.username}</dd></div>
          <div><dt>认证方式</dt><dd>{server.auth_type === 'key' ? 'SSH 私钥' : '密码'}</dd></div>
          <div><dt>首次连接自动信任并保存指纹</dt><dd>{server.trust_on_first_use ? '是' : '否'}</dd></div>
          <div><dt>可信主机指纹</dt><dd>{server.fingerprint || '未记录'}</dd></div>
        </>}
        <div><dt>凭据状态</dt><dd>{server.has_credentials ? '已安全保存，不提供明文查看' : '未配置凭据'}</dd></div>
        <div><dt>连接状态</dt><dd><StatusBadge status={server.status} /></dd></div>
        <div><dt>最近测试</dt><dd>{dateTime(server.last_checked_at)}</dd></div>
      </dl>
    </div>
    <div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭</Button></div>
  </Modal>;
}
function ServerForm({ value, onClose }: { value: Server | 'new'; onClose: () => void }) {
  const item = value === 'new' ? null : value; const [kind, setKind] = useState<'ssh' | 'kubernetes'>(item?.kind || 'ssh'); const [auth, setAuth] = useState<'key' | 'password'>(item?.auth_type || 'key'); const [autoTrust, setAutoTrust] = useState(item?.trust_on_first_use ?? true); const notify = useToast();
  return <FormDialog title={item ? '编辑服务器' : '添加基础设施'} description="连接信息只用于后端安全执行，密钥不会在页面中回显。" onClose={onClose} wide submitLabel={item ? '保存配置' : '添加服务器'} onSubmit={async form => {
    if (item?.read_only) throw new Error('系统默认资源为只读，无法修改。');
    const payload: Record<string, unknown> = { name: formString(form, 'name'), kind, description: formString(form, 'description'), tags: listFromText(formString(form, 'tags')) };
    if (kind === 'ssh') Object.assign(payload, { host: formString(form, 'host'), port: Number(formString(form, 'port') || 22), username: formString(form, 'username'), auth_type: auth, trust_on_first_use: autoTrust, fingerprint: formString(form, 'fingerprint'), ...(auth === 'password' ? { password: formString(form, 'password') } : { private_key: formString(form, 'private_key') }) });
    else payload.kubeconfig = formString(form, 'kubeconfig');
    await (item ? api.patch(`/servers/${item.id}`, payload) : api.post('/servers', payload)); dataChanged(); notify(item ? '连接配置已保存' : '服务器已添加，请测试连接');
  }}><div className="connection-tabs"><button type="button" className={kind === 'ssh' ? 'selected' : ''} onClick={() => setKind('ssh')}><Terminal size={20} /><strong>SSH 服务器</strong><span>Linux 主机与远程终端</span></button><button type="button" className={kind === 'kubernetes' ? 'selected' : ''} onClick={() => setKind('kubernetes')}><Globe2 size={20} /><strong>Kubernetes</strong><span>使用独立 kubeconfig</span></button></div><Field label="资源名称" required><input name="name" defaultValue={item?.name} placeholder="例如：生产环境 · 应用节点 01" required maxLength={120} /></Field>{kind === 'ssh' ? <><div className="form-grid form-grid-host"><Field label="主机地址" required><input name="host" defaultValue={item?.host} placeholder="IP 地址或域名" required /></Field><Field label="端口" required><input name="port" type="number" defaultValue={item?.port || 22} min={1} max={65535} required /></Field></div><div className="form-grid"><Field label="SSH 用户名" required><input name="username" defaultValue={item?.username} placeholder="ubuntu / root" required /></Field><Field label="认证方式"><Select label="认证方式" value={auth} onChange={value => setAuth(value as typeof auth)} options={[{ value: 'key', label: 'SSH 私钥' }, { value: 'password', label: '密码' }]} /></Field></div>{auth === 'key' ? <Field label="私钥内容" required={!item} hint={item ? '留空保留已保存的密钥。不回显任何历史凭据。' : '粘贴完整 PEM / OpenSSH 私钥。请使用专用、最小权限的运维密钥。'}><textarea className="mono" name="private_key" rows={5} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" required={!item || !item.has_credentials} autoComplete="off" spellCheck={false} /></Field> : <Field label="SSH 密码" required={!item} hint={item ? '留空保留原密码。' : undefined}><input name="password" type="password" autoComplete="new-password" required={!item || !item.has_credentials} placeholder={item ? '已保存凭据，留空不更改' : '输入远程账户密码'} /></Field>}<Switch label="首次连接自动信任并保存指纹" checked={autoTrust} onChange={setAutoTrust} /><Field label="可信主机指纹" hint={autoTrust ? '可以留空。首次连接自动记录，之后指纹变化会拒绝连接；也可预先填写已核实的指纹。' : '请填写通过可信渠道核实的 SHA256 主机指纹。'}><input name="fingerprint" className="mono" defaultValue={item?.fingerprint} placeholder="SHA256:…（自动信任时可留空）" pattern="SHA256:.+" required={!autoTrust} /></Field><Banner tone="warning">首次自动信任无法独立证明主机身份，请确保 IP 和网络可信。已记录的指纹不匹配时不会自动覆盖。</Banner></> : <><Field label="kubeconfig 内容" required={!item} hint="仅支持包含 token 或嵌入式客户端证书/密钥与 CA 的独立配置。不支持本地文件路径或 exec 凭据插件。"><textarea className="mono" name="kubeconfig" rows={11} placeholder={item ? '留空保留已保存的 kubeconfig' : 'apiVersion: v1\nkind: Config\nclusters: …'} required={!item || !item.has_credentials} autoComplete="off" spellCheck={false} /></Field><Banner>请使用权限最小化的 Kubernetes 服务账户。此处不会在客户端解析或执行配置中的命令。</Banner></>}<Field label="资源描述"><textarea name="description" defaultValue={item?.description} rows={2} placeholder="用途、环境与注意事项" /></Field><Field label="标签" hint="多个标签用逗号分隔"><input name="tags" defaultValue={item?.tags.join(', ')} placeholder="生产环境, 应用服务, 华东" /></Field></FormDialog>;
}
export function ProvidersPage() {
  const resource = useResource<Provider[]>('/providers', []); const [edit, setEdit] = useState<Provider | 'new' | null>(null); const [view, setView] = useState<Provider | null>(null); const [test, setTest] = useState<{ name: string; result: TestResult } | null>(null); const [search, setSearch] = useState(''); const { confirm, dialog } = useConfirm(); const notify = useToast();
  const syncModels = async (provider: Provider) => {
    if (provider.read_only) return;
    const response = await api.post<Provider>(`/providers/${provider.id}/sync-models`);
    dataChanged();
    const sync = response.model_sync;
    if (sync?.status === 'ok') notify(`已同步 ${sync.count ?? response.models.length} 个模型`);
    else if (sync?.status === 'error') notify('模型同步失败，已保留原有模型配置；可点击“同步模型”重试，或编辑后手动填写模型。', 'error');
    else if (sync?.status === 'empty') notify('供应商未返回可用模型，已保留原有模型配置；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    else if (sync?.status === 'stale') notify('供应商配置已变更，本次同步结果未应用；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    else notify('未收到模型同步结果，请刷新后重试或手动填写模型。', 'info');
  };
  return <div className="page"><PageHeader eyebrow="INTELLIGENCE ENGINE" title="为工作空间注入智能" description="连接 OpenAI 兼容模型服务，自由选择你的 AI 引擎。" action={<><UserResourceImportButton kind="providers" label="模型供应商" /><NewButton onClick={() => setEdit('new')}>添加供应商</NewButton></>} /><div className="page-context-note">仅连接可信的模型服务；API Key 加密保存，仅由后端使用。</div><div className="list-toolbar"><span className="muted small">{resource.data.length} 个模型供应商 · {resource.data.filter(provider => provider.enabled).length} 个已启用</span><SearchInput value={search} onChange={setSearch} placeholder="搜索供应商…" /></div>{resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading /> : !resource.data.length ? <div className="panel"><EmptyState compact icon={Sparkles} title="为 EarthAI 连接第一个模型" description="没有模型配置时，智能体不会伪造执行结果。添加真实模型供应商，让你的运维助手开始工作。" /></div> : <div className="provider-grid">{resource.data.filter(provider => `${provider.name} ${provider.base_url}`.toLowerCase().includes(search.toLowerCase())).map(provider => <article className="provider-card" key={provider.id}><div className="provider-card-heading"><span className="provider-logo"><Sparkles size={23} /></span><div><h3>{provider.name}</h3><span>OpenAI Compatible</span></div>{provider.read_only ? <span className="ea-resource-state">{provider.enabled ? '已启用' : '已停用'}</span> : <Switch checked={provider.enabled} label={provider.enabled ? '已启用' : '已停用'} onChange={enabled => { if (provider.read_only) return; void api.patch(`/providers/${provider.id}`, { enabled }).then(() => dataChanged()).catch(error => notify(error instanceof Error ? error.message : '更新失败', 'error')); }} />}</div>{provider.read_only && <span className="ea-resource-read-only">系统默认 · 只读</span>}<div className="provider-url"><Globe2 size={14} /><span>{provider.base_url}</span></div><div className="provider-models"><span className="minor-heading">默认模型</span><strong>{provider.default_model || '未设置默认模型'}</strong><div className="tag-row">{provider.models.slice(0, 5).map(model => <span key={model} className="resource-tag">{model}</span>)}{provider.models.length > 5 && <span className="resource-tag">+{provider.models.length - 5}</span>}</div></div>{provider.model_sync && provider.model_sync.status !== 'ok' && <Banner tone="warning">{provider.model_sync.status === 'error' ? '模型同步失败。' : provider.model_sync.status === 'empty' ? '模型同步未返回可用模型。' : '供应商配置已变更，模型目录需要重新同步。'}{provider.read_only ? '请联系管理员重试同步或手动补充模型。' : '可点击“同步模型”重试，或编辑后手动填写模型。'}</Banner>}<div className="provider-secret"><KeyRound size={13} />{provider.has_api_key ? 'API Key 已安全保存' : '尚未配置 API Key'}</div><div className="resource-card-footer"><AsyncButton variant="secondary" className="button-small" action={async () => { const result = await api.post<TestResult>(`/providers/${provider.id}/test`); setTest({ name: provider.name, result }); dataChanged(); }}><FlaskConical size={14} />测试连接</AsyncButton>{!provider.read_only && <AsyncButton variant="ghost" className="button-small" action={() => syncModels(provider)}>同步模型</AsyncButton>}<div className="card-footer-spacer" />{provider.read_only ? <Button variant="ghost" className="button-small" onClick={() => setView(provider)}><Eye size={15} />查看配置</Button> : <><button className="icon-button" aria-label="编辑供应商" onClick={() => setEdit(provider)}><Pencil size={15} /></button><button className="icon-button danger-text" aria-label="删除供应商" onClick={() => confirm('移除模型供应商？', `“${provider.name}”的密钥与连接设置将被删除。依赖它的任务可能无法执行。`, async () => { if (provider.read_only) return; await api.delete(`/providers/${provider.id}`); dataChanged(); })}><Trash2 size={15} /></button></>}</div></article>)}</div>}{edit && (edit === 'new' || !edit.read_only) && <ProviderForm value={edit} onClose={() => setEdit(null)} />}{view && <ProviderDetails provider={view} onClose={() => setView(null)} />}{test && <TestModal title={test.name} result={test.result} onClose={() => setTest(null)} />}{dialog}<div className="bottom-note"><KeyRound size={15} />密钥只在后端使用，读取接口不会返回明文。编辑时留空即保留当前密钥。</div></div>;
}
function ProviderDetails({ provider, onClose }: { provider: Provider; onClose: () => void }) {
  return <Modal title={`查看配置 · ${provider.name}`} description="仅展示模型与非密钥连接配置，API Key 不会回显。" onClose={onClose} wide>
    <div className="ea-resource-details">
      <span className="ea-resource-read-only">系统默认 · 只读</span>
      <dl>
        <div><dt>供应商名称</dt><dd>{provider.name}</dd></div>
        <div><dt>接口协议</dt><dd>OpenAI Compatible</dd></div>
        <div><dt>API Base URL</dt><dd>{provider.base_url}</dd></div>
        <div><dt>默认模型</dt><dd>{provider.default_model || '未设置默认模型'}</dd></div>
        <div><dt>可选模型列表</dt><dd>{provider.models.length ? <div className="tag-row">{provider.models.map(model => <span className="resource-tag" key={model}>{model}</span>)}</div> : '未配置模型列表'}</dd></div>
        <div><dt>启用状态</dt><dd>{provider.enabled ? '已启用' : '已停用'}</dd></div>
        <div><dt>API Key 状态</dt><dd>{provider.has_api_key ? '已安全保存，不提供明文查看' : '未配置 API Key'}</dd></div>
      </dl>
    </div>
    <div className="modal-footer"><Button variant="secondary" onClick={onClose}>关闭</Button></div>
  </Modal>;
}
function ProviderForm({ value, onClose }: { value: Provider | 'new'; onClose: () => void }) {
  const item = value === 'new' ? null : value; const notify = useToast();
  return <FormDialog title={item ? '编辑模型供应商' : '连接模型供应商'} description={item ? '填写真实的 OpenAI 兼容 API 配置。编辑保存不会自动同步模型，可在卡片上手动同步。' : '保存后会自动同步一次 /models；默认模型留空时，将使用返回的首个可用模型。'} onClose={onClose} onSubmit={async form => {
    if (item?.read_only) throw new Error('系统默认资源为只读，无法修改。');
    const models = listFromText(formString(form, 'models')); const defaultModel = formString(form, 'default_model');
    if (defaultModel && !models.includes(defaultModel)) models.unshift(defaultModel);
    const payload = { name: formString(form, 'name'), base_url: formString(form, 'base_url').replace(/\/+$/, ''), api_key: formString(form, 'api_key'), default_model: defaultModel, models, enabled: form.has('enabled') };
    const response = await (item ? api.patch<Provider>(`/providers/${item.id}`, payload) : api.post<Provider>('/providers', payload));
    dataChanged();
    if (item) notify('供应商配置已保存');
    else if (response.model_sync?.status === 'ok') notify(`供应商配置已保存，已自动同步 ${response.model_sync.count ?? response.models.length} 个模型`);
    else if (response.model_sync?.status === 'error') notify('配置已保存，但自动同步失败；可点击“同步模型”重试，或编辑后手动填写模型。', 'error');
    else if (response.model_sync?.status === 'empty') notify('配置已保存，但自动同步未返回可用模型；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    else if (response.model_sync?.status === 'stale') notify('配置已保存，但配置已变更，自动同步结果未应用；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
    else notify('配置已保存，但未收到自动同步结果；可点击“同步模型”重试，或编辑后手动填写模型。', 'info');
  }}><Field label="供应商名称" required><input name="name" defaultValue={item?.name} required placeholder="例如：团队模型服务" maxLength={100} /></Field><Field label="API Base URL" required hint="填写包含 /v1 等版本路径的基础地址，不要包含 /chat/completions，后端会自动拼接。"><input name="base_url" type="url" defaultValue={item?.base_url} required placeholder="https://api.openai.com/v1" /></Field><Field label="API Key" hint={item ? '留空保留已保存密钥，不会回显历史密钥。' : '必填；本地免鉴权模型服务可填写占位值 local。'}><input name="api_key" type="password" autoComplete="new-password" required={!item?.has_api_key} placeholder={item?.has_api_key ? '•••••••• 已安全保存' : 'sk-…'} /></Field><Field label="默认模型" hint={item ? '可留空；编辑保存不会自动同步，可在卡片上点击“同步模型”。' : '可留空；保存后自动同步一次模型列表，默认使用返回的首个可用模型。'}><input name="default_model" defaultValue={item?.default_model} placeholder="可留空，或输入模型标识" /></Field><Field label="可选模型列表" hint="可留空。每行一个或用英文逗号分隔；新建保存后自动同步，也可在卡片上手动同步。"><textarea name="models" rows={4} className="mono" defaultValue={item?.models.join('\n')} placeholder="model-name-1\nmodel-name-2" /></Field><Switch name="enabled" label="启用该模型供应商" defaultChecked={item?.enabled ?? true} /><Banner>连接测试会真实访问此 URL。仅添加你信任的服务地址，避免将密钥发送到错误端点。</Banner></FormDialog>;
}
function TestModal({ title, result, onClose }: { title: string; result: TestResult; onClose: () => void }) { return <Modal title={`连接测试 · ${title}`} onClose={onClose}><div className={`test-result ${result.ok ? 'test-ok' : 'test-failed'}`}><div className="test-result-icon">{result.ok ? <CheckCircle2 size={32} /> : <CircleAlert size={32} />}</div><h3>{result.ok ? '真实连接测试通过' : '连接未能建立'}</h3><p>{result.message}</p>{result.models && <div className="tag-row">{result.models.slice(0, 20).map(model => <span className="resource-tag" key={model}>{model}</span>)}</div>}{result.details !== undefined && result.details !== null && <pre>{pretty(result.details)}</pre>}</div><div className="modal-footer"><Button onClick={onClose}>我知道了<ArrowRight size={15} /></Button></div></Modal>; }
