# 个人默认资源、远程打开与排序更新

日期：2026-10-28。

本轮五项需求已实现并通过隔离验收。后端 WAL/DELETE 模式各723项、前端71项、类型检查及生产构建通过，`earthai:latest`已重新构建。1366px/390px真实浏览器与断网单目录容器重建验收通过，结果见 [DELIVERY.md](DELIVERY.md)、[浏览器报告](personal-resources-verification.json) 和 [容器报告](admin-container-verification.json)。现机没有production服务，未连接真实NAS、付费模型或生产SSH/Kubernetes，也未部署用户实际服务。

## 用户可以管理哪些默认副本

默认目录仍由管理员维护，每位普通用户拥有自己的实体 ID，`default_template_id` 记录来源模板；智能体关联的技能、知识库等使用当前 owner 的实体 ID，不能使用管理员模板 ID 或其他用户的实体 ID。是否只读由服务端 `read_only` 决定，不以“来自默认目录”一概禁止写入。

| 当前用户的资源 | 个人权限 |
| --- | --- |
| 默认技能 skills | 编辑、启停、删除自己的副本 |
| 默认知识库 knowledge | 编辑、删除自己的副本；上传和删除自己的知识文档，全文读取仍按 owner 鉴权 |
| 默认本地 local 智能体 | 编辑、删除自己的副本；不能转为 remote |
| 默认远程 remote 智能体 | 始终只读，可查看和打开链接，不能编辑或删除 |
| 默认 providers/servers/projects/schedules | 维持只读，不能改配置、删除、启停或同步模型写回等 |
| private 自建资源 | 原有 CRUD、授权和 local/remote 类型转换规则不变 |

默认 local 不能由用户转为 remote，前端固定本地类型，服务端也拒绝该转换，避免修改后落入 default remote 只读规则而锁死。已有个人 override 的 local 同样遵循此限制。私有智能体仍可按既有校验转换类型，活动任务期间的原类型切换限制不取消。

知识文档增删通过现有上传/删除接口完成；本轮不新增普通用户编辑文档正文的 PATCH 接口。管理员仍使用模板文档管理接口维护默认内容。

## 个人修改、删除与同步

后端以 `default_owner_states(owner,template_id,entity_id,state)` 持久化个人状态，主键为 `(owner,template_id)`，`state` 为 `override|deleted`。

- **未修改的副本**继续接收对应模板内容更新，保持稳定实体 ID，并将关联重映射到同一 owner 的实体。
- **首次个人编辑**技能、知识库或 local 智能体，或为默认知识库上传/删除文档，会记录 `override`。从此整份资源内容由个人管理，不再逐字段合并或接收后续模板内容；知识库包括其个人文档与索引。改动不反写模板，不影响其他用户。
- **个人删除**记录 `deleted` 墓碑并删除该 owner 的实体及相关内容。同一模板 ID 不会因同步、重新登录或重启重新出现。管理员创建新的模板 ID 是新资源，仍可正常下发，即使名称相同。
- **管理员删除模板**或把对应模板改成 remote，不删除已有个人 override 的 local 内容，也不把它改成 remote；仍受模板管理的未修改副本按模板变化处理。
- **来源与排序元数据例外**：来源引用保留，个人智能体的 `sort_order` 仍可随平台 rank 更新，这不等于覆盖个人内容。用户保存过的 `agent_orders` 优先控制其展示顺序。

接口对默认来源的 agents/skills/knowledge 提供 `personal_override` 与按类型计算的 `read_only`；界面区分「系统默认 · 可编辑」「默认来源 · 已个人定制」和「系统默认 · 只读」。不能把来源字段、状态或平台排名当作普通可写配置。查看、检索或仅调整个人排序不等于内容 override。

## 远程链接的一次点击

用户通过卡片每次打开 default 或 private remote 智能体，发送无必需请求体的 `POST /api/agents/{ownerAgentID}/open`，成功返回 `{ok:true}`。路径 ID 是当前用户的实体 ID，不是管理员模板 ID。后端校验 owner、remote 类型和 HTTP(S) URL，只写入 `remote_agent_clicks`，不创建会话、模型 run，不请求或代理外站；GET 列表、详情和 URL 读取不得登记点击。

一次点击定义为一次卡片链接激活对应的一条成功落库事件。事件字段为 `id,owner,resource_id,template_id,created_at`，private 的 `template_id` 为 null；每次 POST 使用新事件 ID，不按 run、资源或时间窗去重，重复激活会分别计数。这不是外站模型请求或任务成功证明。

- 保留原生 `<a href target="_blank" rel="noopener noreferrer">`。普通左键、键盘激活和 Ctrl/Meta 点击由 `onClick` 各登记一次；不另绑 keydown 造成重复。
- 中键通过 `onAuxClick` 的 button=1 分支各登记一次；右键 button=2 不登记。右键菜单直接“新标签页打开”、复制 URL 后打开、直接访问外部站点无法追踪。
- 外部导航由浏览器处理。登记失败必须错误 toast，不能提前增加已确认计数或伪报登记成功；即使登记成功，也不能声称目标网页一定打开、外站发生模型调用或任务成功。

## 三种统计范围

| 展示入口 | `usage_count` 或总计范围 |
| --- | --- |
| 管理概览 `GET /api/admin/overview` | 所有用户的默认及 private 资源，包含已删除资源/模板历史；智能体合并本地使用与远程点击 |
| 管理默认 agents/skills/knowledge 卡片 | 依据记录中的 `template_id` 汇总该模板的所有用户副本，包括保留默认来源的个人定制副本 |
| 用户 `GET /api/agents`、`/api/skills`、`/api/knowledge` | 当前 owner 的单个 `resource_id`，智能体同时包含本地使用和远程点击 |

概览 `usage` 包含 `totals:{agents,knowledge,skills}`、原 `started_at`、`scope:'all_resources'`、`method:'per_run_resource_and_remote_click'`、`description`。默认卡片与全量概览范围不同，不能要求卡片求和等于概览总计；private 和已没有管理卡的模板历史仍在全量总计中。用户及管理员三类单资源统计无记录为 0，缺失统计字段显示“暂无统计”，不从任务数或浏览次数推算。

原 `resource_usage` 保持 `(run_id,kind,resource_id)` 唯一键和 `INSERT OR IGNORE`：本地智能体首次发起模型请求计一次；技能只计绑定列表前 12 个位置中已启用且实际注入上下文的项；知识库只计检索命中并进入任务参考的项。同任务多轮、重试和重复知识命中不重复计，页面浏览、目录筛选、手工知识搜索不计。远程独立 click 不进入该 run 去重表。

删除资源或模板不清掉这两类历史记录；删除用户沿用清理其全部 `resource_usage` 和 `remote_agent_clicks` 的规则，包括已经删除资源的记录，因此概览仍可下降。原 `platform_settings.usage_started_at`（接口 `started_at`）保持不变，不从历史 run 推算，不回填旧远程点击；它不是新增远程事件的历史覆盖起点证明。混合统计不是供应商请求数、token 用量、成功率或不可回退的计费账本。

## 管理员默认智能体排序

管理员 agents 页「调整排序」始终列出全部默认智能体，不受页面搜索、类型筛选或勾选范围影响。支持拖拽、上移/下移，显式保存生效，取消放弃当前调整；创建/编辑表单移除数字排名输入和 `sort_order` payload，内部排名字段仍保存。新建默认智能体追加到末尾。

保存接口为 `POST /api/admin/defaults/agents/reorder {agent_ids:string[]}`，返回 `{ok:true,count:number}`。仅管理员可用；后端在同一事务校验字符串 ID、无重复、无遗漏、无额外 ID 且集合等于当前整表，再按数组顺序更新 rank，失效列表整体拒绝，不部分保存。纯排序不改变指令、内容或类型，不因活动 run 阻止保存。

平台 rank 同步到没有个人 `agent_orders` 的用户；已经保存个人顺序的用户仍优先使用个人顺序，不能用管理员排序覆盖。用户原 `POST /api/agents/reorder` 只维护个人顺序，不改变平台模板，内容 override 与排序归属分开。

## 供应商徽标与升级边界

用户供应商卡片仅对 `.provider-card > .provider-card-heading + .ea-resource-read-only` 设置 `margin-top:10px`，不修改全局 badge、其他卡片或全局布局。

`default_owner_states` 与 `remote_agent_clicks` 由后端启动自动幂等建表/升级，不清空已有 `resource_usage`，不重置统计起点，不覆盖原数据库、磁盘 `master.key` 或原环境主钥；无需为升级清库、重装或重新生成密钥。

部署方案不变：唯一 `compose.yaml` 无服务/顶层 `volumes`、无 `EARTHAI_NAS_DIR`。平台将原 `10.53.10.5:/nas` 直接挂到 `/app/data`，数据库、原主钥、品牌与 uploads 同目录直写；不新增 local state、持久盘、额外挂载、启动复制或周期异步写回。Compose 本身不提供持久化，单独 `docker compose up` 不会获得这份 NAS；平台每次重建必须保留原挂载。维持 DELETE、每个物理连接 FULL、单 worker/单写容器及原访问配置；DELETE 不保证真实 NAS 故障下零丢失或更快。更新/备份步骤见 [USAGE-NAS-UPDATE.md](USAGE-NAS-UPDATE.md)。

实现来源定位见 [CONTRACT.md](../CONTRACT.md) 的“Schema 与源码定位”。个人技能/知识库在账号存在活动任务时不能删除默认副本，先停止任务再操作；事务拒绝不写入删除状态。所有验收限隔离数据，不能代替真实NAS或生产连通性验证。
