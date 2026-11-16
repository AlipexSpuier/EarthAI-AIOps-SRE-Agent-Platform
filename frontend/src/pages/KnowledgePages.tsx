import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowRight, BookOpen, CheckCircle2, ChevronRight, Database, File, FileCode2, FileText, FolderOpen, HardDrive, Layers, Loader2, Pencil, Plus, Search, ShieldCheck, Trash2, UploadCloud, X } from 'lucide-react';
import { api, downloadFile, errorMessage } from '../lib/api';
import { dateTime, fileSize } from '../lib/format';
import { dataChanged, useResource } from '../lib/hooks';
import { useAuth } from '../context/AuthContext';
import { canUseSpace } from '../lib/spaceAccess';
import { useToast } from '../context/ToastContext';
import type { Knowledge, KnowledgeDocument, PersonalFile, SearchResult } from '../types';
import { AsyncButton, Banner, Button, EmptyState, ErrorState, Field, FormDialog, Loading, Modal, NewButton, PageHeader, SearchInput, formString, useConfirm } from '../components/ui';
import { UserResourceImportButton } from '../components/UserResourceImport';
import { Content } from '../components/Content';
import './ResourcePermissions.css';
import './LibraryWorkbench.css';

function FileGlyph({ name }: { name: string }) { const extension = name.split('.').at(-1)?.toLowerCase(); return <span className={`file-glyph file-${extension === 'pdf' ? 'pdf' : ['ts', 'js', 'py', 'json', 'yaml'].includes(extension || '') ? 'code' : 'text'}`}>{['ts', 'js', 'py', 'json', 'yaml'].includes(extension || '') ? <FileCode2 size={21} /> : <FileText size={21} />}</span>; }
function UploadArea({ upload, busy, description, compact = false, accept }: { upload: (files: File[]) => Promise<void>; busy: string; description: string; compact?: boolean; accept?: string }) {
  const input = useRef<HTMLInputElement>(null); const [dragging, setDragging] = useState(false);
  return <div className={`upload-area ${compact ? 'upload-compact' : ''} ${dragging ? 'dragging' : ''} ${busy ? 'upload-busy' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) void upload([...event.dataTransfer.files]); }}><input ref={input} type="file" multiple accept={accept} hidden disabled={Boolean(busy)} onChange={event => { if (event.target.files) void upload([...event.target.files]); event.target.value = ''; }} />{busy ? <Loader2 size={28} className="spin" /> : <UploadCloud size={29} strokeWidth={1.5} />}<div><strong>{busy || '拖放文件到这里，或点击上传'}</strong><p>{description}</p></div><Button variant="secondary" className="button-small" disabled={Boolean(busy)} onClick={() => input.current?.click()}><Plus size={15} />选择文件</Button></div>;
}
export function SpacePage() {
  const { user } = useAuth();
  const enabled = canUseSpace(user, 'personal');
  const resource = useResource<PersonalFile[]>(enabled ? '/files' : null, []); const [search, setSearch] = useState(''); const [busy, setBusy] = useState(''); const notify = useToast(); const { confirm, dialog } = useConfirm();
  const upload = async (files: File[]) => {
    if (busy || !files.length) return; let success = 0;
    for (let index = 0; index < files.length; index++) { const file = files[index]; setBusy(`上传 ${index + 1}/${files.length} · ${file.name}`); try { await api.upload('/files', file); success++; } catch (err) { notify(`${file.name}：${errorMessage(err)}`, 'error'); } }
    setBusy(''); if (success) { dataChanged(); notify(`已上传 ${success} 个文件`); }
  };
  const filtered = resource.data.filter(file => file.name.toLowerCase().includes(search.toLowerCase()));
  if (!enabled) return <div className="page"><Banner>个人空间暂未开启，请联系管理员。原文件未删除，重新开启后仍可访问。</Banner></div>;
  return <div className="page"><PageHeader eyebrow="YOUR PERSONAL SPACE" title="一处收纳，随时取用" description="安全保存你的运维文件、配置与工作资料，个人空间只属于你。" /><div className="space-top-grid"><UploadArea upload={upload} busy={busy} description="文件安全保存在 Web 根目录之外，下载时校验账户权限。" /><div className="space-storage"><span className="storage-icon"><HardDrive size={24} /></span><span>个人文件空间</span><strong>{fileSize(resource.data.reduce((total, file) => total + file.size, 0))}</strong><p>{resource.data.length} 个文件 · 私有存储</p><div><ShieldCheck size={12} />访问权限由账户隔离</div></div></div><div className="list-toolbar"><div className="list-title"><FolderOpen size={19} /><h2>我的文件</h2><span>{resource.data.length}</span></div><SearchInput value={search} onChange={setSearch} placeholder="搜索文件名…" /></div>{resource.error && <ErrorState message={resource.error} retry={resource.reload} />}{resource.loading ? <Loading /> : resource.data.length ? <div className="table-panel"><table><thead><tr><th>文件名称</th><th>文件大小</th><th>上传时间</th><th className="align-right">操作</th></tr></thead><tbody>{filtered.map(file => <tr key={file.id}><td><div className="table-file-name"><FileGlyph name={file.name} /><div><strong>{file.name}</strong><span>{file.mime || '未知文件类型'}</span></div></div></td><td className="muted">{fileSize(file.size)}</td><td className="muted">{dateTime(file.created_at)}</td><td><div className="table-actions"><AsyncButton variant="ghost" className="button-small" action={() => downloadFile(file.id, file.name)}><ArrowDownToLine size={15} />下载</AsyncButton><button className="icon-button danger-text" aria-label={`删除${file.name}`} onClick={() => confirm('删除文件？', `“${file.name}”将从个人空间永久删除。请确保已保存需要的副本。`, async () => { await api.delete(`/files/${file.id}`); dataChanged(); notify('文件已删除'); })}><Trash2 size={15} /></button></div></td></tr>)}</tbody></table>{!filtered.length && <EmptyState compact title="没有匹配的文件" description="请尝试其他文件名。" />}</div> : <div className="panel"><EmptyState compact icon={File} title="把工作资料放在手边" description="上传日志片段、配置备份或运维文档，随时安全下载。需要给智能体检索的资料，请上传到知识库。" /></div>}<Banner>个人空间文件用于独立存储，不会自动被模型读取。需要让智能体检索内容，请在知识库中上传文档并关联智能体。</Banner>{dialog}</div>;
}
export function KnowledgePage() {
  const resource = useResource<Knowledge[]>('/knowledge', []);
  const [selected, setSelected] = useState<string | null>(null);
  const [edit, setEdit] = useState<Knowledge | 'new' | null>(null);
  const [directorySearch, setDirectorySearch] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [busy, setBusy] = useState('');
  const [reading, setReading] = useState<{ id: string; name: string; text: string } | null>(null);
  const [documentIndex, setDocumentIndex] = useState<{ knowledgeId: string; data: KnowledgeDocument[]; loading: boolean; error: string }>({ knowledgeId: '', data: [], loading: false, error: '' });
  const [documentRevision, setDocumentRevision] = useState(0);
  const mainRef = useRef<HTMLElement>(null);
  const searchRequest = useRef(0);
  const { confirm, dialog } = useConfirm();
  const notify = useToast();
  const active = resource.data.find(item => item.id === selected) || resource.data[0];
  const personalOverride = (active as (Knowledge & { personal_override?: boolean }) | undefined)?.personal_override;
  const activeId = active?.id;
  const activeKnowledgeId = useRef<string | undefined>(activeId);
  const directoryTerm = directorySearch.trim().toLowerCase();
  const filtered = resource.data.filter(knowledge => `${knowledge.name} ${knowledge.description}`.toLowerCase().includes(directoryTerm));
  const activeOutsideDirectory = active && !filtered.some(knowledge => knowledge.id === active.id);
  const documents = documentIndex.knowledgeId === activeId ? documentIndex.data : [];
  const documentsLoading = documentIndex.knowledgeId !== activeId || documentIndex.loading;
  const documentsError = documentIndex.knowledgeId === activeId ? documentIndex.error : '';

  useLayoutEffect(() => {
    activeKnowledgeId.current = activeId;
    searchRequest.current++;
    setResults(null);
    setSearchError('');
    setSearching(false);
    setReading(null);
    if (mainRef.current) mainRef.current.scrollTop = 0;
    return () => { activeKnowledgeId.current = undefined; searchRequest.current++; };
  }, [activeId]);

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    let requestId = 0;
    const loadDocuments = async (quiet = false) => {
      const request = ++requestId;
      if (!quiet) setDocumentIndex(previous => ({ knowledgeId: activeId, data: previous.knowledgeId === activeId ? previous.data : [], loading: true, error: '' }));
      try {
        const data = await api.get<KnowledgeDocument[]>(`/knowledge/${activeId}/documents`);
        if (!cancelled && request === requestId) setDocumentIndex({ knowledgeId: activeId, data, loading: false, error: '' });
      } catch (err) {
        if (!cancelled && request === requestId) setDocumentIndex(previous => ({ knowledgeId: activeId, data: previous.knowledgeId === activeId ? previous.data : [], loading: false, error: errorMessage(err) }));
      }
    };
    void loadDocuments();
    const refresh = () => { void loadDocuments(true); };
    window.addEventListener('earthai:data-changed', refresh);
    return () => { cancelled = true; window.removeEventListener('earthai:data-changed', refresh); };
  }, [activeId, documentRevision]);

  const selectKnowledge = (id: string) => {
    searchRequest.current++;
    setSelected(id);
    setResults(null);
    setSearchError('');
    setSearching(false);
  };
  const upload = async (files: File[]) => {
    if (!active || active.read_only || busy || !files.length) return;
    const knowledgeId = active.id;
    let success = 0;
    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      setBusy(`索引 ${index + 1}/${files.length} · ${file.name}`);
      try { await api.upload(`/knowledge/${knowledgeId}/documents`, file); success++; }
      catch (err) { notify(`${file.name}：${errorMessage(err)}`, 'error'); }
    }
    setBusy('');
    if (success) {
      dataChanged();
      notify(`已上传并索引 ${success} 份文档`);
      if (activeKnowledgeId.current === knowledgeId) setResults(null);
    }
  };
  const search = async () => {
    if (!active || !query.trim()) return;
    const knowledgeId = active.id;
    const request = ++searchRequest.current;
    setSearching(true);
    setSearchError('');
    try {
      const response = await api.post<{ results: SearchResult[] }>('/knowledge/search', { query: query.trim(), knowledge_ids: [knowledgeId] });
      if (request === searchRequest.current && activeKnowledgeId.current === knowledgeId) setResults(response.results);
    } catch (err) {
      if (request === searchRequest.current && activeKnowledgeId.current === knowledgeId) setSearchError(errorMessage(err));
    } finally {
      if (request === searchRequest.current && activeKnowledgeId.current === knowledgeId) setSearching(false);
    }
  };

  return <div className="page knowledge-page">
    <PageHeader eyebrow="KNOWLEDGE THAT WORKS" title="让知识，参与每一次决策" description="文档入库、全文检索，让智能体读懂你的业务与运维经验。" action={<><UserResourceImportButton kind="knowledge" label="知识库" /><NewButton onClick={() => setEdit('new')}>创建知识库</NewButton></>} />
    <div className="knowledge-stats">
      <div><BookOpen size={18} /><strong>{resource.data.length}</strong><span>个知识库</span></div>
      <div><FileText size={18} /><strong>{resource.data.reduce((sum, knowledge) => sum + knowledge.document_count, 0)}</strong><span>份已索引文档</span></div>
      <div><Layers size={18} /><strong>{resource.data.reduce((sum, knowledge) => sum + knowledge.chunk_count, 0)}</strong><span>个检索片段</span></div>
    </div>
    <div className="knowledge-directory-toolbar">
      <span>本地全文索引 · 真实文档内容</span>
      <SearchInput value={directorySearch} onChange={setDirectorySearch} placeholder="查找知识库名称或描述…" />
    </div>
    {resource.error && <ErrorState message={resource.error} retry={resource.reload} />}
    {resource.loading ? <Loading /> : !resource.data.length ? <div className="panel">
      <EmptyState compact icon={BookOpen} title="为智能体建立业务记忆" description="从操作手册到排障记录，创建知识库并上传文档，让真实经验为每一次诊断提供依据。" />
      <div className="empty-feature-row"><span>TXT / Markdown</span><span>PDF</span><span>CSV / JSON / YAML</span><span>日志与代码文本</span></div>
    </div> : <div className="knowledge-workbench">
      <aside className="knowledge-sidebar" role="region" aria-label="知识库目录" tabIndex={0}>
        <div className="knowledge-sidebar-title">知识库目录 <span aria-live="polite">{filtered.length} / {resource.data.length}</span></div>
        {filtered.map(knowledge => <button key={knowledge.id} className={active?.id === knowledge.id ? 'selected' : ''} aria-pressed={active?.id === knowledge.id} onClick={() => selectKnowledge(knowledge.id)}>
          <BookOpen size={19} />
          <span><strong>{knowledge.name}</strong><small>{knowledge.document_count} 份文档 · {knowledge.chunk_count} 个片段</small></span>
          <ChevronRight size={13} />
        </button>)}
        {!filtered.length && <div className="knowledge-directory-empty" role="status">
          <strong>没有匹配的知识库</strong>
          <p>请尝试其他名称或描述，或清除查找条件。</p>
          <Button variant="secondary" className="button-small" onClick={() => setDirectorySearch('')}>清除目录查找</Button>
        </div>}
      </aside>
      {active && <section ref={mainRef} className="knowledge-main" role="region" aria-label="知识库详情" tabIndex={0} data-knowledge-id={active.id}>
        {activeOutsideDirectory && <div className="knowledge-directory-note" role="status">当前阅读的知识库不在目录筛选结果中，阅读和全文检索不受影响。</div>}
        <div className="knowledge-heading">
          <div><span className="document-kicker">KNOWLEDGE COLLECTION</span><h2>{active.name}</h2><p>{active.description || '为这个知识库添加一段说明，让团队更清楚它的用途。'}</p></div>
          <div className="ea-resource-actions">
            {active.read_only ? <span className="ea-resource-read-only">系统默认 · 只读</span> : <>
              {(active.default_template_id || personalOverride) && <span className="ea-resource-origin">{personalOverride ? '默认来源 · 已个人定制' : '系统默认 · 可编辑'}</span>}
              <button className="icon-button" aria-label="编辑知识库" onClick={() => setEdit(active)}><Pencil size={16} /></button>
              <button className="icon-button danger-text" aria-label="删除知识库" onClick={() => confirm('删除知识库及文档？', `“${active.name}”中的所有文档与检索片段将永久删除。`, async () => {
                if (active.read_only) return;
                await api.delete(`/knowledge/${active.id}`);
                dataChanged();
                setSelected(null);
                setResults(null);
                notify('知识库已删除');
              })}><Trash2 size={16} /></button>
            </>}
            {typeof active.usage_count === 'number' && <span className="ea-resource-usage">调用 {active.usage_count} 次</span>}
          </div>
        </div>
        {!active.read_only && (active.default_template_id || personalOverride) && <div className="ea-resource-personal-note">{personalOverride ? '此知识库已个人定制，与系统模板独立。' : '这是当前账户的默认知识库副本，编辑或增删文档后即与系统模板独立。'}修改仅影响当前账户，不影响其他用户；删除后不会重新出现。</div>}
        <form className="knowledge-search" onSubmit={event => { event.preventDefault(); void search(); }}>
          <Search size={18} />
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder={`在“${active.name}”中检索关键词…`} aria-label="知识库检索关键词" required />
          <Button type="submit" busy={searching} disabled={!query.trim()} className="button-small">全文检索<ArrowRight size={14} /></Button>
        </form>
        {searchError && <div className="inline-error">{searchError}</div>}
        {results !== null ? <div className="knowledge-results">
          <div className="knowledge-results-top"><strong>找到 {results.length} 个相关片段</strong><Button variant="ghost" className="button-small" onClick={() => setResults(null)}><X size={14} />返回文档</Button></div>
          {results.length ? results.map((result, index) => <article className="search-result-card" key={`${result.id}-${index}`}>
            <div><FileText size={15} /><strong>{result.document_name}</strong><span>匹配度 {Number.isFinite(result.score) ? result.score.toFixed(3) : '—'}</span></div>
            <pre>{result.content}</pre>
          </article>) : <EmptyState compact icon={Search} title="没有找到匹配片段" description="尝试更具体的关键词，并确认文档已成功索引。" />}
        </div> : <>
          {!active.read_only && <UploadArea upload={upload} busy={busy} compact accept=".txt,.text,.md,.csv,.json,.yaml,.yml,.log,.py,.js,.ts,.pdf" description="支持文本、Markdown、PDF、CSV、JSON、YAML、日志与代码。上传后自动提取和索引。" />}
          {documentsError && <ErrorState message={documentsError} retry={() => setDocumentRevision(revision => revision + 1)} />}
          {documentsLoading ? <Loading text="读取文档索引…" /> : documents.length ? <div className="knowledge-documents">
            {documents.map(document => <div className="knowledge-document" key={document.id}>
              <FileGlyph name={document.name} />
              <div><strong>{document.name}</strong><span>{fileSize(document.size)}<i>·</i>{document.chunk_count} 个片段<i>·</i>{dateTime(document.created_at, true)}</span></div>
              <span className="document-indexed"><CheckCircle2 size={13} />已索引</span>
              <AsyncButton variant="ghost" className="button-small" action={async () => {
                const detail = await api.get<{ id: string; name: string; text: string }>(`/knowledge/${active.id}/documents/${document.id}`);
                if (activeKnowledgeId.current === active.id) setReading(detail);
              }}><BookOpen size={14} />阅读</AsyncButton>
              {!active.read_only && <button className="icon-button danger-text" aria-label={`删除${document.name}`} onClick={() => confirm('删除已索引文档？', `“${document.name}”及其所有检索片段将被移除。`, async () => {
                if (active.read_only) return;
                await api.delete(`/knowledge/${active.id}/documents/${document.id}`);
                dataChanged();
                notify('文档已移除');
              })}><Trash2 size={15} /></button>}
            </div>)}
          </div> : <EmptyState compact icon={FileText} title={active.read_only ? '暂无可阅读文档' : '等待第一份文档'} description={active.read_only ? '系统默认知识库文档由管理员维护，已有内容可通过上方全文检索查看。' : '上传与业务相关的资料后，即可在这里检索真实内容。'} />}
        </>}
      </section>}
    </div>}
    {edit && (edit === 'new' || !edit.read_only) && <FormDialog title={edit === 'new' ? '创建知识库' : '编辑知识库'} description="按业务、环境或用途组织文档，方便智能体按范围检索。" onClose={() => setEdit(null)} onSubmit={async form => {
      if (edit !== 'new' && edit.read_only) throw new Error('系统默认资源为只读，无法修改。');
      const payload = { name: formString(form, 'name'), description: formString(form, 'description') };
      const knowledge = await (edit === 'new' ? api.post<Knowledge>('/knowledge', payload) : api.patch<Knowledge>(`/knowledge/${edit.id}`, payload));
      dataChanged();
      selectKnowledge(knowledge.id);
      notify('知识库已保存');
    }}>
      {edit !== 'new' && edit.default_template_id && <Banner>修改此默认知识库的配置或增删文档，只影响当前账户的个人副本；保存后与系统模板独立，删除后不会重新出现。</Banner>}
      <Field label="知识库名称" required><input name="name" required defaultValue={edit === 'new' ? '' : edit.name} maxLength={100} placeholder="例如：生产运维手册" /></Field>
      <Field label="知识库描述"><textarea name="description" defaultValue={edit === 'new' ? '' : edit.description} rows={4} placeholder="适用业务、内容范围与维护约定" /></Field>
    </FormDialog>}
    {reading && <Modal title={`阅读文档 · ${reading.name}`} description="展示已提取的文档全文；内容仅用于阅读，不执行代码或渲染原始 HTML。" onClose={() => setReading(null)} wide>
      <div className="ea-resource-document">{reading.text ? <Content text={reading.text} /> : <EmptyState compact icon={FileText} title="文档暂无可阅读文本" description="当前文档没有提取到可展示的全文内容。" />}</div>
      <div className="modal-footer"><Button variant="secondary" onClick={() => setReading(null)}>关闭</Button></div>
    </Modal>}
    {dialog}
    <div className="bottom-note"><Database size={15} />使用本地 FTS5 全文检索。文档内容仅作为文本展示，绝不执行文件中的代码或渲染原始 HTML。</div>
  </div>;
}
