import { useRef, useState } from 'react';
import { FileJson } from 'lucide-react';
import { Banner, Button, Field, FormDialog, formString } from './ui';
import { useAuth } from '../context/AuthContext';
import { useCatalog } from '../context/CatalogContext';
import { useToast } from '../context/ToastContext';
import { api } from '../lib/api';
import { canUseControl, fallbackControl } from '../lib/controlAccess';
import { dataChanged } from '../lib/hooks';

const importKinds = ['agents', 'skills', 'knowledge', 'projects', 'servers', 'providers', 'schedules', 'alerts'] as const;
type UserResourceKind = typeof importKinds[number];

export function UserResourceImportButton({ kind, label }: { kind: UserResourceKind; label: string }) {
  const { user } = useAuth(); const catalog = useCatalog(); const notify = useToast();
  const [open, setOpen] = useState(false); const submitting = useRef(false);
  const defaultControl = fallbackControl(user, 'observe');
  if (!importKinds.includes(kind)) return null;
  const needsControl = kind === 'agents' || kind === 'schedules';
  const examples: Record<UserResourceKind, Record<string, unknown>[]> = {
    agents: [{ name: '巡检助手', kind: 'local', description: '只读巡检', system_prompt: '先检查再分析，只报告证据和建议，不进行变更。', skill_ids: [], knowledge_ids: [], control_level: defaultControl || 'observe' }],
    skills: [{ name: '只读巡检', description: '巡检规范', content: '检查负载、内存与磁盘，记录异常证据，不执行变更。', enabled: true }],
    knowledge: [{ name: '运维手册', description: '经审阅的个人业务知识，创建后再添加文档。' }],
    projects: [{ name: '业务项目', description: '个人业务上下文', server_ids: [], knowledge_ids: [], skill_ids: [], status: 'active', color: '#087f69' }],
    servers: [{ name: '只读主机', kind: 'ssh', host: 'ssh.example.com', port: 22, username: 'ops', auth_type: 'key', private_key: '<请替换为可信主机的 SSH 私钥>', trust_on_first_use: true, tags: [] }],
    providers: [{ name: '个人模型', base_url: 'https://api.example.com/v1', api_key: '<请替换为此可信供应商的 API Key>', models: [], default_model: '', enabled: true }],
    schedules: [{ name: '每日巡检', prompt: '仅检查并报告，不做变更。', cron: '0 9 * * *', timezone: 'Asia/Shanghai', control_level: defaultControl || 'observe', enabled: false }],
    alerts: [{ title: '待核实的巡检异常', description: '记录异常证据，核实后手动处理。', severity: 'warning', status: 'open', source: 'manual' }],
  };
  return <span style={{ display: 'contents' }} data-user-import-kind={kind} onSubmitCapture={event => {
    if (submitting.current) { event.preventDefault(); event.stopPropagation(); }
  }}>
    <Button type="button" variant="secondary" data-user-import-trigger={kind} disabled={!user || (needsControl && !defaultControl)} title={needsControl && !defaultControl ? '当前账号没有可创建资源的控制模式，请联系管理员授权。' : undefined} onClick={() => { submitting.current = false; setOpen(true); }}><FileJson size={16} />JSON 批量导入</Button>
    {open && <FormDialog title={`批量导入${label}`} description="粘贴 1–200 个资源对象的 JSON 数组，也可使用包含 items 数组的对象。本次只新增，不按名称或 ID 覆盖已有资源。" onClose={() => setOpen(false)} submitLabel="确认导入" wide onSubmit={async form => {
      submitting.current = true;
      try {
        let value: unknown;
        try { value = JSON.parse(formString(form, 'json')); } catch { throw new Error('JSON 格式有误，请检查双引号、逗号和括号。'); }
        const items: unknown = Array.isArray(value) ? value : value !== null && typeof value === 'object' && 'items' in value ? value.items : null;
        if (!Array.isArray(items) || items.length < 1 || items.length > 200 || !items.every((item: unknown): item is Record<string, unknown> => item !== null && typeof item === 'object' && !Array.isArray(item))) throw new Error('请提供含 1–200 个资源对象的数组；每一项必须是非 null、非数组的 JSON 对象。');
        const payload = items.map(item => {
          if (!needsControl) return item;
          const level = item.control_level === undefined ? defaultControl : item.control_level;
          if (!canUseControl(user, level)) throw new Error('只能使用当前账号获准的控制模式创建智能体或定时任务，请检查 control_level 或联系管理员授权。');
          if (kind === 'schedules' && item.agent_id) {
            const agent = catalog.agents.find(agent => agent.id === item.agent_id);
            if (catalog.loading) throw new Error('智能体目录尚未加载完成，请稍后重试。');
            if (!agent || agent.kind === 'remote' || !canUseControl(user, agent.control_level)) throw new Error('定时任务关联了不可执行或控制等级未获授权的智能体，请检查 agent_id。');
          }
          return kind === 'schedules' ? { enabled: false, ...item, control_level: level } : { ...item, control_level: level };
        });
        const result = await api.post<{ ok: true; count: number; warnings?: string[] }>(`/${kind}/import`, { items: payload });
        dataChanged();
        notify(`已成功导入 ${result.count} 个${label}，仅当前账号可见。`);
        if (result.warnings?.length) notify(`资源已成功导入，无需重复提交。${result.warnings.join('；')}`, 'info');
      } catch (error) { submitting.current = false; throw error; }
    }}>
      <Banner>导入内容仅属于当前账号，不会修改平台默认配置或其他账号的资源。关联字段只能使用本账号已存在的资源 ID，不支持同批新资源相互引用。</Banner>
      {needsControl && <Banner>只能使用本账号获准的控制模式。省略 control_level 时优先使用 observe（只读观察）；未获准时使用本账号可用的首个模式。定时任务省略 enabled 时按关闭导入，启用前请核实目标、模型与时区。</Banner>}
      <Field label={`${label} JSON 内容`} required hint="只粘贴文本，不支持对话、文件或知识文档导入。凭据只用于写入，请勿向他人分享包含真实密钥的 JSON。">
        <textarea name="json" aria-label="JSON 内容" data-user-import-json={kind} required rows={16} className="mono" spellCheck={false} autoComplete="off" placeholder={JSON.stringify(examples[kind], null, 2)} />
      </Field>
      {(kind === 'servers' || kind === 'providers') && <Banner tone="warning">示例域名和密钥都是占位值，请替换后再提交。仅填写你信任的服务器地址或供应商 URL，以及有权使用的 SSH 凭据或 API Key；供应商导入后可能访问该 URL 同步模型，请先核实其可信性。</Banner>}
      <Banner>服务端会原子校验并新增整批资源；有字段或依赖错误时不会部分写入，请保留并修正 JSON 后重试。成功后的模型同步等提醒不代表导入失败，请勿重复导入。</Banner>
    </FormDialog>}
  </span>;
}
