# EarthAI implementation contract

Stack: React 19 + TypeScript + Vite frontend, Python FastAPI backend, SQLite durable per-user data, encrypted secrets. UI language Simplified Chinese. Base API `/api`; cookies authenticate all routes. Errors `{detail:string}`. All entities IDs strings (uuid), timestamps ISO8601 UTC. Server serves built frontend. No mock successful infrastructure responses.

**本轮（2026-10-29）空间模块与团队空间已通过自动化、浏览器及隔离容器验收。** `ruff check backend scripts tests` 通过；团队 148 + 模块 133 + 备份 4 + schema 1，共 286 项通过，WAL 全套 `1308 passed in 168.02s`、DELETE 全套 `1308 passed in 176.74s`，仅 1 条既有 Starlette/AnyIO 弃用警告。前端 lint、122 项测试（团队 UI 7 项）及构建通过，JS 773.05 KB、CSS 227.22 KB，Vite >500 KB 为非阻塞警告。浏览器 12 项检查、35 项负向断言、10 项布局检查通过；唯一 Compose 校验、镜像无网络临时单目录重建与数据保全检查通过。源码交付位置为 `/home/god-agent/god-agent-workspace/EarthAI-source.zip`。报告、镜像 ID 与验证边界见 [DELIVERY.md](docs/DELIVERY.md)，规则见 [TEAM-SPACES.md](docs/TEAM-SPACES.md)。现机无 production 服务；未访问用户真实 NAS、付费模型或生产基础设施，未部署用户服务。

上一轮目录扩充、多选关联、控制等级授权与用户导入的 Ruff、WAL/DELETE 各 1023 项、前端 lint/115 项/构建、浏览器 7 项及旧库检查均为历史记录，不覆盖团队功能。392 篇是当时隔离实例随机实数，500 篇是候选而非全部落库；旧镜像与源码包记录同样不证明已包含本轮改动。见 [历史说明](docs/CATALOG-CONTROL-UPDATE.md)。

## Auth and profile
- GET `/auth/me` -> User or 401. User `{id,email,name,avatar,theme,control_level,allowed_control_levels,space_modules?:('personal'|'team')[],team_invites_blocked?:boolean}`. avatar string chosen glyph/initials; theme light/dark/system; control observe/approve/autonomous. `control_level` is a preference, not a grant; execution requires the corresponding `allowed_control_levels` membership. `space_modules` is a separate access grant, defaults to `["personal"]` for new accounts and permits `[]`; `team_invites_blocked` is server-managed.
- POST `/auth/register` `{email,password,name}` -> User and session cookie. POST `/auth/login` `{email,password}` same. POST `/auth/logout` -> `{ok:true}`.
- PATCH `/auth/me` `{name?,avatar?,theme?,control_level?}` -> User. `allowed_control_levels`, `space_modules` and `team_invites_blocked` are not user-writable.

## 本轮空间模块与团队契约（2026-10-29，已验收）

### 空间授权与保留数据

- `space_modules?: ('personal'|'team')[]` 是可为空、无重复的精确子集，新注册及管理员新建未指定时默认 `["personal"]`。只有旧数据缺字段才由一次性 `space_modules_v1` 补 personal；显式空数组保留，显式格式坏/非法值拒绝授权，不回退开放。普通 profile PATCH 不可写空间授权；管理员 `/admin/users` 创建、单改及批改可写，批改须显式勾选应用才替换，未应用不改。
- 关闭 personal/team 仅暂停相应访问、隐藏导航并拒绝 API，不删除 entities、个人文件/物理 blob、团队空间或成员关系；重新开启仍可访问原 ID/内容。账号永久删除另行处理，个人文件可删，但团队所有者必须先转交，不能连带删除团队。
- 空间授权、团队成员角色与 `allowed_control_levels` 互相独立；开启 team 或被邀请不授予模型、SSH、控制等级等执行权限，管理员治理也不变成普通用户执行授权。

### 团队角色、成员及生命周期

- 用户入口 `/team-spaces`、管理员入口 `/admin/team-spaces`；团队为独立实体，不属于 default 模板。已启 team 的普通用户可创建自己的空间，只可访问自己是成员的空间；非成员不得读取信息、成员或文件。
- viewer 仅可读基本信息、成员列表及共享文件；editor 可上传、重命名、替换、确认删除团队内全部共享文件，不可管理成员。manager 另可修改空间资料及添加/调整/移除 viewer/editor，不得授予或修改 manager/owner、转交、归档或恢复。owner 可管理 manager、转交、归档/恢复；唯一 owner 不得直接降级、移除或退出。admin 可全局治理并审计，但不成为团队 owner 或运维执行者。
- 添加成员按 `email` 精确匹配已有邮箱/账号，不公开全用户目录，不创建新账号。目标必须是启用、无需强制改密的普通账号，否则拒绝。未启 team 且 `team_invites_blocked` 不为 true 时，同事务将 team 并入当前集合，保留 personal、其他用户数据及 grants；原已启 team 不改。新 personal 用户的阻止标记默认 false。
- 管理员把原已开启的 team 关闭时设置 `team_invites_blocked=true`；邀请和转交不能绕过，返回 409，必须先由管理员重新勾选 team 并清除标记。移除/退出成员不自动关闭 team，也不删除其上传的共享文件。
- 转交目标须为现有活跃普通成员；转交原子更新唯一所有者，原 owner 变 manager。账号停用或模块关闭不移除归属，管理员可转交救援失活 owner；空间若已归档，必须先恢复后转交。
- 空间 DELETE 是 `deleted_at` 软归档，保留成员与文件，owner/admin 可恢复。归档可读基本信息、成员列表，拒绝文件列表/信息/下载/上传及所有文件、成员写入；所有操作者（含管理员）的转交、退出、成员写入与文件写入都须先恢复，不设救援例外。本轮不提供永久 purge。
- 平台删除账号或将其升为 admin 前，对整批账号拥有的空间（含归档）事务预检；任一冲突返回 409，不能部分执行。删除非 owner 账号可级联清理其 membership，团队共享文件仍在、uploader 置 null，不因上传者删号清理团队 blob。

### 文件、Agent 与升级

- 个人文件 API、Agent `list_files/read_file/write_report` 必须检查最新 personal 授权，包括成功写结果缓存复用前；上传在 await 后、落文件前再次检查。关闭后不创建文件、不读取内容、不 unlink，保留原文件 ID/字节。前端隐藏入口不能代替服务端 gate。
- 本轮不新增团队 Agent 工具，不自动把共享文件送入模型，也不允许模型跨团队读取。团队文件全部操作按最新账号、模块、成员角色与归档状态校验；共享文件并非上传者私有文件。
- 启动幂等补建 `team_spaces/team_members/team_files` 及索引，并迁移 `users.data` JSON/`space_modules_v1`；不清用户库、不替换原主钥或密文，不声称支持任意 ALTER。具体列定义以 [teams.py](backend/teams.py) 为准。
- 团队文件物理 blob 平铺于原 `/app/data/uploads/team-<uuid>`；现有 `scripts/backup.py` 的文件 glob 可覆盖。唯一 NAS、唯一 Compose、无 volumes、DELETE/FULL、单 worker 与 root-only 不变，不增加持久盘。

团队 API 完整前缀为 `/api/team-spaces`、`/api/admin/team-spaces`，覆盖列表/创建、详情/修改、软归档/恢复、转交、成员增改删与退出、共享文件上传/读取/重命名/替换/删除；请求方法与后缀以 [team_routes.py](backend/team_routes.py) 为准，精确清单见 [TEAM-SPACES.md](docs/TEAM-SPACES.md#api-清单)。本轮自动化、浏览器及隔离容器持久化验收均通过，报告见 [DELIVERY.md](docs/DELIVERY.md)。

## 上一轮新增契约（2026-10-29，历史验收）

### 目录增补、关联与技能上下文

- 保留原 50 个知识库及每库 2 篇文档；实例首次升级为每库随机追加 1–10 篇有实际正文的运维专题。随机结果与 marker 持久化，仅成功事务提交后生效，重启不重抽、不重复追加；不伪造历史或官方资料。管理员修订/删除不被覆盖或重建，个人 `default_owner_states` 的 `override|deleted` 仍受保护。
- 标准未改目录的技能由 50 项增至 100 项，新增 50 项均有实质运维内容；不为凑数复活删除项，不自动更改现有 agent 绑定，用户可显式全选关联。500 篇候选专题均有正文，但仅按实例首次随机结果选取追加，并非全部落库。本次隔离浏览器实例初始为 100 技能、50 库、392 篇文档（每库 3–12 篇）；392 不代表所有实例或用户生产数据。
- 管理员及用户的智能体、项目表单中，知识库/技能 `MultiSelect` 支持全选、清空及原生 form 提交；操作只影响当前组 enabled 选项，不跨组、不改 disabled 项。
- Project 新增 `skill_ids:string[]`，存于现有 `entities` JSON。真实引擎先按 agent 的 `skill_ids`、project 的 `skill_ids` 顺序合并 ID 并保序去重，再取前 12 个槽位，仅注入其中存在且 enabled 的技能，不从后续列表补足。全选关联不改变此上下文上限；usage 仅记录实际注入资源，同任务去重。

### 控制等级授权

- User 新增 `allowed_control_levels:string[]`，为 `observe`、`approve`、`autonomous` 的非空精确子集，三者无隐含包含关系，`autonomous` 不自动授予 `approve` 或 `observe`。公开注册及管理员新建账号未指定时默认 `["observe"]`；只有旧数据完全缺失字段时兼容原三种，字段存在但为空/格式坏/含非法值则 fail closed，不退回全授权，也不擅自把旧账号降为 observe。
- `control_level` 仅是 profile/会话默认偏好，不产生授权。普通用户无权修改 grants。管理员单改替换完整集合；批改必须勾选“应用控制等级授权”才替换，未勾选不改。空/非法集合使整批拒绝、不部分保存。
- profile/preferences、资源 create/PATCH/import、conversation create/PATCH/messages、关联 agent 校验均受此授权约束。任务模式和关联本地 agent 自身模式都必须被授权，不得把未授权 approve agent 包在 observe 会话或定时任务里绕过检查。服务器/告警诊断固定 observe，仍须显式有 observe 授权。
- engine 创建任务、每轮模型调用、工具执行与审批前后，以及 scheduler 实际派发/手动执行，均读取最新 grants 并复查账号与关联 agent，不信任旧会话、前端状态或启动时快照。
- 未授权模式、带未授权模式的 local agents/schedules 及相应关联选项灰显并禁执行；保留浏览、历史读取和编辑降级的能力，不封禁所有 observe 模块。
- 授权收紧先持久化新集合，再仅取消 run 模式或关联 agent 模式被撤权的活动任务，并令这些任务的待审批项过期；模式仍获授权的活动任务不因集合变化全部取消。已发送的远端操作不能撤销，需核查远端实际状态。

### 用户八类 JSON 原子导入

`POST /{kind}/import`（完整路径 `/api/{kind}/import`），仅限 `agents|skills|knowledge|projects|servers|providers|schedules|alerts`，请求 `{items:object[]}`，每批 1–200 个对象。

- 全量校验通过后，同一事务创建全部实体和审计；任一项非法则整批不落库。只新增当前用户 private 资源，不覆盖、不接收客户端 ID，不支持批内交叉引用；关联只能指向现存 owner 资源或其默认副本，不接受模板 ID/他人资源。create/PATCH 的字段、密钥和授权边界同样适用。
- 供应商密钥密封存储，不在响应、警告或审计输出明文；事务提交后仅做一次模型目录发现。失败以 warnings 告知资源已保存、可重试目录同步，不误报整批未创建或诱导重导。
- schedule 导入的 `enabled` 默认 false，启用、手动执行及后台派发仍受相同等级授权校验。
- conversations、个人 files、知识 documents 不在导入范围。knowledge 仅为知识库元数据，文档仍走现有 multipart 上传，不因 JSON 导入创建正文或索引。

### 启动与 schema 边界

已有初始化用 `CREATE TABLE IF NOT EXISTS` 及索引初始化补建缺失表/索引，不会修改已存在表列，不是任意 `ALTER` 升级框架，也不能保证未来只改 CREATE 语句即可升级旧库。上一轮授权使用 `users.data` JSON 新 key、project 技能使用 `entities` JSON，目录沿用既有表，因此无需 add column；保留旧数据及其他 JSON keys、原密文和主钥。

每次容器 startup 执行幂等 init；目录内容、首次随机结果和 marker 仅随成功事务提交，重启不重抽、不重复追加。一次性 `control_grants_v1` 为缺字段旧账号补齐原三种授权，不覆盖新账号或管理员显式配置，坏字段仍 fail closed。手工五表旧库经完整 TestClient startup 补齐所需表/索引，旧密码哈希、主钥、密文行及管理员改删保留，重启完整快照不变；不清库、不重置统计、不覆盖 `master.key` 或环境主钥。此验收限于上一轮初始化与 JSON 数据迁移，不保证未来任意 DDL 自动升级。完整旧schema lifespan及重启保全、上一轮1023项双日志回归、前端115项及构建均通过；`earthai:latest`已重建并通过断网容器验收。唯一Compose、平台NAS直挂、DELETE/FULL和单worker约束不变。

## 管理与权限扩展（2026-10-27，既有契约）

User 追加 `role:user|admin`、`disabled:boolean`、`must_change_password:boolean`。旧用户缺少角色按普通用户处理。启动创建一次 `admin/admin`，首次强制改密，重启不重置。`POST /auth/password {current_password,new_password}` 改密并轮换当前会话，撤销旧会话；新密码8–256位。公开注册固定 user，个人资料 PATCH 不允许提权。

管理员登录后仅走 `/admin/*`、`/auth/*` 与精确的只读 `/guides` 接口，不能进入用户执行 API；角色/停用/强制改密状态在引擎与调度层再次校验。普通用户不能进入任何 `/admin/*` 接口。

默认资源与用户私有资源分离：七类资源来自 `default_templates`，文档来自 `template_documents`，管理员变更在同一数据库事务内同步仍受模板管理的用户副本，引用按 owner 重映射，副本 ID 保持稳定。`default_template_id` 是来源引用，不等于只读；`read_only` 必须按当前资源类型由服务端计算，不能只信数据库旧标志或前端按钮。

- 用户自己的默认技能、默认知识库及默认 **local** 智能体副本返回 `read_only:false`，允许 PATCH/DELETE；知识库允许上传和删除文档。这些写入只影响当前 owner，不修改模板或其他用户。知识文档全文 GET 仍按 owner 校验；上一轮不新增用户文档正文 PATCH 接口。
- 默认 **remote** 智能体始终 `read_only:true`，可查看和打开链接，但不能编辑或删除；默认 providers/servers/projects/schedules 仍只读，禁止配置 PATCH/DELETE、启停、模型同步写回等修改。私有资源的原 CRUD 和类型转换权限不变。
- `default_owner_states(owner,template_id,entity_id,state)` 以 `(owner,template_id)` 为主键，`state` 为 `override|deleted`。首次个人编辑或知识文档增删后，整份副本及其内容归个人管理，不再合并后续模板内容；没有个人改动的副本继续跟随模板。个人删除留下 `deleted` 墓碑，同一模板 ID 不会因同步或重启复活，管理员创建新模板 ID 则正常下发。
- 管理员删除模板或将模板改为 remote，不删除已有个人 override 的 local 内容，也不改变其 local 类型。来源字段和实体 ID 保留以便引用及统计；依赖 `skill_ids`、`knowledge_ids` 等仍使用当前 owner 的实体 ID，不能提交管理员模板 ID 或其他 owner 的 ID。
- 内容 override 不接管平台排序元数据：副本 `sort_order` 仍跟随平台 rank，用户 `agent_orders` 一旦保存则优先控制个人展示。默认 local 副本（含已 override）不得转为 remote，避免转换后成为锁死的只读副本；服务端拒绝该转换，私有 local/remote 转换保持原有校验。

- `/admin/overview` GET 返回全局 `counts`、`health` 及 `usage:{totals:{agents:number,knowledge:number,skills:number},started_at:string|null,scope:'all_resources',method:'per_run_resource_and_remote_click',description:string}`；`/admin/audit?start&end` GET 全平台最近100条。`counts` 是资源/任务数量，`usage.totals` 是全资源历史使用统计，两者不能互换；默认管理卡的模板副本汇总也不等于概览全量总计。
- `/admin/users` GET/POST，`/{id}` PATCH/DELETE；`/batch` POST `{ids,action:update|delete,changes}`。保护初始admin、当前管理员及最后可用管理员；删除前等待活动任务结束取消清理，撤权与重置密码撤销会话。
- `/admin/defaults/{kind}` GET/POST，`/{id}` GET/PATCH/DELETE，`/batch` POST `{ids,action,changes}`，`/import` POST `{items}`。kind为agents/knowledge/skills/projects/servers/providers/schedules，密钥只写不读。关联仅能指向默认目录。默认任务新建未给enabled按false。
- `/admin/defaults/agents/reorder` POST `{agent_ids:string[]}` -> `{ok:true,count:number}`。仅管理员；在同一事务内校验 ID 全为字符串、无重复、无缺漏、无多余 ID 且集合等于当前全部默认智能体，失效列表整体拒绝，不部分保存。按数组顺序写内部 `sort_order` 并同步用户 rank，不修改指令/内容/类型，不因活动 run 阻止纯排序。无个人 `agent_orders` 的用户跟随，已保存个人顺序优先保留；新增默认智能体追加末尾。管理员 UI 用「调整排序」完整列表提供上下移、drag、保存/取消，不受页面筛选或选择范围影响；创建/编辑表单移除数字排序输入及 `sort_order` payload，内部字段仍存。个人 `/agents/reorder` 不修改平台模板。
- `/admin/defaults/knowledge/{id}/documents` GET/POST `{name,content}`；`/{doc_id}` PATCH/DELETE；`/batch` POST `{ids,action:delete}`。同步仍跟随模板的副本全文和FTS，不覆盖个人 override。
- `/knowledge/{id}/documents/{doc_id}` GET `{id,name,text}`，仅当前用户范围，用于阅读真实全文。
- `/admin/alerts` GET 全员告警含owner_id/owner_email，`/{id}` PATCH/DELETE，`/batch` POST。管理员不发起诊断。
- `/guides` GET 返回登录角色对应的章节数组，字段 `{id,audience,title,summary,icon,sort_order,content,created_at,updated_at}`；普通用户不能通过query切换到管理员指南。
- `/admin/guides?audience=admin|user` GET 管理两套；`/admin/guides/{role}` POST 新章节；`/{id}` PATCH/DELETE，地址标识创建后不可改；`/batch-delete` POST `{ids}` 在同事务校验并批删。Markdown正文安全显示。初始内容存于 `backend/guide_presets.json`，首次写入 `help_guides` 后重启不覆盖编辑、不复活删除。管理员入口 `/admin/guides` 位于帮助页内，不增主导航。
- `/branding` GET 公开品牌配置；`/admin/branding` PATCH整套或部分配置；`/admin/branding/assets` POST multipart file<=2MB，返回站内URL；`/branding/assets/{name}` GET公开安全图片。

主界面使用本地 react-markdown + remark-gfm 支持安全 GFM 表格等，不执行原始 HTML，不自动加载远程图片。管理员导航加入独立 `/admin/team-spaces`；普通用户 `/space`、`/team-spaces` 依模块授权显示。问号链接 `/help` 按角色默认重定向第一节，`/help/:section` 每节独立路由且只挂载一节正文；首次初始化的管理员 11 节、普通用户 12 节并非固定数量，目录搜索只筛选链接，历史和刷新恢复章节。品牌名称/副标题/图标/favicon 及字体字号颜色均可管理，不使用外部字体/图片。

## 全资源调用统计与远程打开（2026-10-28 既有契约；技能口径按上一轮更新）

`GET /admin/overview` 的 `usage` 返回 `totals:{agents,knowledge,skills}`、原有 `started_at`、`scope:'all_resources'`、`method:'per_run_resource_and_remote_click'` 和 `description`。总计统计所有用户的默认及 private 资源，并保留资源或模板删除前的历史；不能通过 join 当前存在的实体/模板缩小总计。删除用户仍清除该 owner 的全部 `resource_usage` 和 `remote_agent_clicks`，包括其已删资源的历史，因此总计可以下降，不是不可回退账本。

`GET /admin/defaults/{kind}` 在 `kind=agents|knowledge|skills` 时每项返回 `usage_count:number`，按记录中的 `template_id` 汇总该模板所有用户副本，智能体卡还包含其远程点击。该卡片范围不是概览的 `all_resources`；private 及已经没有卡片的模板历史仍可计入概览，不能要求卡片和等于总计。用户 `GET /agents`、`GET /skills`、`GET /knowledge` 每项也返回 `usage_count:number`，按当前 owner 与 `resource_id` 汇总单资源，智能体合并本地使用和远程点击；无记录为 0。字段缺失显示暂无统计，不可从任务数或浏览次数伪造。

`backend/usage.py` 保留本地使用的 `resource_usage(owner,run_id,kind,resource_id,template_id,created_at)` 及唯一键 `(run_id,kind,resource_id)`，`INSERT OR IGNORE` 保证同任务同资源去重。`template_id` 是记录当时的来源引用，private 为 null；个人 override 保留默认来源，不抹掉既有统计。资源/模板删除不级联清空这两类历史表。

- 本地智能体在首次发起模型请求时记一次，不要求任务完成或请求成功；没有发起请求的配置失败不算。
- 技能先按智能体、项目顺序合并绑定 ID 并保序去重，再取前 12 个槽位，仅统计其中存在、enabled 且实际注入模型上下文的资源，不从后续列表补足。仅绑定、浏览或启用而未注入不算；全选不改变此上下文上限。
- 知识库仅在检索命中并送入任务参考时计数，包括初始任务参考与任务内 `knowledge_search` 的命中；同任务多篇文档/多次命中同库仍为一次，未命中不算。页面阅读、目录筛选及手工 `/knowledge/search` 不计调用。

### One click 定义与接口

`POST /agents/{ownerAgentID}/open`（完整路径 `/api/agents/{ownerAgentID}/open`）无必需请求体，返回 `{ok:true}`；必须登录，以当前用户副本 ID 查找并校验 owner、`kind:remote` 和 HTTP(S) URL。本地智能体拒绝 422，不存在或不属于当前用户拒绝 404；default remote 的 `read_only:true` 不禁止此打开登记，private remote 同样计数。接口只插入事件，不跳转、不请求目标站点、不创建会话、run 或模型调用；读取列表、详情及 GET URL 不得登记点击。

一次点击是 EarthAI 卡片的一次链接激活所触发且成功落库的一条 `remote_agent_clicks(id,owner,resource_id,template_id,created_at)`。每次 POST 使用独立事件 ID，不按 run、资源或时间窗去重；用户再次激活仍计一次，不沿用 `resource_usage` 的唯一键，也不引入自动重发来假装一次点击成功。

前端使用真实 `<a href target="_blank" rel="noopener noreferrer">`，普通左键、键盘激活及 Ctrl/Meta 点击由 `onClick` 各发一次 POST，中键由 `onAuxClick` 的 button=1 分支发一次，不为右键 button=2 登记，不用额外 keydown 再记一遍。右键菜单「新标签页打开」、复制 URL 后打开、直接访问外部站点不会触发这条上报，不能追踪。浏览器处理导航，登记失败必须 toast 明示且不能增加已确认计数或伪报成功；登记成功也不证明目标站点加载成功、发生模型调用或任务完成。

多轮本地模型推理、重试不重复计数；多个任务分别计数，同任务使用多个不同资源则分别计数。概览智能体统计混合本地 per-run-resource 与远程 per-click，不是供应商请求数、token 用量、成功率或计费数据。`platform_settings.usage_started_at` 首次初始化后保持不变，作为 `usage.started_at` 返回；新表上线不改起点，不推算旧任务或回填旧远程点击。

### Schema 与源码定位

后端启动幂等补建缺失表/索引，新增 `default_owner_states` 与 `remote_agent_clicks` 不清空已有 `resource_usage`，不重置统计起点，不覆盖数据库、原磁盘 `master.key` 或原环境主钥。`CREATE TABLE IF NOT EXISTS` 不会修改已有表列；上一轮无新增列，使用 JSON 新 key 和既有目录表的事务 marker 数据迁移。完整旧库 lifespan 与重启快照保全已验证，范围见上文，不代表通用 ALTER 框架。以下是既有功能源码定位，验收结果见交付记录：

- [access.py](backend/access.py) 的 `read_only` / `writable`：按类型执行用户默认资源写权限。
- [defaults.py](backend/defaults.py) 的 `init_tables`、`mark_personal`、`save_personal`、`delete_personal`、`_sync_user`：来源实体映射、个人状态与模板同步；内容 override 与平台排序元数据分离。
- [main.py](backend/main.py) 的 `public_entity`、`collection`、`open_remote_agent` 及知识文档上传/删除接口：返回权限/来源引用和单资源统计，校验 owner，登记远程 POST。
- [usage.py](backend/usage.py) 的 `initialize`、`record`、`record_remote_open`、`counts`、`resource_counts`、`summary`：两类事件、模板/owner/全量统计及 metadata；[admin.py](backend/admin.py) 删除用户时清理该 owner 的两表记录。
- [admin_routes.py](backend/admin_routes.py) 的 `reorder_default_agents`、[agents.py](backend/agents.py) 与 [store.py](backend/store.py) 的 `list_entities`：平台全量排序、个人 `agent_orders` 优先及展示顺序。
- [WorkspacePages.tsx](frontend/src/pages/WorkspacePages.tsx) 的 `reportRemoteOpen`、`ResourceOrigin`、`AgentForm`，以及 [KnowledgePages.tsx](frontend/src/pages/KnowledgePages.tsx)、[AdminPages.tsx](frontend/src/pages/AdminPages.tsx) 的 `DefaultAgentOrderDialog`、[ResourcePermissions.css](frontend/src/pages/ResourcePermissions.css)：用户交互、来源提示、管理员排序和供应商徽标局部 10px 间距。

个人副本完整规则见 [PERSONAL-RESOURCES-UPDATE.md](docs/PERSONAL-RESOURCES-UPDATE.md)。上一轮验证结果见 [DELIVERY.md](docs/DELIVERY.md)，不将隔离验收当作真实 NAS 或生产部署验证。

## 存储与读取性能边界

本次部署由平台将 `10.53.10.5:/nas` 直接挂载到容器 `/app/data`，这是唯一外部持久化挂载；`earthai.db`、磁盘 `master.key`、`branding/`、`uploads/` 均在该目录直接读写。唯一 `compose.yaml` 设置 `EARTHAI_DATA_DIR=/app/data`、`EARTHAI_SQLITE_JOURNAL_MODE=DELETE`，不设 STATE/UPLOADS 覆盖，服务和顶层均无 `volumes` 定义。无需宿主机 NAS 路径或 NAS 路径变量，不增加挂载、本地状态盘、启动复制或周期异步写回；内存缓存不是唯一数据源。

**Compose 本身无持久化定义，单独执行 `docker compose up` 不提供 NAS 持久化。** 平台导入 Compose、重建和后续升级时，必须在最终部署配置中持续保留原 NAS → `/app/data` 挂载；只有保留该挂载才持久。`docker compose -f compose.yaml config --quiet` 仅校验配置，不验证挂载或运行数据；完整 `config` 输出可能含主钥，只能在受控终端核对。实际挂载须结合平台配置和原数据检查，目录存在或健康检查通过不足以证明。

- `backend/store.py` 保留 `WAL` 兼容能力，当前 Compose 显式使用 `DELETE`；每个物理连接均设置 `synchronous=FULL`，禁止 `OFF` / `MEMORY` 等不安全日志模式，不以关闭 fsync 或同步换性能。旧 WAL 库必须先停所有旧实例，由 SQLite 在新实例启动时切换到 DELETE；不得删除 `-wal` / `-shm` / `-journal` 或裸复制运行中的数据库。
- SQLite 官方 [WAL](https://sqlite.org/wal.html) 不支持网络文件系统，[网络文件访问说明](https://sqlite.org/useovernet.html) 提醒网络锁与同步仍有损坏风险。DELETE 只是规避 WAL 共享内存依赖的缓解，不是网络文件系统安全认证，也不保证任何故障下零丢失；远程 FULL 提交仍可能很慢，不承诺加速。
- 连接池按进程/数据库路径隔离，每次借出独占连接，事务结束清理后归还；不允许并发请求同时共享同一连接。只运行一个 worker、一个写同一数据目录的容器，不横向扩容该 SQLite 目录。
- 用户知识列表和管理员默认知识列表采用批量 `GROUP BY` 统计，避免每项连接和查询。默认模板、用户及同步版本均不变时，`defaults.sync_all_if_needed` 仅 3 条 SELECT、无 DML；这不指整个应用启动。偏好/智能体排序稳态 GET 不取写锁，首次初始化或修复失效引用仍可能写入。
- 前端 API 只合并同一会话代次、同路径的在途 GET，完成即移除，不设 TTL 结果缓存；写请求前后失效映射。SSE 在持久化事件提交后以进程内信号通知，空闲等待及十秒心跳替代 80ms 查询循环，仍按事件游标恢复；通知不跨 worker。cron 在 SQL 中筛选已启用、到期且账号可执行的任务。
- `EARTHAI_MASTER_KEY` 优先于磁盘主钥，必须保留原环境值或原磁盘 key；环境主钥不会归档，须另行安全保管并在每次重建继续提供。当前镜像不含 `scripts/backup.py`；有源码及 NAS 访问权限的维护环境可用 Python 标准库执行该脚本，将 DATA 指向维护容器或平台实际可见的 NAS 根目录、清除旧 STATE/UPLOADS 覆盖，备份写同一 NAS 的 `backups/`。不能假设宿主机有 NAS 路径，不能虚构容器内脚本路径。也可停写后用 NAS 快照；同 NAS 备份不防 NAS 整体损坏，offsite 属于用户策略，不要求新应用挂载。
- 旧默认命名卷不再是当前 Compose 默认配置；历史数据仍在命名卷的其他用户须用旧配置保留原挂载，停写备份并确认迁移后才切换，不能直接以新配置启动而丢弃原卷，不执行 `down -v`。本用户已有原 NAS 直挂，不搬数据。旧 split 路径 API 与 `scripts/migrate_nas_state.py` 仅兼容旧配置，本次不使用；若已有 split，须先确认有效数据库和密钥位置，不能丢弃旧 split 库后启动 NAS 中的旧副本。
- 同一 NAS 数据目录及原主钥重新挂回后可读取已提交记录；执行中任务在进程中断后标记 `interrupted`，不会自动重放有副作用的步骤。此恢复能力仍受 NAS 锁、同步、损坏和备份边界约束。

现有 [nas-performance-verification.json](docs/nas-performance-verification.json) 由 `scripts/benchmark_nas_io.py` 在此前 WAL 隔离环境生成：TestClient、50 库/100 文档、每条 SELECT 人工延时 5ms，等价旧逐项路径至当时接口为 52→3 次查询/连接借用，中位数 287.16→20.11ms；20 次顺序读创建 1 个物理连接。这只是历史模拟，不是 DELETE/NAS 实测或通用加速保证。此前单 NAS 调整的 WAL/DELETE 两种模式分别通过 603 项，包含 21 项单目录/日志恢复专项；更早的 582/71、split 验收及 2026-10-28 的 723/71 项和隔离容器记录也都仅为历史。进程异常退出不等于 NAS 物理断电测试。此前测试、构建及旧库 lifespan、断网单目录容器重建曾验证原数据、主钥和个人状态保留，这些均为历史结果。本轮自动化、镜像构建及无网络临时单目录容器重建检查已通过，原主钥、个人/共享文件与团队状态保留；这些隔离结果不能代替真实 NAS 验证。现机没有运行中的 production 服务，未部署用户实际服务、迁移数据或测量真实 NAS。边界见 [DELIVERY.md](docs/DELIVERY.md)，平台步骤见 [USAGE-NAS-UPDATE.md](docs/USAGE-NAS-UPDATE.md)。

## Dashboard
GET `/overview` -> `{counts:{servers,conversations,runs,files,knowledge,skills,projects,schedules,alerts,providers}, active_runs:Run[], recent_runs:Run[], alerts:Alert[], daily_runs:[{date,count}], recent_audit:Audit[], health:{database,status,version}}`.

## Conversations / runs
- GET `/conversations` -> Conversation[]. POST `{title?,agent_id?,project_id?,server_id?,provider_id?,model?,control_level?}` -> Conversation.
- Conversation `{id,title,agent_id,project_id,server_id,provider_id,model,control_level,created_at,updated_at}`.
- GET `/conversations/{id}` -> `{conversation:Conversation,messages:Message[],runs:Run[]}`. Message `{id,role,content,created_at,run_id?}`. DELETE `/conversations/{id}`. PATCH same fields as create.
- POST `/conversations/{id}/messages` `{content,server_id?,provider_id?,model?,control_level?,agent_id?}` -> Run, starts background task. Fails with 409 for active run. No provider -> actual failed run with setup guidance (never fake AI success).
- Run `{id,conversation_id,status,goal,server_id,provider_id,model,control_level,summary,error,created_at,updated_at,step_count}`. statuses queued/running/waiting_approval/completed/failed/cancelled/interrupted.
- GET `/runs` -> Run[]; GET `/runs/{id}` -> `{run,events:Event[],approvals:Approval[]}`.
- GET `/runs/{id}/events?after=0` SSE; event message `data: JSON(Event)\n\n`. Event `{id:number,run_id,type,data,created_at}`. types status, plan, assistant, tool_start, tool_result, approval, error, done. `data` includes content for assistant; plan `{steps:string[]}`; tool_start `{tool_call_id,name,arguments,risk}`; tool_result `{tool_call_id,name,output,ok}`; approval includes approval fields; status `{status}`; done `{status,summary}`. EventSource auto reconnect support Last-Event-ID. GET run returns persisted events as well.
- POST `/runs/{id}/cancel` -> Run. POST `/approvals/{id}` `{approved:boolean}` -> Approval. Approval `{id,run_id,tool_name,arguments,risk,status,created_at}`.

## Generic entities
GET collection -> array, POST -> entity, PATCH `/{id}` -> entity, DELETE `/{id}` -> `{ok:true}`. Owner scoped. Secret fields are omitted in responses and blank secret in PATCH retains current value. User resources expose server-calculated `read_only` and optional `default_template_id`; default-origin agents/skills/knowledge also expose `personal_override:boolean`. The source reference survives personal changes, while permissions follow the type rules above. User collection items for agents/skills/knowledge include `usage_count:number` (0 when unused).

- `/providers`: `{id,name,base_url,api_key (write only),has_api_key,models:string[],default_model,enabled:boolean,model_sync?:{status,message,count?,synced_at?}}`。新增时 models/default_model 可空；保存配置后只调用一次 GET base_url + `/models`，成功将响应顺序中的首个有效模型设为默认，同步失败/空目录保留配置并返回200与明确的model_sync状态。编辑不自动同步。POST `/{id}/sync-models` -> Provider，手动同步保留仍在目录中的默认；失败保留旧目录。默认管理员供应商同样支持 `/admin/defaults/providers/{id}/sync-models` 并向用户同步。已有GET `/{id}/models`只读、POST `/{id}/test`测试仍保留，自动同步不调用chat/completions。
- `/servers`: `{id,name,kind:'ssh'|'kubernetes',host,port,username,auth_type:'password'|'key',password (write only),private_key (write only),fingerprint, kubeconfig (write only),has_credentials,description,tags:string[],status:'unknown'|'online'|'offline',last_checked_at}`. SSH 默认 `trust_on_first_use:true`，首次实际握手原子固定SHA256指纹，之后换钥拒绝，不自动覆盖；可关闭首次信任并手填独立核实指纹。 kubernetes accepts self-contained kubeconfig with token or embedded client cert/key + embedded CA; no external file/exec credential plugins. POST `/{id}/test` -> `{ok,message,details?}`; POST `/{id}/diagnose` -> `{run_id,conversation_id}` creates a real diagnostic agent conversation with default provider.
- `/agents`: `{id,name,description,kind:'local'|'remote',url,sort_order,system_prompt,icon,color,skill_ids:string[],knowledge_ids:string[],provider_id?,model?,control_level,read_only,default_template_id?,personal_override?,usage_count?}`. Local agent prompt and selected skills/knowledge are injected into the real tool loop; remote agents only expose the external link and click registration. Source fields and sort metadata are server-managed, not user configuration.
- `/projects`: `{id,name,description,color,server_ids:string[],knowledge_ids:string[],skill_ids:string[],status:'active'|'archived'}`. `skill_ids` 已按上文顺序与 agent 技能合并，取前 12 槽位后过滤存在/启用项并真实注入，相关测试通过。
- `/skills`: `{id,name,description,content,enabled:boolean}`. Skill is trusted instruction context, not arbitrary executable uploaded code.
- `/knowledge`: `{id,name,description,document_count,chunk_count}`; GET `/{id}/documents` -> Document[] `{id,name,size,chunk_count,created_at}`; POST `/{id}/documents` multipart `file` uploads and extracts text/md/csv/json/yaml/log/py/js/ts or PDF, indexes local FTS5. DELETE `/{id}/documents/{doc_id}`. POST `/knowledge/search` `{query,knowledge_ids?:string[]}` -> `{results:[{id,knowledge_id,document_name,content,score}]}`.
- `/files`: GET -> File[] `{id,name,size,mime,created_at}`; POST multipart `file` -> File; GET `/{id}/download` -> attachment; DELETE `/{id}`. Files are stored outside web root; owner authorization and the latest personal module grant are required. Disabling personal denies access without deleting IDs or blobs; upload rechecks after await and Agent checks before cached write-result reuse.
- `/schedules`: `{id,name,prompt,server_id?,provider_id?,model?,agent_id?,control_level,cron,timezone:'Asia/Shanghai',enabled:boolean,next_run_at,last_run_at,last_run_id}`; cron e.g. `0 9 * * *`. POST `/{id}/run` -> `{run_id,conversation_id}`. Schedule dispatch real engine, not shell cron. Background resumes after service restart, pending missed runs coalesce once.
- `/alerts`: GET -> Alert[] `{id,title,severity:'critical'|'warning'|'info',status:'open'|'resolved',source,description,server_id?,run_id?,created_at}`; POST create manual alert; PATCH `{status}`; POST `/{id}/diagnose` -> `{run_id,conversation_id}`.
- `/audit`: GET -> Audit[] `{id,action,resource,detail,created_at}`.

## Shared frontend requirements
Create frontend in `earthai/frontend` ONLY. You own entire directory. Do not edit backend/root docs. React Router routes `/chat` + `/chat/:id`, `/overview`, `/agents`, `/space`, `/team-spaces`, `/knowledge`, `/skills`, `/projects`, `/servers`, `/providers`, `/schedules`, `/alerts`, `/settings`, plus the separate administrator `/admin/team-spaces` workbench. Gate `/space` and `/team-spaces` by the corresponding module, hide disabled navigation, and preserve stored data. Login screen if no user. Beautiful polished responsive design, distinctive teal/emerald accent, compact sidebar, cream light theme and midnight dark, real forms/actions, useful empty states, no invented metrics. API fetch credentials same-origin. Vite dev proxies /api to 127.0.0.1:8000. Client global execution store/provider OUTSIDE routes maintains EventSource for active run; reconnect and fetch persisted messages; task dock in sidebar continues across pages. Stream rendering includes plan, tool execution results and approval UI, cancel. Provide `package.json` pinned dependencies, scripts build/lint (tsc); all frontend code should compile. Prefer lucide-react for icons, plain CSS for polished UI (no UI generator). Mark missing infrastructure configuration truthfully. Avatar selection and theme persist via PATCH. App can be deployed same origin with production build. Never render secrets or raw unescaped HTML.
