import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, BookOpen, Columns2, Eye, FileText, Pencil, Plus, RefreshCw, Search, ShieldCheck, Trash2, Users } from 'lucide-react';
import { Content } from '../components/Content';
import { Select } from '../components/Select';
import { Banner, Button, EmptyState, ErrorState, Field, FormDialog, Loading, Modal, PageHeader, SearchInput, formString, useConfirm } from '../components/ui';
import { useToast } from '../context/ToastContext';
import { api } from '../lib/api';
import { dateTime } from '../lib/format';
import { dataChanged, useResource } from '../lib/hooks';
import { guideIcon, guideIcons } from './HelpPage';
import type { Guide, GuideAudience } from './HelpPage';
import './AdminGuidesPage.css';

const audiences: { value: GuideAudience; label: string; people: string; icon: typeof ShieldCheck }[] = [
  { value: 'admin', label: '管理员指南', people: '管理员', icon: ShieldCheck },
  { value: 'user', label: '普通用户指南', people: '普通用户', icon: Users },
];
const iconOptions = Object.entries(guideIcons).map(([name, Icon]) => ({ value: name, label: name, icon: <Icon size={17} /> }));

export function AdminGuidesPage() {
  const [audience, setAudience] = useState<GuideAudience>('admin');
  const [editing, setEditing] = useState<Guide | 'new' | null>(null);
  const [preview, setPreview] = useState<Guide | null>(null);
  const current = audiences.find(item => item.value === audience)!;
  return <div className="page ea-guides-page">
    <PageHeader eyebrow="ROLE-BASED HANDBOOKS" title="把使用方法，写得更清楚" description="分别维护管理员与普通用户的使用指南。每一节都有固定地址，保存后对同角色全部账户生效。" action={<><Link className="button button-secondary" to="/help"><ArrowLeft size={16} />返回使用指南</Link><Button onClick={() => setEditing('new')}><Plus size={16} />新建章节</Button></>} />
    <section className="ea-guides-scope"><span><BookOpen size={25} /></span><div><strong>两套目录，各自清晰；每节内容，全员共享。</strong><p>正在维护{current.label}。新建、编辑与删除只影响这套目录，不会改动另一套指南或账户权限。</p></div><span className="ea-guides-scope-label">{current.label}</span></section>
    <div className="ea-guides-tabs" role="tablist" aria-label="指南受众">{audiences.map(item => <button type="button" key={item.value} id={`ea-guide-tab-${item.value}`} role="tab" aria-selected={audience === item.value} aria-controls={`ea-guide-panel-${item.value}`} tabIndex={audience === item.value ? 0 : -1} onClick={() => { setAudience(item.value); setEditing(null); setPreview(null); }} onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'admin' : event.key === 'End' ? 'user' : audience === 'admin' ? 'user' : 'admin';
      setAudience(next); setEditing(null); setPreview(null);
      document.getElementById(`ea-guide-tab-${next}`)?.focus();
    }}><item.icon size={17} />{item.label}</button>)}</div>
    <AudienceGuides key={audience} audience={audience} onEdit={setEditing} onPreview={setPreview} />
    {editing && <GuideForm key={`${audience}-${editing === 'new' ? 'new' : editing.id}`} audience={audience} guide={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    {preview && <Modal title={`阅读预览 · ${preview.title}`} description={`${current.label} · /help/${preview.id} · 排序 ${preview.sort_order}`} onClose={() => setPreview(null)} wide>
      <div className="ea-guide-reading"><Banner>本节面向全部{current.people}。当前为阅读预览，不会修改已发布内容；HTML 不会执行，远程图片不会自动加载。</Banner><article aria-label={preview.title}><h3>{preview.title}</h3>{preview.summary && <p className="ea-guide-reading-summary">{preview.summary}</p>}<div className="ea-guide-reading-body">{preview.content.trim() ? <Content text={preview.content} /> : <p className="muted">本章节尚未填写正文。</p>}</div></article></div>
      <div className="modal-footer"><Button variant="secondary" onClick={() => setPreview(null)}>关闭预览</Button><Button onClick={() => { setEditing(preview); setPreview(null); }}><Pencil size={16} />编辑本节</Button></div>
    </Modal>}
  </div>;
}

function AudienceGuides({ audience, onEdit, onPreview }: { audience: GuideAudience; onEdit: (guide: Guide) => void; onPreview: (guide: Guide) => void }) {
  const resource = useResource<Guide[]>(`/admin/guides?audience=${audience}`, []);
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const { confirm, dialog } = useConfirm(); const notify = useToast();
  const current = audiences.find(item => item.value === audience)!;
  const filtered = useMemo(() => {
    const terms = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return resource.data.filter(guide => {
      const text = `${guide.id} ${guide.title} ${guide.summary} ${guide.content}`.toLowerCase();
      return terms.every(term => text.includes(term));
    });
  }, [resource.data, search]);
  const validIds = new Set(resource.data.map(guide => guide.id));
  const selected = selectedIds.filter(id => validIds.has(id));
  const visibleIds = filtered.map(guide => guide.id);
  const allSelected = visibleIds.length > 0 && visibleIds.every(id => selected.includes(id));
  const someSelected = visibleIds.some(id => selected.includes(id));
  const unavailable = resource.loading || Boolean(resource.error);
  const remove = (ids: string[], batch = false) => {
    confirm(`删除${current.label}的 ${ids.length} 节指南？`, `本次将永久删除“${current.label}”中的 ${ids.length} 节指南，对全部${current.people}生效，章节链接将失效。不会影响另一套指南；删除后不会因重启自动恢复。请确认受众与数量。`, async () => {
      if (batch) await api.post(`/admin/guides/${audience}/batch-delete`, { ids });
      else await api.delete(`/admin/guides/${audience}/${ids[0]}`);
      setSelectedIds([]); dataChanged(); notify(`已删除${current.label}中的 ${ids.length} 节指南`);
    });
  };
  return <section id={`ea-guide-panel-${audience}`} role="tabpanel" aria-labelledby={`ea-guide-tab-${audience}`} className="ea-guides-panel">
    <div className="ea-guides-toolbar"><div><strong>{current.label}</strong><span role="status" aria-live="polite">共 {resource.data.length} 节 · 当前显示 {filtered.length} 节</span></div><SearchInput value={search} onChange={setSearch} placeholder="搜索章节标题、摘要或正文…" /><Button variant="secondary" busy={resource.loading} onClick={() => { void resource.reload(); }}><RefreshCw size={15} />刷新目录</Button></div>
    <div className="ea-guides-selection" aria-label="指南批量操作">
      <label><input className="ea-guide-checkbox" type="checkbox" aria-label="全选当前筛选结果" checked={allSelected} ref={element => { if (element) element.indeterminate = someSelected && !allSelected; }} disabled={unavailable || !visibleIds.length} onChange={() => setSelectedIds(allSelected ? selected.filter(id => !visibleIds.includes(id)) : [...new Set([...selected, ...visibleIds])])} /><span>全选当前结果</span></label>
      <span aria-live="polite">已选 <strong>{selected.length}</strong> / 共 {resource.data.length} 项</span>
      {selected.length > 0 && <button type="button" className="ea-guides-clear" onClick={() => setSelectedIds([])}>清空选择</button>}
      <Button variant="danger" disabled={unavailable || !selected.length} onClick={() => remove([...selected], true)}><Trash2 size={15} />批量删除</Button>
    </div>
    {resource.loading ? <Loading text={`读取${current.label}…`} /> : resource.error ? <ErrorState message={resource.error} retry={resource.reload} /> : !filtered.length ? <div className="panel"><EmptyState icon={search.trim() ? Search : BookOpen} title={resource.data.length ? '没有匹配的指南章节' : `${current.label}暂无章节`} description={resource.data.length ? '请调整关键词。选择可跨搜索保留，批量删除前请核对所选总数。' : '这套目录目前为空。点击页头“新建章节”即可发布第一节，另一套指南不受影响。'} action={search.trim() ? <Button variant="secondary" onClick={() => setSearch('')}>清除搜索</Button> : undefined} /></div> : <div className="ea-guides-grid" aria-label={`${current.label}章节列表`}>{filtered.map(guide => {
      const Icon = guideIcon(guide.icon); const checked = selected.includes(guide.id);
      return <article className={`ea-guide-card${checked ? ' is-selected' : ''}`} key={guide.id} aria-label={guide.title} data-guide-id={guide.id}>
        <div className="ea-guide-card-top"><input className="ea-guide-checkbox" type="checkbox" aria-label={`选择 ${guide.title}`} checked={checked} onChange={() => setSelectedIds(checked ? selected.filter(id => id !== guide.id) : [...selected, guide.id])} /><span className="ea-guide-card-icon"><Icon size={22} /></span><span className="ea-guide-card-audience">{current.label}</span></div>
        <h2>{guide.title}</h2><p className="ea-guide-card-summary">{guide.summary || '暂未填写摘要，可通过阅读预览查看完整正文。'}</p>
        <dl className="ea-guide-card-meta"><div><dt>排序</dt><dd>{guide.sort_order}</dd></div><div><dt>章节 URL</dt><dd><code>/help/{guide.id}</code></dd></div></dl>
        <p className="ea-guide-card-updated">最近更新 <time dateTime={guide.updated_at}>{dateTime(guide.updated_at)}</time></p>
        <div className="ea-guide-card-actions"><Button variant="secondary" className="button-small" aria-label={`预览 ${guide.title}`} onClick={() => onPreview(guide)}><Eye size={15} />阅读预览</Button><Button variant="ghost" className="button-small" aria-label={`编辑 ${guide.title}`} onClick={() => onEdit(guide)}><Pencil size={15} />编辑</Button><Button variant="ghost" className="button-small ea-guide-delete" aria-label={`删除 ${guide.title}`} onClick={() => remove([guide.id])}><Trash2 size={15} />删除</Button></div>
      </article>;
    })}</div>}
    {dialog}
  </section>;
}

function GuideForm({ audience, guide, onClose }: { audience: GuideAudience; guide: Guide | null; onClose: () => void }) {
  const notify = useToast(); const current = audiences.find(item => item.value === audience)!;
  const [id, setId] = useState(guide?.id || '');
  const [icon, setIcon] = useState(guide && Object.hasOwn(guideIcons, guide.icon) ? guide.icon : 'BookOpen');
  const [content, setContent] = useState(guide?.content || '');
  const [mode, setMode] = useState<'edit' | 'preview' | 'split'>('split');
  return <FormDialog title={`${guide ? '编辑' : '新建'}章节 · ${current.label}`} description="编辑单节内容，不移动受众，不改变已有章节地址。Markdown 预览与使用指南采用同一安全渲染方式。" onClose={onClose} wide submitLabel={guide ? '保存章节' : '发布章节'} onSubmit={async form => {
    const nextId = guide?.id || formString(form, 'id');
    const title = formString(form, 'title'); const summary = formString(form, 'summary');
    const order = formString(form, 'sort_order'); const sortOrder = Number(order);
    const body = String(form.get('content') || '');
    if (!/^[a-z][a-z0-9-]{0,79}$/.test(nextId)) throw new Error('章节地址需以小写字母开头，仅含小写字母、数字与连字符，最多 80 个字符。');
    if (!title || title.length > 120) throw new Error('标题需为 1～120 个字符。');
    if (summary.length > 1000) throw new Error('摘要不能超过 1000 个字符。');
    if (!Object.hasOwn(guideIcons, icon)) throw new Error('请从内置列表选择图标。');
    if (!order || !Number.isInteger(sortOrder) || sortOrder < 0 || sortOrder > 100000) throw new Error('排序需为 0～100000 之间的整数。');
    if (!body.trim() || body.length > 200000) throw new Error('Markdown 正文需为1～200000个字符。');
    const payload = { title, summary, icon, sort_order: sortOrder, content: body };
    if (guide) await api.patch<Guide>(`/admin/guides/${audience}/${guide.id}`, payload);
    else await api.post<Guide>(`/admin/guides/${audience}`, { id: nextId, ...payload });
    dataChanged(); notify(`${current.label}章节已${guide ? '保存' : '发布'}，对全部${current.people}生效`);
  }}>
    <div className="ea-guide-form">
      <Banner tone="warning">生效范围：本节保存在“{current.label}”，保存后对全部{current.people}立即生效，不是当前账户的私人草稿。受众与已有章节地址不可更改。</Banner>
      <div className="form-grid"><Field label="指南受众" hint="受众固定，不能将章节移入另一套目录。"><input value={current.label} readOnly aria-readonly="true" /></Field><Field label="章节地址" required hint={guide ? `地址已固定：/help/${guide.id}。编辑不会改变已有链接。` : `发布地址：/help/${id || '章节地址'}。以小写字母开头，仅允许小写字母、数字、连字符，最多 80 字符。`}><input name="id" value={id} onChange={event => setId(event.target.value)} readOnly={Boolean(guide)} required pattern="[a-z][a-z0-9-]{0,79}" maxLength={80} placeholder="例如：getting-started" autoComplete="off" autoCapitalize="none" spellCheck={false} /></Field></div>
      <Field label="章节标题" required hint="1～120 个字符，显示于目录与章节标题。"><input name="title" required maxLength={120} defaultValue={guide?.title || ''} placeholder="例如：开始使用你的工作空间" /></Field>
      <Field label="章节摘要" hint="最多 1000 个字符；用于目录搜索与正文导语。"><textarea name="summary" maxLength={1000} rows={3} defaultValue={guide?.summary || ''} placeholder="简要说明本节解决什么问题，以及适用范围。" /></Field>
      <div className="form-grid"><Field label="目录图标" hint="仅使用本地内置图标，不请求外部图标服务。"><Select name="icon" label="目录图标" value={icon} onChange={setIcon} options={iconOptions} searchable /></Field><Field label="章节排序" required hint="0～100000 的整数，数值越小越靠前。"><input name="sort_order" type="number" min={0} max={100000} step={1} required defaultValue={guide?.sort_order ?? 0} /></Field></div>
      <div className="ea-guide-editor-toolbar"><div><FileText size={17} /><strong>Markdown 正文</strong><span aria-live="polite">{content.length.toLocaleString()} / 200,000</span></div><div className="ea-guide-editor-modes" role="group" aria-label="正文显示方式"><Button type="button" variant="ghost" aria-pressed={mode === 'edit'} onClick={() => setMode('edit')}><Pencil size={14} />编辑</Button><Button type="button" variant="ghost" aria-pressed={mode === 'preview'} onClick={() => setMode('preview')}><Eye size={14} />预览</Button><Button type="button" variant="ghost" aria-pressed={mode === 'split'} onClick={() => setMode('split')}><Columns2 size={14} />分栏</Button></div></div>
      <div className="ea-guide-editor" data-mode={mode}>
        <div className="ea-guide-editor-source" hidden={mode === 'preview'}><Field label="Markdown 正文" required hint="支持标题、列表、代码块与表格，需填写1～200000个字符。"><textarea name="content" required value={content} onChange={event => setContent(event.target.value)} maxLength={200000} rows={18} spellCheck={false} placeholder={'## 本节目标\n\n说明功能、关键字段、推荐步骤与注意事项。'} /></Field></div>
        <div className="ea-guide-editor-preview" role="region" aria-label="Markdown 正文预览" hidden={mode === 'edit'}><span className="ea-guide-preview-caption">安全阅读预览</span>{content.trim() ? <Content text={content} /> : <p className="ea-guide-preview-empty">在编辑区写下 Markdown，预览会在这里同步呈现。</p>}</div>
      </div>
      <p className="ea-guide-editor-note">HTML 按文本显示，不会执行；Markdown 图片仅显示安全链接，不会自动加载远程图片。此预览不会保存内容，请点击下方“{guide ? '保存章节' : '发布章节'}”发布。</p>
    </div>
  </FormDialog>;
}
