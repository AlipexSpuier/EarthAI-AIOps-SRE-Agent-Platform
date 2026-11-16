import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { AlertCircle, Archive, ArrowDownToLine, ArrowRightLeft, Check, ChevronRight, Crown, File as FileIcon, FileArchive, FileCode2, FileImage, FileText, FolderOpen, HardDrive, Info, Loader2, LockKeyhole, LogOut, Pencil, Plus, RefreshCw, RotateCcw, ShieldCheck, Trash2, UploadCloud, UserPlus, Users } from 'lucide-react';
import { Select } from '../components/Select';
import { Banner, Button, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, SearchInput, Switch, formString } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api, ApiError, errorMessage } from '../lib/api';
import { dateTime, fileSize, initials } from '../lib/format';
import { dataChanged, useResource } from '../lib/hooks';
import { canUseSpace } from '../lib/spaceAccess';
import './TeamSpacesPage.css';

export type TeamRole = 'owner' | 'manager' | 'editor' | 'viewer' | 'admin';
export interface TeamSpace {
  id: string; name: string; description: string; owner_id: string; owner_name: string; role: TeamRole;
  archived: boolean; member_count: number; file_count: number; total_size: number; created_at: string; updated_at: string;
}
export interface TeamFile {
  id: string; space_id: string; name: string; size: number; mime: string; uploader_id: string | null; uploader_name: string; created_at: string; updated_at: string;
}
export interface TeamMember {
  user_id: string; email: string; name: string; role: TeamRole; team_module_enabled: boolean; created_at: string; updated_at: string;
}
interface OwnerAccount { id: string; name: string; email: string; role?: 'user' | 'admin'; disabled?: boolean; must_change_password?: boolean }
type MemberRole = 'manager' | 'editor' | 'viewer';
type Permission = 'owner' | 'files' | 'members' | 'download' | 'leave';
type DetailDialog = { kind: 'edit-space' | 'transfer' | 'add-member' | 'archive' | 'leave' }
  | { kind: 'rename-file' | 'replace-file' | 'delete-file'; id: string }
  | { kind: 'edit-member' | 'remove-member'; id: string };
interface SpaceSnapshot { space: TeamSpace | null; files: TeamFile[]; members: TeamMember[]; loading: boolean; error: string }

const MAX_FILE_SIZE = 20 * 1024 * 1024;
const roleLabels: Record<TeamRole, string> = { owner: '所有者', manager: '管理者', editor: '编辑者', viewer: '浏览者', admin: '平台管理员' };
const roleDescriptions: Record<TeamRole, string> = {
  owner: '管理空间、全部成员和文件，可归档、恢复并转移所有权。',
  manager: '管理文件；只能添加、调整或移除浏览者和编辑者，不能授予管理者或归档空间。',
  editor: '上传、替换、重命名和永久删除团队文件，不能管理成员。',
  viewer: '查看成员与文件，并下载未归档空间的文件，不能修改。',
  admin: '后台管理所有团队空间、成员和文件；不受个人团队模块开关限制。',
};
const ownsSpace = (space: TeamSpace, admin: boolean) => admin || space.role === 'owner' || space.role === 'admin';
const writesFiles = (space: TeamSpace, admin: boolean) => !space.archived && (ownsSpace(space, admin) || space.role === 'manager' || space.role === 'editor');
const managesMembers = (space: TeamSpace, admin: boolean) => !space.archived && (ownsSpace(space, admin) || space.role === 'manager');
const availableRoles = (space: TeamSpace, admin: boolean): MemberRole[] => ownsSpace(space, admin) ? ['viewer', 'editor', 'manager'] : ['viewer', 'editor'];
function managesMember(space: TeamSpace, member: TeamMember, admin: boolean, userId: string) {
  return managesMembers(space, admin) && member.user_id !== space.owner_id && member.role !== 'owner' && member.user_id !== userId
    && (ownsSpace(space, admin) || member.role === 'viewer' || member.role === 'editor');
}
const spacePath = (prefix: string, id: string) => `${prefix}/${encodeURIComponent(id)}`;
const filePath = (path: string, id: string) => `${path}/files/${encodeURIComponent(id)}`;
const memberPath = (path: string, id: string) => `${path}/members/${encodeURIComponent(id)}`;
const accessError = (error: unknown) => error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404);
const permissionChanged = '无权限或已变化。你可能已被移出团队，或空间权限已更新，请重新选择空间或刷新。';

export function TeamSpacesPage() { return <TeamSpaces admin={false} />; }
export function AdminTeamSpacesPage() { return <TeamSpaces admin />; }

function TeamSpaces({ admin }: { admin: boolean }) {
  const { user } = useAuth();
  const account = user;
  const enabled = Boolean(account && (admin ? account.role === 'admin' && !account.disabled && !account.must_change_password : canUseSpace(account, 'team')));
  return <TeamSpacesWorkspace key={`${admin}:${account?.id || 'anonymous'}:${enabled}`} admin={admin} userId={account?.id || ''} enabled={enabled} />;
}

function TeamSpacesWorkspace({ admin, userId, enabled }: { admin: boolean; userId: string; enabled: boolean }) {
  const prefix = admin ? '/admin/team-spaces' : '/team-spaces';
  const [includeArchived, setIncludeArchived] = useState(false);
  const spaces = useResource<TeamSpace[]>(enabled ? `${prefix}${includeArchived ? '?include_archived=true' : ''}` : null, []);
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const notify = useToast();
  const query = search.trim().toLocaleLowerCase();
  const filtered = spaces.data.filter(space => `${space.name} ${space.description}`.toLocaleLowerCase().includes(query));
  const selected = spaces.data.find(space => space.id === selectedId) || (!selectedId ? spaces.data[0] : undefined);

  useEffect(() => {
    if (enabled && !selectedId && !spaces.loading && !spaces.error && spaces.data[0]) setSelectedId(spaces.data[0].id);
  }, [enabled, selectedId, spaces.data, spaces.loading, spaces.error]);
  useEffect(() => {
    if (!enabled) return;
    const focus = () => { void spaces.reload(true); };
    window.addEventListener('focus', focus);
    return () => window.removeEventListener('focus', focus);
  }, [enabled, spaces.reload]);

  return <div className={`page ea-team-page${admin ? ' ea-team-admin-page' : ''}`} data-team-mode={admin ? 'admin' : 'user'}>
    <PageHeader eyebrow={admin ? 'TEAM SPACE ADMINISTRATION' : 'A SHARED PLACE TO WORK'} title={admin ? '团队空间管理' : '团队空间'} description={admin ? '按成员角色管理共享文件；归档保留文件，所有权变更由服务端校验。' : '把团队资料放在一起，按角色协作。与你的个人空间独立，不会读取个人文件。'} action={enabled ? <Button onClick={() => setCreating(true)} data-team-action="create-space"><Plus size={16} />创建团队空间</Button> : undefined} />
    {!enabled ? <div className="panel ea-team-disabled" data-team-disabled><EmptyState compact icon={LockKeyhole} title={admin ? '仅平台管理员可进入后台' : '团队空间尚未启用'} description={admin ? '请使用有后台权限的管理员账户。' : '管理员尚未为当前账户启用团队空间，或账户已停用。此页不会请求团队数据，个人空间权限保持独立。'} /></div> : <>
      <div className="ea-team-toolbar">
        <span className="ea-team-toolbar-caption"><ShieldCheck size={16} />共享文件，仅限授权成员</span>
        <Switch checked={includeArchived} onChange={setIncludeArchived} label="包含已归档" />
        <Button variant="ghost" className="button-small" onClick={() => dataChanged()} aria-label="刷新团队空间"><RefreshCw size={14} />刷新</Button>
      </div>
      <div className="ea-team-workbench">
        <aside className="ea-team-directory" aria-label="团队空间列表">
          <div className="ea-team-directory-heading"><div><FolderOpen size={17} /><strong>我的团队{admin ? ' · 全部' : ''}</strong><span>{spaces.data.length}</span></div><SearchInput value={search} onChange={setSearch} placeholder="搜索空间名称或描述…" /></div>
          <div className="ea-team-list-scroll" role="region" aria-label="空间目录" tabIndex={0}>
            {spaces.error ? <ErrorState message={spaces.error} retry={() => spaces.reload()} /> : spaces.loading ? <Loading text="正在读取团队空间…" /> : !filtered.length ? <EmptyState compact icon={Users} title={search ? '没有匹配的团队空间' : '还没有团队空间'} description={search ? '试试其他名称或描述。' : '创建一个空间，或请所有者通过准确的账户邮箱添加你。'} /> : filtered.map(space => <button type="button" key={space.id} className={`ea-team-space-card${selected?.id === space.id ? ' selected' : ''}`} aria-pressed={selected?.id === space.id} data-team-space-id={space.id} onClick={() => setSelectedId(space.id)}>
              <span className="ea-team-space-icon">{space.archived ? <Archive size={20} /> : <Users size={20} />}</span>
              <span className="ea-team-space-copy"><span className="ea-team-space-title"><strong>{space.name}</strong><ChevronRight size={14} /></span><span className="ea-team-space-description">{space.description || '团队共享的文件与协作资料'}</span><span className="ea-team-space-meta"><span>{roleLabels[space.role]}</span>{space.archived && <span className="ea-team-archived-label">已归档</span>}<span>{space.member_count} 位成员 · {space.file_count} 个文件</span></span></span>
            </button>)}
          </div>
          <div className="ea-team-directory-footer"><LockKeyhole size={12} />角色与权限以服务器实时校验为准</div>
        </aside>
        {spaces.error ? <div className="ea-team-detail ea-team-detail-placeholder"><ErrorState message="目录读取失败，已隐藏空间操作。请刷新后重试。" retry={() => spaces.reload()} /></div> : selected ? <TeamSpaceDetail key={`${prefix}/${selected.id}`} id={selected.id} prefix={prefix} admin={admin} userId={userId} onArchived={() => setIncludeArchived(true)} onInvalidated={() => { void spaces.reload(true); }} onUpdated={space => spaces.setData(current => current.map(item => item.id === space.id ? space : item))} /> : <div className="ea-team-detail ea-team-detail-placeholder"><EmptyState compact icon={FolderOpen} title={selectedId ? '无权限或已变化' : '选择一个团队空间'} description={selectedId ? '该空间已归档、成员关系已变化，或不在当前目录中。可启用“包含已归档”或重新选择空间。' : '在左侧选择空间，查看共享文件、成员和你的角色权限。'} /></div>}
      </div>
      {creating && <CreateTeamSpace admin={admin} prefix={prefix} onClose={() => setCreating(false)} onCreated={space => {
        spaces.setData(current => [...current.filter(item => item.id !== space.id), space]);
        setSelectedId(space.id);
        dataChanged();
        notify('团队空间已创建');
      }} />}
    </>}
  </div>;
}

function CreateTeamSpace({ admin, prefix, onClose, onCreated }: { admin: boolean; prefix: string; onClose: () => void; onCreated: (space: TeamSpace) => void }) {
  const users = useResource<OwnerAccount[]>(admin ? '/admin/users' : null, []);
  const owners = users.data.filter(user => user.role !== 'admin' && !user.disabled && !user.must_change_password);
  const [ownerId, setOwnerId] = useState('');
  return <TeamDialog title="创建团队空间" description="共享文件不会进入个人空间，也不会自动发送给模型或外部服务。" onClose={onClose} submitLabel="创建空间" onSubmit={async form => {
    if (admin && (users.loading || users.error || !owners.some(user => user.id === ownerId))) throw new Error('请选择一个未停用的普通用户作为所有者。');
    const name = formString(form, 'name');
    if (!name) throw new Error('请输入空间名称。');
    const payload = { name, description: formString(form, 'description'), ...(admin ? { owner_id: ownerId } : {}) };
    onCreated(await api.post<TeamSpace>(prefix, payload));
  }}>
    {admin && <Field label="空间所有者" required hint="只显示未停用的普通账户；管理员不能拥有团队空间。">
      <div>{users.error ? <ErrorState message={users.error} retry={() => users.reload()} /> : <Select name="owner_id" label="空间所有者" value={ownerId} onChange={setOwnerId} searchable required disabled={users.loading} placeholder={users.loading ? '正在读取用户…' : '选择普通用户'} options={owners.map(user => ({ value: user.id, label: `${user.name} · ${user.email}`, keywords: user.email }))} emptyText="没有可用的普通用户" />}</div>
    </Field>}
    <Field label="空间名称" required><input name="name" required maxLength={120} placeholder="例如：产品协作资料" autoComplete="off" /></Field>
    <Field label="空间描述"><textarea name="description" rows={3} maxLength={2000} placeholder="说明资料用途、协作范围和团队约定" /></Field>
    <Banner>{admin ? '选中的普通用户将成为所有者；账户是否允许团队功能仍由服务器检查。' : '你将成为所有者。之后可按准确的账户邮箱添加现有用户，不会创建新账户。'}</Banner>
  </TeamDialog>;
}

function TeamSpaceDetail({ id, prefix, admin, userId, onArchived, onInvalidated, onUpdated }: { id: string; prefix: string; admin: boolean; userId: string; onArchived: () => void; onInvalidated: () => void; onUpdated: (space: TeamSpace) => void }) {
  const path = spacePath(prefix, id);
  const [snapshot, setSnapshot] = useState<SpaceSnapshot>({ space: null, files: [], members: [], loading: true, error: '' });
  const latest = useRef(snapshot); latest.current = snapshot;
  const alive = useRef(true);
  const requestId = useRef(0);
  const operation = useRef(false);
  const [busy, setBusy] = useState('');
  const [actionError, setActionError] = useState('');
  const [tab, setTab] = useState<'files' | 'members'>('files');
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<DetailDialog | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const notify = useToast();
  const invalidated = useRef(onInvalidated); invalidated.current = onInvalidated;
  const updated = useRef(onUpdated); updated.current = onUpdated;

  const clearAccess = useCallback((message: string) => {
    requestId.current += 1;
    const empty = { space: null, files: [], members: [], loading: false, error: message };
    latest.current = empty;
    setSnapshot(empty);
    setEditing(null);
    setActionError('');
  }, []);
  const refresh = useCallback(async () => {
    const request = ++requestId.current;
    latest.current = { ...latest.current, loading: true };
    setSnapshot(latest.current);
    try {
      const space = await getTeamResource<TeamSpace>(path);
      const [files, members] = await Promise.all([space.archived ? Promise.resolve([] as TeamFile[]) : getTeamResource<TeamFile[]>(`${path}/files`), getTeamResource<TeamMember[]>(`${path}/members`)]);
      if (!alive.current || request !== requestId.current) return;
      const previous = latest.current.space;
      if (previous && (previous.role !== space.role || previous.archived !== space.archived || previous.owner_id !== space.owner_id)) setEditing(null);
      const next = { space, files, members, loading: false, error: '' };
      latest.current = next;
      setSnapshot(next);
      updated.current(space);
    } catch (error) {
      if (!alive.current || request !== requestId.current) return;
      clearAccess(accessError(error) ? permissionChanged : `读取失败，已隐藏旧数据与操作。${errorMessage(error)}`);
      if (accessError(error)) invalidated.current();
    }
  }, [path, clearAccess]);

  useEffect(() => {
    alive.current = true;
    void refresh();
    const reload = () => { void refresh(); };
    window.addEventListener('earthai:data-changed', reload);
    window.addEventListener('focus', reload);
    return () => {
      alive.current = false;
      requestId.current += 1;
      window.removeEventListener('earthai:data-changed', reload);
      window.removeEventListener('focus', reload);
    };
  }, [refresh]);

  const requirePermission = (permission: Permission) => {
    const current = latest.current;
    if (!alive.current || !current.space || current.error) throw new Error(permissionChanged);
    if (current.loading) throw new Error('正在校验当前团队权限，请稍后重试。');
    const space = current.space;
    const allowed = permission === 'owner' ? ownsSpace(space, admin)
      : permission === 'files' ? writesFiles(space, admin)
        : permission === 'members' ? managesMembers(space, admin)
          : permission === 'download' ? !space.archived
            : !admin && !space.archived && ['viewer', 'editor', 'manager'].includes(space.role);
    if (!allowed) throw new Error(space.archived ? '空间已归档，请等待所有者或管理员恢复后再操作。' : '你的当前角色无权执行此操作，请刷新空间。');
    return space;
  };
  const perform = async (permission: Permission, action: (space: TeamSpace) => Promise<unknown>, message: string, write = true) => {
    if (operation.current) throw new Error('已有操作进行中，请稍后重试。');
    const current = requirePermission(permission);
    operation.current = true;
    setBusy(message);
    setActionError('');
    try {
      await action(current);
      if (alive.current) setEditing(null);
      if (write) dataChanged();
      notify(message);
    } catch (error) {
      if (alive.current) {
        if (accessError(error)) { clearAccess(permissionChanged); invalidated.current(); }
        else setActionError(errorMessage(error));
      }
      throw error;
    } finally {
      operation.current = false;
      if (alive.current) setBusy('');
    }
  };
  const upload = (file: File) => {
    void perform('files', () => { validateFile(file); return api.upload<TeamFile>(`${path}/files`, file); }, '团队文件已上传').catch(() => undefined);
  };

  const { space, files, members, loading, error } = snapshot;
  const owner = space ? ownsSpace(space, admin) : false;
  const canWrite = space ? writesFiles(space, admin) : false;
  const canManage = space ? managesMembers(space, admin) : false;
  const disabled = Boolean(busy) || loading;
  const filteredFiles = files.filter(file => file.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const selectedFile = editing && 'id' in editing ? files.find(file => file.id === editing.id) : undefined;
  const selectedMember = editing && 'id' in editing ? members.find(member => member.user_id === editing.id) : undefined;
  const canEditMember = Boolean(space && selectedMember && managesMember(space, selectedMember, admin, userId));
  const roleOptions = space ? availableRoles(space, admin).map(role => ({ value: role, label: roleLabels[role], description: roleDescriptions[role] })) : [];
  const currentMember = (memberId: string, current: TeamSpace) => {
    const member = latest.current.members.find(item => item.user_id === memberId);
    if (!member || !managesMember(current, member, admin, userId)) throw new Error('成员或权限已变化，不能直接调整所有者、自己或同级管理者。请刷新。');
    return member;
  };

  return <section className="ea-team-detail" role="region" aria-label="团队空间详情" tabIndex={0} data-team-detail-id={id} aria-busy={loading}>
    {error ? <div className="ea-team-detail-placeholder" data-team-access-error><ErrorState message={error} retry={() => refresh()} /></div> : !space ? <Loading text="正在校验空间与成员权限…" /> : <>
      <div className="ea-team-detail-header">
        <div className="ea-team-detail-title"><span className="ea-team-kicker">{space.archived ? 'ARCHIVED TEAM SPACE' : 'TEAM WORKSPACE'}</span><h2>{space.name}</h2><p>{space.description || '这里收纳团队共享的工作资料。'}</p></div>
        <div className="ea-team-header-actions">
          {loading && <Loader2 className="spin" size={16} aria-label="正在刷新团队权限" />}
          <RoleBadge role={admin ? 'admin' : space.role} />
          {(owner || space.role === 'manager') && !space.archived && <Button variant="ghost" className="button-small" disabled={disabled} data-team-action="edit-space" onClick={() => setEditing({ kind: 'edit-space' })}><Pencil size={14} />编辑</Button>}
          {owner && !space.archived && <Button variant="secondary" className="button-small" disabled={disabled} data-team-action="transfer" onClick={() => setEditing({ kind: 'transfer' })}><ArrowRightLeft size={14} />转移</Button>}
          {owner && (space.archived ? <Button variant="secondary" className="button-small" disabled={disabled} data-team-action="restore" onClick={() => { void perform('owner', () => api.post(`${path}/restore`), '团队空间已恢复').catch(() => undefined); }}><RotateCcw size={14} />恢复空间</Button> : <Button variant="ghost" className="button-small" disabled={disabled} data-team-action="archive" onClick={() => setEditing({ kind: 'archive' })}><Archive size={14} />归档</Button>)}
          {!admin && !space.archived && ['viewer', 'editor', 'manager'].includes(space.role) && <Button variant="ghost" className="button-small danger-text" disabled={disabled} data-team-action="leave" onClick={() => setEditing({ kind: 'leave' })}><LogOut size={14} />离开</Button>}
        </div>
      </div>
      <div className="ea-team-summary"><span><Crown size={14} />所有者：{space.owner_name || '未命名账户'}</span><span><Users size={14} />{space.member_count} 位成员</span><span><HardDrive size={14} />{space.file_count} 个文件 · {fileSize(space.total_size)}</span><span>更新于 {dateTime(space.updated_at, true)}</span></div>
      {space.archived ? <div className="ea-team-archive-notice" role="status" data-team-archived><Archive size={19} /><div><strong>空间已归档，文件仍被保留</strong><p>所有文件上传、替换、重命名、删除和下载均已暂停。{owner ? '恢复空间后，成员才可按角色继续协作。' : '请等待所有者或平台管理员恢复空间。'}</p></div></div> : <div className="ea-team-role-note"><ShieldCheck size={15} /><p>{roleLabels[admin ? 'admin' : space.role]}：{roleDescriptions[admin ? 'admin' : space.role]}</p></div>}
      {actionError && <div className="inline-error ea-team-action-error" role="alert"><AlertCircle size={16} />{actionError}</div>}
      {busy && <div className="ea-team-progress" role="status"><Loader2 className="spin" size={14} />正在处理，请勿重复提交…</div>}
      <div className="ea-team-tabs" role="tablist" aria-label="空间内容">
        <button id={`team-files-${id}`} type="button" role="tab" aria-selected={tab === 'files'} aria-controls={`team-panel-${id}`} onClick={() => setTab('files')}><FolderOpen size={16} />共享文件<span>{files.length}</span></button>
        <button id={`team-members-${id}`} type="button" role="tab" aria-selected={tab === 'members'} aria-controls={`team-panel-${id}`} onClick={() => setTab('members')}><Users size={16} />团队成员<span>{members.length}</span></button>
      </div>
      <div id={`team-panel-${id}`} className="ea-team-tab-panel" role="tabpanel" aria-labelledby={`team-${tab}-${id}`}>
        {tab === 'files' ? <>
          <div className="ea-team-content-toolbar"><SearchInput value={search} onChange={setSearch} placeholder="搜索团队文件名…" /><div className="ea-team-upload-action"><small>单个文件不超过 20 MB</small>{canWrite && <Button className="button-small" disabled={disabled} data-team-action="upload" onClick={() => uploadInput.current?.click()}><UploadCloud size={15} />上传文件</Button>}</div><input ref={uploadInput} type="file" className="ea-team-file-input" aria-label="上传团队文件" disabled={!canWrite || disabled} onChange={event => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (file) upload(file); }} /></div>
          {!filteredFiles.length ? <EmptyState compact icon={FileIcon} title={search ? '没有找到这个文件' : '还没有共享文件'} description={search ? '文件名搜索仅在当前空间内进行。' : space.archived ? '空间已归档，恢复后可上传文件。' : canWrite ? '上传第一份资料，让团队在同一个空间协作。' : '有编辑权限的成员上传文件后，你就能在这里查看。'} /> : <div className="ea-team-files" data-team-files>{filteredFiles.map(file => <article className="ea-team-file-row" key={file.id} data-team-file-id={file.id}>
            <span className="ea-team-file-icon"><TeamFileIcon file={file} /></span><div className="ea-team-file-copy"><strong title={file.name}>{file.name}</strong><p><span>{fileSize(file.size)}</span><span>{file.uploader_name || '未命名成员'}</span><time dateTime={file.updated_at}>{dateTime(file.updated_at, true)}</time></p></div>
            <div className="ea-team-row-actions"><Button variant="ghost" className="button-small" aria-label={`下载 ${file.name}`} disabled={disabled || space.archived} onClick={() => { void perform('download', () => downloadTeamFile(filePath(path, file.id), file.name), '已开始下载团队文件', false).catch(() => undefined); }}><ArrowDownToLine size={15} /><span className="ea-team-download-label">下载</span></Button>{canWrite && <>
              <button type="button" className="icon-button" disabled={disabled} aria-label={`重命名 ${file.name}`} onClick={() => setEditing({ kind: 'rename-file', id: file.id })}><Pencil size={15} /></button>
              <button type="button" className="icon-button" disabled={disabled} aria-label={`替换 ${file.name}`} onClick={() => setEditing({ kind: 'replace-file', id: file.id })}><RefreshCw size={15} /></button>
              <button type="button" className="icon-button danger-text" disabled={disabled} aria-label={`永久删除 ${file.name}`} onClick={() => setEditing({ kind: 'delete-file', id: file.id })}><Trash2 size={15} /></button>
            </>}</div>
          </article>)}</div>}
          <div className="ea-team-privacy-note"><LockKeyhole size={13} /><span>文件仅通过本站鉴权下载，不会自动读取个人文件，也不会发送给模型或外部服务。</span></div>
        </> : <>
          <div className="ea-team-content-toolbar"><p className="ea-team-members-intro">所有成员均可查看名单，权限修改以服务器校验为准。</p>{canManage && <Button className="button-small" disabled={disabled} data-team-action="add-member" onClick={() => setEditing({ kind: 'add-member' })}><UserPlus size={15} />添加成员</Button>}</div>
          <div className="ea-team-members" data-team-members>{members.map(member => <article className="ea-team-member-row" key={member.user_id} data-team-member-id={member.user_id}>
            <span className="ea-team-member-avatar">{initials(member.name || member.email)}</span><div className="ea-team-member-copy"><strong>{member.name || member.email}{member.user_id === userId && <small>你</small>}</strong><span title={member.email}>{member.email}</span><small className={!member.team_module_enabled ? 'ea-team-member-disabled' : ''}>{member.team_module_enabled ? '团队模块已启用' : '团队模块未启用，当前无法访问'}</small></div>
            <div className="ea-team-member-actions"><RoleBadge role={member.role} />{managesMember(space, member, admin, userId) && <><button type="button" className="icon-button" disabled={disabled} aria-label={`修改 ${member.name || member.email} 的角色`} onClick={() => setEditing({ kind: 'edit-member', id: member.user_id })}><Pencil size={15} /></button><button type="button" className="icon-button danger-text" disabled={disabled} aria-label={`移除 ${member.name || member.email}`} onClick={() => setEditing({ kind: 'remove-member', id: member.user_id })}><LogOut size={15} /></button></>}</div>
          </article>)}</div>
          {!members.length && <EmptyState compact icon={Users} title="暂无成员记录" description="请刷新以获取服务器上的最新成员关系。" />}
          {owner && <div className="ea-team-owner-hint"><Info size={15} /><span>所有者不能直接降级、移除或离开。删除所有者账户或将其升级为管理员前，须先转移其拥有的全部团队空间，包括已归档空间。</span></div>}
          <details className="ea-team-role-guide"><summary><ShieldCheck size={15} />了解成员角色</summary><div>{(['owner', 'manager', 'editor', 'viewer'] as TeamRole[]).map(role => <p key={role}><strong>{roleLabels[role]}</strong><span>{roleDescriptions[role]}</span></p>)}</div></details>
        </>}
      </div>
      {editing?.kind === 'edit-space' && (owner || space.role === 'manager') && !space.archived && <TeamDialog title="编辑团队空间" description="名称和描述对全部有访问权限的成员可见。" onClose={() => setEditing(null)} onSubmit={form => {
        const name = formString(form, 'name');
        if (!name) return Promise.reject(new Error('请输入空间名称。'));
        return perform('members', () => api.patch<TeamSpace>(path, { name, description: formString(form, 'description') }), '团队空间已更新');
      }}><Field label="空间名称" required><input name="name" required maxLength={120} defaultValue={space.name} /></Field><Field label="空间描述"><textarea name="description" rows={3} maxLength={2000} defaultValue={space.description} /></Field></TeamDialog>}
      {editing?.kind === 'archive' && owner && !space.archived && <TeamDialog title="归档团队空间？" description="这是软归档，不会删除任何团队文件。" danger submitLabel="归档空间" onClose={() => setEditing(null)} onSubmit={async () => { await perform('owner', () => api.delete(path), '团队空间已归档，文件未删除'); onArchived(); }}><Banner tone="warning">“{space.name}”归档后，所有成员将无法写入或下载文件。所有者或平台管理员可在“包含已归档”中恢复。</Banner></TeamDialog>}
      {editing?.kind === 'transfer' && owner && !space.archived && <TransferTeamSpace space={space} members={members} admin={admin} onClose={() => setEditing(null)} onTransfer={user_id => perform('owner', current => {
        const target = latest.current.members.find(member => member.user_id === user_id && member.user_id !== current.owner_id && ['manager', 'editor', 'viewer'].includes(member.role));
        if (!target) throw new Error('请选择当前空间中的普通成员，成员关系可能已变化。');
        return api.post<TeamSpace>(`${path}/transfer`, { user_id });
      }, '所有权已转移，原所有者已变为管理者')} />}
      {editing?.kind === 'leave' && !admin && !space.archived && ['viewer', 'editor', 'manager'].includes(space.role) && <TeamDialog title="离开团队空间？" description="不会删除团队文件；离开后将失去文件和成员的访问权限。" danger submitLabel="确认离开" onClose={() => setEditing(null)} onSubmit={() => perform('leave', () => api.delete(memberPath(path, userId)), '已离开团队空间')}><Banner tone="warning">离开“{space.name}”后，需要其他管理成员重新添加你才能访问。所有者必须先转移所有权才能离开。</Banner></TeamDialog>}
      {editing?.kind === 'add-member' && canManage && <TeamDialog title="添加已有账户" description="使用准确的账户邮箱匹配用户，不会创建新账号。" submitLabel="添加成员" onClose={() => setEditing(null)} onSubmit={form => perform('members', current => {
        const role = formString(form, 'role');
        if (!availableRoles(current, admin).includes(role as MemberRole)) throw new Error('当前角色不能授予此成员权限。');
        const email = formString(form, 'email');
        if (!email) throw new Error('请输入现有账户的准确邮箱。');
        return api.post<TeamMember>(`${path}/members`, { email, role });
      }, '团队成员已添加')}><Field label="账户邮箱 / 登录账号" required hint="必须与现有账户的邮箱或登录账号完全匹配。"><input name="email" type="text" required autoComplete="off" placeholder="colleague@example.com 或登录账号" /></Field><Field label="成员角色" required><Select label="成员角色" name="role" defaultValue="viewer" options={roleOptions} required /></Field><Banner>若对方尚未启用团队模块，添加成功后会自动启用；若平台明确禁止该账户使用团队功能，服务器会拒绝添加并显示原因，不会伪报成功。</Banner></TeamDialog>}
      {editing?.kind === 'edit-member' && selectedMember && canEditMember && <TeamDialog title="调整成员角色" description={`${selectedMember.name || selectedMember.email} · ${selectedMember.email}`} onClose={() => setEditing(null)} onSubmit={form => perform('members', current => {
        currentMember(selectedMember.user_id, current);
        const role = formString(form, 'role');
        if (!availableRoles(current, admin).includes(role as MemberRole)) throw new Error('当前角色不能授予此成员权限。');
        return api.patch<TeamMember>(memberPath(path, selectedMember.user_id), { role });
      }, '成员角色已更新')}><Field label="成员角色" required><Select label="成员角色" name="role" defaultValue={selectedMember.role} options={roleOptions} required /></Field><Banner>管理者只能管理浏览者和编辑者；不能授予管理者，也不能修改所有者、自己或其他管理者。</Banner></TeamDialog>}
      {editing?.kind === 'remove-member' && selectedMember && canEditMember && <TeamDialog title="移除团队成员？" description="移除只影响访问权限，不会删除该成员上传的团队文件。" danger submitLabel="移除成员" onClose={() => setEditing(null)} onSubmit={() => perform('members', current => { currentMember(selectedMember.user_id, current); return api.delete(memberPath(path, selectedMember.user_id)); }, '成员已移除')}><Banner tone="warning">“{selectedMember.name || selectedMember.email}”将立即失去此团队的访问权限。</Banner></TeamDialog>}
      {editing?.kind === 'rename-file' && selectedFile && canWrite && <TeamDialog title="重命名团队文件" description="只修改文件名，不修改内容。建议保留原扩展名。" onClose={() => setEditing(null)} onSubmit={form => {
        const name = formString(form, 'name');
        if (!name) return Promise.reject(new Error('请输入文件名。'));
        return perform('files', () => api.patch<TeamFile>(filePath(path, selectedFile.id), { name }), '团队文件已重命名');
      }}><Field label="文件名" required><input name="name" required maxLength={200} defaultValue={selectedFile.name} /></Field></TeamDialog>}
      {editing?.kind === 'replace-file' && selectedFile && canWrite && <TeamDialog title="替换团队文件内容" description={`将直接覆盖“${selectedFile.name}”的内容，没有版本恢复。`} submitLabel="确认替换" onClose={() => setEditing(null)} onSubmit={form => perform('files', () => {
        const file = form.get('file');
        if (!(file instanceof File) || !file.name) throw new Error('请选择要替换的文件。');
        validateFile(file);
        return replaceTeamFile(filePath(path, selectedFile.id), file);
      }, '团队文件内容已替换')}><Field label="新文件" required hint="单个文件不超过 20 MB；仅覆盖当前团队文件，不影响其他文件。"><input name="file" type="file" required /></Field><Banner tone="warning">原内容将被永久覆盖。请确认文件后再提交。</Banner></TeamDialog>}
      {editing?.kind === 'delete-file' && selectedFile && canWrite && <TeamDialog title="永久删除这个团队文件？" description="此操作不是归档，删除后无法恢复。" danger submitLabel="永久删除文件" onClose={() => setEditing(null)} onSubmit={() => perform('files', () => api.delete(filePath(path, selectedFile.id)), '这个团队文件已永久删除')}><Banner tone="warning">将永久删除“{selectedFile.name}”（{fileSize(selectedFile.size)}）及其内容。只删除这个文件，不会归档空间或删除其他文件。</Banner></TeamDialog>}
    </>}
  </section>;
}

function TransferTeamSpace({ space, members, admin, onClose, onTransfer }: { space: TeamSpace; members: TeamMember[]; admin: boolean; onClose: () => void; onTransfer: (userId: string) => Promise<unknown> }) {
  const users = useResource<OwnerAccount[]>(admin ? '/admin/users' : null, []);
  const [targetId, setTargetId] = useState('');
  const candidates = members.filter(member => member.user_id !== space.owner_id && ['manager', 'editor', 'viewer'].includes(member.role));
  const activeUsers = users.data.filter(user => user.role !== 'admin' && !user.disabled && !user.must_change_password);
  const eligible = admin ? candidates.filter(member => activeUsers.some(user => user.id === member.user_id)) : candidates;
  return <TeamDialog title="转移团队空间所有权" description="可转给当前空间中的未停用普通账户；原所有者将变为管理者。已归档空间须先恢复再转移。" submitLabel="确认转移所有权" onClose={onClose} onSubmit={async () => {
    if (admin && (users.loading || users.error)) throw new Error('无法确认目标账户状态，请重新读取用户列表。');
    if (!eligible.some(member => member.user_id === targetId)) throw new Error('请选择一个现有的普通成员。');
    await onTransfer(targetId);
  }}>
    {admin && users.error && <ErrorState message={users.error} retry={() => users.reload()} />}
    <Field label="新所有者" required hint="不能转给管理员、已停用账户或非成员。最终资格由服务器校验。"><Select name="user_id" label="新所有者" value={targetId} onChange={setTargetId} required searchable disabled={admin && (users.loading || Boolean(users.error))} options={eligible.map(member => ({ value: member.user_id, label: `${member.name || member.email} · ${member.email}`, description: roleLabels[member.role], keywords: member.email }))} emptyText="没有可转移的现有普通成员" /></Field>
    {!candidates.length && <Banner tone="warning">请先在成员页添加一位普通成员，再转移所有权。归档空间可先恢复后添加成员。</Banner>}
    <Banner tone="warning">转移后，原所有者失去归档、恢复和再次转移的权限。删除所有者账户或将其升级为管理员前，必须转移其全部团队空间（含已归档）。</Banner>
  </TeamDialog>;
}

function TeamDialog({ title, description, onClose, onSubmit, children, submitLabel = '保存', danger = false }: { title: string; description?: string; onClose: () => void; onSubmit: (form: FormData) => Promise<unknown>; children: ReactNode; submitLabel?: string; danger?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending.current) return;
    const form = new FormData(event.currentTarget);
    pending.current = true;
    setBusy(true);
    setError('');
    try { await onSubmit(form); if (mounted.current) onClose(); }
    catch (error) { if (mounted.current) setError(errorMessage(error)); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  return <Modal title={title} description={description} onClose={onClose} preventClose={busy}>
    <form className="ea-team-form" onSubmit={event => { void submit(event); }}><fieldset className="form-body" disabled={busy}>{children}{error && <div className="inline-error" role="alert"><AlertCircle size={16} />{error}</div>}</fieldset><div className="modal-footer"><span className="small muted">更改会同步给有权限的团队成员</span><Button type="button" variant="secondary" disabled={busy} onClick={onClose}>取消</Button><Button type="submit" variant={danger ? 'danger' : 'primary'} busy={busy}>{danger ? <AlertCircle size={15} /> : <Check size={15} />}{submitLabel}</Button></div></form>
  </Modal>;
}

function RoleBadge({ role }: { role: TeamRole }) { return <span className={`ea-team-role ea-team-role-${role}`} title={roleDescriptions[role]} data-team-role={role}>{role === 'owner' && <Crown size={11} />}{roleLabels[role]}</span>; }
function TeamFileIcon({ file }: { file: TeamFile }) {
  if (file.mime.startsWith('image/')) return <FileImage size={21} />;
  if (/zip|gzip|tar|compressed/.test(file.mime)) return <FileArchive size={21} />;
  if (/json|javascript|xml/.test(file.mime) || /\.(py|tsx?|jsx?|sh|ya?ml|toml)$/i.test(file.name)) return <FileCode2 size={21} />;
  if (file.mime.startsWith('text/') || file.mime === 'application/pdf') return <FileText size={21} />;
  return <FileIcon size={21} />;
}
function validateFile(file: File) { if (file.size > MAX_FILE_SIZE) throw new Error('文件不能超过 20 MB，请选择更小的文件。'); }
async function teamResponseError(response: Response, fallback: string) {
  const body: unknown = await response.json().catch(() => null);
  let message = `${fallback}（${response.status}）`;
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail)) message = detail.map((item: { msg?: string; loc?: unknown[] }) => `${item.loc?.slice(1).join('.') || '输入'}：${item.msg || '格式有误'}`).join('；') || message;
  }
  if (response.status === 401) window.dispatchEvent(new Event('earthai:unauthorized'));
  if (response.status === 403) window.dispatchEvent(new Event('earthai:permissions-refresh'));
  return new ApiError(message, response.status);
}
async function getTeamResource<T>(path: string): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api${path}`, { credentials: 'same-origin', mode: 'same-origin', cache: 'no-store' }); }
  catch { throw new Error('读取团队数据失败，请检查网络连接后重试。'); }
  if (!response.ok) throw await teamResponseError(response, '读取团队数据失败');
  return response.json() as Promise<T>;
}
async function replaceTeamFile(path: string, file: File): Promise<void> {
  const body = new FormData(); body.append('file', file);
  let response: Response;
  try { response = await fetch(`/api${path}/content`, { method: 'PUT', credentials: 'same-origin', mode: 'same-origin', body }); }
  catch { throw new Error('替换文件失败，请检查网络连接后重试。'); }
  if (!response.ok) throw await teamResponseError(response, '替换文件失败，请确认当前角色有编辑权限');
}
async function downloadTeamFile(path: string, name: string): Promise<void> {
  let response: Response;
  try { response = await fetch(`/api${path}/download`, { credentials: 'same-origin', mode: 'same-origin' }); }
  catch { throw new Error('下载失败，请检查网络连接后重试。'); }
  if (!response.ok) throw await teamResponseError(response, '下载失败，文件可能已变化或你已无权限');
  let blob: Blob;
  try { blob = await response.blob(); }
  catch { throw new Error('下载中断，请检查网络连接后重试。'); }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
