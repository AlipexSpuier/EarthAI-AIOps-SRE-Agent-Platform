# EarthAI 前端

完整的 React 19 / TypeScript / Vite 单页应用，使用 React Router、Lucide 和原生 CSS。面向同源 FastAPI `/api` 接口，不包含模拟基础设施数据。

**本轮（2026-10-29）空间模块与团队工作台已通过自动化、浏览器及隔离容器验收。** `npm run lint`、`npm test`（122 项，团队 UI 7 项）及 `npm run build` 全部通过；JS 773.05 KB、CSS 227.22 KB，Vite >500 KB 为非阻塞体积警告。浏览器 12 项检查、35 项负向断言、10 项布局检查通过，1366×900／390×844 的用户和管理员界面无水平溢出，目录与详情独立滚动。后端 Ruff、286 项专项及 WAL/DELETE 各 1308 项、唯一 Compose 校验与镜像无网络容器持久化检查通过。源码交付位置为 `/home/god-agent/god-agent-workspace/EarthAI-source.zip`。现机无 production 服务；未访问用户真实 NAS、付费模型或生产基础设施，未部署用户服务。规则见 [TEAM-SPACES.md](../docs/TEAM-SPACES.md)，报告见 [DELIVERY.md](../docs/DELIVERY.md)。

上一轮目录、关联、控制授权和 JSON 导入的前端 lint/115 项/构建、1366px/390px 浏览器 7 项，以及后端各 1023 项和旧库检查，仅为该轮历史证据；733.81 KB 也是当时包大小，不代表本轮产物。

## 本轮空间前后端契约（已验收）

- `User.space_modules?: ('personal'|'team')[]` 新账号默认 `["personal"]`，允许 `[]`；缺字段旧账号由 `space_modules_v1` 补 personal，显式坏值拒绝授权。空间模块与角色、`allowed_control_levels` 分开，普通用户资料不能自授。管理员创建/编辑可配置，批改只有勾选“统一修改开放空间”才提交完整数组，未勾选保持不变；空数组不是错误。
- `/space` 与 `/team-spaces` 分别受 personal/team 控制，关闭时隐藏导航并拒绝直接路由与 API，不请求受限数据。关闭只暂停访问，保留 entities、文件/blob、团队和成员关系，重新开放可恢复；表单须显示保留数据提示，不能混同删除账号。
- 普通用户 `/team-spaces` 与管理员 `/admin/team-spaces` 使用独立团队目录/详情工作台，不走默认资源模板。目录、详情及文件/成员标签页限高、独立滚动，手机上下布局；权限、成员和归档状态变化后撤去失效操作，以服务端校验为准。
- viewer 只读文件、空间信息和成员列表；editor 可上传、重命名、替换及确认删除全部共享文件，不能管成员；manager 还能改空间资料、管理 viewer/editor，不能授予/修改 manager 或 owner、转交或归档；owner 可管理 manager、转交、归档/恢复。管理员全局治理并审计，不因此获得模型/SSH 执行权。团队表单不得显示仅适用于个人资源的提示。
- 添加成员只填写准确的已有邮箱/账号，不开放全用户目录，不注册新账号；目标须为启用且无需强制改密的普通账号。未启 team 且未被平台阻止时自动合并开启，保留 personal 与其他 grants，原已开启则不改。管理员将已开的 team 关闭后 `team_invites_blocked=true`，邀请返回 409，须管理员重新勾选 team 清除；新 personal 用户默认不阻止邀请。
- 删除空间是软归档，文件保留；归档后只读基本信息/成员，拒绝文件访问，owner/admin 可恢复。所有操作者（含管理员）的转交、退出、成员写入与文件写入都须先恢复，前端不得提供绕过入口；不提供永久清理。所有者不能直接退出/降级/移除，转交给现有活跃普通成员后原 owner 变 manager；被平台阻止的目标须先由管理员开 team。成员退出/移除不自动关闭 team，也不删其共享文件。
- 删除账号或升管理员前，对其所有空间（包括归档）整批事务预检，冲突 409 且无部分操作，UI 提示先转交；已归档空间须先恢复再转交。其他成员删号只移除成员关系，共享文件保留且 uploader 变 null；账号停用/模块关闭仍保留所有权，管理员救援同样遵守先恢复后转交。
- 个人文件 API 和 Agent `list_files/read_file/write_report` 读取最新 personal 授权，上传 await 后、写结果缓存复用前仍须检查；关闭后不创建、不读、不 unlink，原 ID 和字节保留。本轮不提供团队 Agent 工具，不自动注入共享文件或跨团队读取。

接口与 schema 的最终字段以 [team_routes.py](../backend/team_routes.py)、[teams.py](../backend/teams.py) 为准，API 清单见 [团队空间说明](../docs/TEAM-SPACES.md#api-清单)。升级幂等补建三张团队表及索引、迁移 JSON marker，不清库、不变原主钥；平铺团队 blob 与既有备份均留在同一 NAS。

## 上一轮前后端契约（已验收）

- 智能体与项目的知识库/技能多选覆盖管理员、普通用户表单，支持原生表单提交。全选/清空仅作用于当前组 enabled 选项，不跨组、不改禁用项。项目新增 `skill_ids`；后端先按智能体、项目顺序合并技能 ID 并保序去重，再取前 12 个槽位，仅注入其中存在且 enabled 的项，不从后续列表补足。全选关联不改变此上下文上限，也不自动把新增技能绑定到智能体。
- 用户 `allowed_control_levels` 是 `observe|approve|autonomous` 的非空精确子集；公开注册和管理员新建默认 `["observe"]`。旧账号缺字段兼容三种，已有坏字段 fail closed；`control_level` 只是偏好，普通用户不能修改授权。管理员单改直接替换集合，批改须勾选“应用”才提交替换集合，空或非法集合全批拒绝；等级不隐含上下包含。
- 未授权模式及带未授权模式的本地智能体、定时任务和关联选项灰显、禁执行；保留浏览、历史和编辑降级，不封禁整个 observe 模块。服务器/告警诊断固定 `observe`，必须有该授权。前端禁用不代替后端校验；即使会话是 observe，也不能调用未获授权的 approve 智能体。收紧授权先持久化，再仅取消任务或关联智能体模式被撤权的活动任务并使审批过期；已发远端操作不能撤销。
- 八类用户资源 `agents/skills/knowledge/projects/servers/providers/schedules/alerts` 对接 `POST /api/{kind}/import {items:[...]}`，每批 1–200 个对象，原子校验、新增及审计；仅创建私有资源，不覆盖、不接受客户端 ID、不支持批内交叉引用，仅引用现有 owner 资源/默认副本。知识导入只建元数据，文档和个人文件仍走 multipart，会话不在导入范围。供应商提交后仅做一次目录发现，失败用 warnings 提示“已保存，可重试同步”，不得诱导重导或展示密钥；定时任务导入默认关闭，创建与执行均受相同模式授权校验。

默认目录保留 50 库及每库原 2 篇文档，首次升级每库随机追加 1–10 篇真实运维专题并持久化结果/marker，重启不重抽，不伪造历史或官方资料。标准未改目录技能从 50 增至 100，新增 50 项均有实质内容；管理员改删和个人 override/deleted 保留，既有智能体绑定不自动扩充。500 篇是候选专题而非全部落库。本次隔离浏览器实例初始为 100 技能、50 库、392 篇文档（各库 3–12 篇），392 不是固定值或用户生产数据。

## 运行与构建

Node.js 22；依赖版本固定，`package-lock.json` 已提交到交付目录。

```bash
export PATH=/home/god-agent/god-agent-workspace/.tools/node-v22.16.0-linux-x64/bin:$PATH
npm ci
npm run dev
npm run lint
npm test
npm run build
```

开发模式将 `/api` 代理到 `http://127.0.0.1:8000`。生产输出为 `frontend/dist`，由后端同源提供静态资源与 SPA 路由回退。此交付不启动长期前端服务器。

## 功能范围

- 账号或邮箱登录、邮箱注册、退出、改密与首次强制改密，会话 Cookie 鉴权；角色与停用状态由后端校验。
- 新建、查看、重命名、删除历史对话；选择真实服务器、供应商、模型、智能体、项目与控制模式。
- 执行计划、工具参数与结果、助手消息、运行详情、风险审批允许/拒绝、停止执行。
- 根级 `ExecutionProvider` 位于路由外：全局运行上下文、后台任务坞、SSE 续传、事件 ID 去重、持久化历史恢复、定时同步及焦点恢复同步。
- 真实概览与趋势、智能体 CRUD、技能指令 CRUD、项目 CRUD 与资源关联。
- 个人文件批量上传、鉴权下载、删除，均受 personal 模块授权；知识库 CRUD、文档索引上传/删除、本地全文检索。
- 团队工作台：用户及管理员独立入口、共享文件/成员标签、四级角色、精确账号邀请、转交与软归档/恢复；不自动给 Agent 团队文件。
- SSH / Kubernetes 服务器 CRUD、真实测试与诊断；OpenAI 兼容模型供应商 CRUD、密钥配置、真实连接测试及模型同步。
- Cron 定时任务 CRUD、启停、立即执行与历史跳转；告警创建、状态处理和 AI 诊断。
- 个人资料、头像文字选择、奶油白/午夜黑/跟随系统主题、默认控制等级持久化。
- 键盘可达的通用模态框、确认删除、错误/加载/空状态、批量文件进度、响应式侧栏与移动端布局。

## 后端对接约定

1. API 基础路径为 `/api`，所有请求使用 `credentials: 'same-origin'`。登录和注册应设置 HttpOnly 会话 Cookie，Cookie 路径需覆盖 `/api`。
2. 集合接口直接返回数组；字段和对象结构遵循上级 `CONTRACT.md`。错误 `{ "detail": "中文说明" }`，也支持 FastAPI 422 字段错误格式。
3. `/runs/:id` 返回 `{ run, events, approvals }`。SSE 为默认 `message` 事件的 JSON 数据，事件带数值 `id`、`run_id`、`type`、`data`、`created_at`。服务端应输出 SSE `id:`，同时支持 `after` 与 `Last-Event-ID`，并禁用代理缓冲。
4. 运行 `updated_at` 与事件 `created_at` 必须为可解析且具有时区的 ISO8601 时间。持久化的运行终态是权威状态；前端不会把终态回退为活动状态。
5. `assistant_delta` 按 `message_id` 增量聚合，终稿 `assistant` 权威替换，不重复拼接；工具按实际时序展示。审批事件包含完整 Approval；`/approvals/:id` 返回处理后状态。停止/服务重启时，应将未决审批标为过期。
6. 控制模式和风险判断只由后端强制执行。前端的禁用按钮与提示不能代替权限检查、CSRF 防护、远程命令安全策略或密钥脱敏。
7. `/servers/:id/test` 和 `/providers/:id/test` 返回真实 `{ ok, message, ... }`；连接失败不作成功提示。SSH 默认 `trust_on_first_use:true`，首次连接自动记录并固定 SHA256 指纹，后续变化拒绝。kubeconfig 只允许独立嵌入式凭据配置。
8. 供应商密钥和服务器凭据为只写字段。读取不得回传明文，PATCH 空值保留旧凭据。目前后端要求供应商 API Key，免鉴权本地服务可输入 `local`。
9. 文件与知识文档通过 multipart 字段 `file` 上传；下载为受认证 attachment。知识库文件不等同个人空间文件，个人空间上传不会自动注入模型上下文。
10. 服务器/告警诊断与定时任务手动执行返回 `{ run_id, conversation_id }`。后端负责创建真实运行并持久化；前端跳转并恢复该运行。
11. 根路径与所有非 `/api`、非静态资源路径应回退到 `dist/index.html`。生产部署不要用缓存代理缓冲 SSE；本交付仅支持一个后端 worker，SSE 的进程内通知不跨 worker，不能将当前 SQLite 布局直接横向扩容。

12. Agent 包含 `kind:local|remote`、`url` 和服务端 `sort_order`；`POST /agents/reorder {agent_ids}` 保存当前用户全量自定义顺序，`agent_orders` 优先于平台排名。远程卡片保留真实 `<a href target="_blank" rel="noopener noreferrer">`，不调用聊天执行 API；每次打开 default/private 远程卡片，向 `/agents/{ownerAgentID}/open` POST 一次，使用当前用户副本 ID 而非模板 ID。普通点击、键盘激活、Ctrl/Meta 点击由 `onClick` 上报，中键由 `onAuxClick` 的 button=1 分支上报，不重复绑定键盘事件；右键菜单直接打开、复制 URL 或直接访问外部站点无法追踪。登记失败用错误 toast 明示，不伪报成功、不提前增加已确认计数，浏览器是否真正打开外站也不能由登记结果证明。不得用 GET 或创建 run 来代替登记。审计 `GET /audit?start=<ISO UTC>&end=<ISO UTC>&limit=100` 保持数组返回。
13. 新增供应商的 `models/default_model` 可为空，后端保存后只同步一次目录；响应 `model_sync.status` 区分成功、空目录、失败或并发过期。成功取返回首模型，失败保留配置并提示，卡片可 `POST .../sync-models` 重试。管理员路径为 `/admin/defaults/providers/:id/sync-models`，用户路径为 `/providers/:id/sync-models`。编辑不自动同步，普通用户的默认供应商仍只读。`ResourcePermissions.css` 仅对 `.provider-card > .provider-card-heading + .ea-resource-read-only` 设置 `margin-top:10px`，不扩大到全局徽标、其他卡片或其他布局。
14. 输入/搜索/密码/选择器移除彩色状态描边但保留原阴影与中性边框；密码使用一枚页面按钮并隐藏浏览器原生重复显示按钮。双主题真实样式测量及23节帮助导航验收见历史 `docs/ui-refinements-verification.json`。

15. 指南由 `GET /guides` 根据登录角色读取动态章节；管理员从帮助页进入 `/admin/guides` 维护两套内容。独立页 `/help/:section` 仍每次只挂载一个章节，初始11/12节并非固定数量。两角色顶栏均展示「使用指南」文字及问号图标。
16. 用户技能库和知识库的目录/正文各自限高并独立滚动；知识库的名称或描述查找仅过滤目录，与当前库全文检索完全分开，筛选不自动切换当前阅读。权限以接口 `read_only` 为准：自己的默认 skills、knowledge 和 local agent 可编辑、删除，知识文档可上传/删除；首次个人写入后整份内容成为个人 override，不再跟随模板内容。显示「系统默认 · 可编辑」或「默认来源 · 已个人定制」等来源说明，不把 `default_template_id` 等同只读。个人修改不反写模板或他人，删除的同模板 ID 副本不会因 sync/restart 复活，新模板 ID 仍正常下发；未改副本继续跟随模板。模板被删除或改为 remote 也保留已 override 的 local 内容/类型。默认 remote 及 providers/servers/projects/schedules 仍只读；默认 local 不能转 remote，私有类型转换不变。平台 rank 仍同步排序 metadata，但保存过的个人 `agent_orders` 优先。详见 [个人资源更新说明](../docs/PERSONAL-RESOURCES-UPDATE.md)。
17. `GET /admin/overview` 的 `usage` 包含 `totals:{agents,knowledge,skills}`、原有 `started_at`、`scope:'all_resources'`、`method:'per_run_resource_and_remote_click'` 和 `description`。后台用三张独立卡展示所有用户默认及 private 资源的历史总使用量，含已删资源/模板历史；`GET /admin/defaults/{kind}`（`kind=agents|knowledge|skills`）每项 `usage_count` 仍是该模板所有用户副本的汇总，范围不同于概览，卡片求和不保证等于总计。用户 `GET /agents`、`GET /knowledge`、`GET /skills` 每项也有 owner 范围的单资源 `usage_count`。接口返回 0 显示 0 次，字段缺失显示「暂无统计」，不从任务数或页面浏览推算。
18. 本地 `resource_usage` 的 `(run_id,kind,resource_id)` 去重不变：本地智能体首次发起模型请求计数；技能先按智能体、项目顺序合并 ID 并保序去重，再取前 12 个槽位，仅统计其中存在、enabled 且实际注入的项，不从后续列表补足；知识库需检索命中并进入任务参考。全选关联不改变此上下文上限。重试/重复命中、页面查看和手工搜索不多计；远程每次成功 POST 独立写入 `remote_agent_clicks`，既不是模型 run 也不代表站外调用成功。删除资源/模板保留历史；删除用户沿用清理其全部 usage/click rows 的规则。原 `usage_started_at`（接口 `started_at`）不重置，不回填旧任务或旧远程点击，不等于任务完成或成功。
19. `src/lib/api.ts` 仅合并同一会话代次、同路径的同时在途 GET，请求完成立即移除；没有 TTL 结果缓存。写请求前后清理在途映射，后续读取仍请求服务端，不能把该优化理解为结果永不过期或所有串行 GET 均被缓存。服务端 SSE 使用持久化事件加进程内通知及十秒心跳，不再每 80ms 空查数据库；前端仍按事件 ID 去重与恢复。
20. 管理员 agents 页新增「调整排序」，对话框始终列出全部默认智能体，不受页面筛选或勾选范围影响。支持拖拽、上移/下移及显式保存/取消，保存 `POST /admin/defaults/agents/reorder {agent_ids}` 并读取 `{ok:true,count}`；服务端原子校验整表，失败时不部分生效。删除创建/编辑中的数字排序输入及其 `sort_order` payload，保留服务端内部排名；新增项追加末尾。平台 rank 同步给没有个人排序的用户，既有个人 `agent_orders` 优先保留；纯排序不修改内容，不因活动 run 阻止保存。
21. 后端每次启动幂等补建缺失表/索引并执行一次性数据迁移，不清库、不清空 usage、不重置起点或覆盖原主钥。上一轮授权使用 `users.data` JSON 新 key，项目 `skill_ids` 使用 `entities` JSON，目录沿用既有表，无需新增列；目录内容、随机结果及 marker 仅随成功事务提交，重启不重复追加或重抽。`control_grants_v1` 为缺字段旧账号一次性补齐原三种授权，不覆盖新账号或管理员显式配置，坏字段仍 fail closed。手工五表旧库的完整 lifespan、哈希/主钥/密文和管理员改删保全及重启快照不变已验证；`CREATE TABLE IF NOT EXISTS` 不会修改已有表列，此验收不代表通用 `ALTER` 框架。前端不能把来源、只读、个人状态或平台排序 metadata 当作普通可写表单字段。

远程 NAS 单目录持久化不改变前端 API 路径：部署平台将 `10.53.10.5:/nas` 直接挂到容器 `/app/data`，数据库、原主钥、品牌及 uploads 均在该目录直接读写，不使用其他持久盘、启动复制或异步写回。唯一 `compose.yaml` 设置 `EARTHAI_DATA_DIR=/app/data`、`EARTHAI_SQLITE_JOURNAL_MODE=DELETE`，服务和顶层均无 `volumes` 定义，无需宿主 NAS 路径变量。**Compose 本身不提供持久化，单独 `docker compose up` 不会获得 NAS 持久化；平台导入和重建后必须在最终配置中继续保留原 NAS → `/app/data` 挂载。** `config --quiet` 只校验配置，不验证挂载成功；完整配置输出可能含主钥，实际挂载与原数据须结合平台配置核验。

每个物理 SQLite 连接保留 `synchronous=FULL`，只运行一个 worker、一个写同目录容器。SQLite 官方说明 [WAL 不适用于网络文件系统](https://sqlite.org/wal.html)，[网络锁和同步风险](https://sqlite.org/useovernet.html) 仍在；DELETE 不能保证物理故障下零丢失或更快。同一 NAS 及原主钥重新挂回后可读取已提交记录，执行中任务中断不自动重放。本用户已有 NAS 直挂，不搬数据；旧命名卷不是当前默认，其他用户须以旧配置保留原挂载，停写备份并确认迁移后才切换，不能直接启动而丢弃原卷。备份需有源码及 NAS 权限的维护环境使用真实可见路径和 Python 标准库，输出到同 NAS 的 `backups/`；当前镜像没有备份脚本，不假定宿主 NAS 路径，也可停写后用 NAS 快照。原访问配置、密钥保留与完整边界见 [调用统计与 NAS 更新说明](../docs/USAGE-NAS-UPDATE.md)；上一轮未部署用户实际服务或迁移数据。

## 验证与限制

本轮 `npm run lint`、`npm test`（122 项，含团队 UI 7 项）、`npm run build` 全部通过；最新 JS 773.05 KB、CSS 227.22 KB，Vite >500 KB 为非阻塞体积警告。后端 Ruff、286 项空间/备份/schema 专项、WAL 全套 `1308 passed in 168.02s` 与 DELETE 全套 `1308 passed in 176.74s` 通过，仅 1 条既有 Starlette/AnyIO 弃用警告。唯一 Compose 校验、`earthai:latest` 构建及扩展无网络容器持久化检查已通过：临时 bind → `/app/data` 在不同容器间保留原主钥、个人/共享文件原 ID/字节、成员及模块/归档状态，未使用真实 NAS 或用户 volume。**浏览器验收通过：** `node tests/team-spaces-browser.cjs` 退出码 0，[team-spaces-verification.json](../docs/team-spaces-verification.json) 为 `ok:true`。Headless Chromium 134.0.6998.35 完成 12 项检查、35 项负向断言、10 项布局检查；1366×900 和 390×844 的 user/admin 均无水平溢出，目录 wheel 350、详情 wheel 420 时各自滚动且外层不动。模块关闭/重开后个人 62 字节、共享 85 字节文件原 ID、名称、内容及 editor 成员保留；完整 CRUD、角色、邀请/平台阻止、归档/恢复、全局管理、转交/退出与删号检查通过。报告的页面错误、站外请求、非预期 HTTP、请求失败、非预期控制台及后端阻止操作列表均为空；另单独记录一次受控导航期间成功 PUT 的预期响应中止，不将其算作零中止。脚本已清理浏览器、测试服务和临时数据。源码交付位置见交付记录，下段数字仅为历史。

上一轮 `npm run lint`、`npm test`（115 项：新增 UI 专项 44 项 + 既有 71 项）和 `npm run build` 通过，0 个编译错误；Vite 主包 733.81 KB 为非阻塞体积警告。`tests/catalog-controls-browser.cjs` 在 1366px/390px 通过 7 项检查，见 [catalog-control-verification.json](../docs/catalog-control-verification.json)：新账号 observe-only、401/403 API 拒绝及模式/关联 agent/schedule 灰显，管理员/用户智能体和项目全选/独立清空，项目真实保存 100 技能及 50 库，八类 JSON 入口及实际技能批量导入，单用户授权后的焦点刷新，批量授权应用开关。页面错误与站外请求均为 0。后端 Ruff、WAL/DELETE 各 1023 项及完整旧库启动/重启保全验收通过。

镜像与源码包状态见 [交付记录最终项](../docs/DELIVERY.md#镜像与源码包最终项)。本轮未访问用户真实 NAS、付费模型或生产基础设施，未部署用户服务。2026-10-28 的 723/71 项及 [personal-resources-verification.json](../docs/personal-resources-verification.json) 等仍为对应轮次历史，完整结果见 [DELIVERY.md](../docs/DELIVERY.md)。

`npm test` 使用 Node test runner、esbuild 和 jsdom，接口/SSE 在测试内桩化；测试桩不会进入生产包。测试覆盖正文 GFM 表格对齐、代码复制、恶意 HTML/URL、图片不自动加载与逐字符流式未完成语法，以及原执行、偏好和 CRUD。

管理员采用独立 `AdminLayout` 与 `/admin/*` 路由，不挂载普通用户执行 Provider；普通用户路由外的执行上下文保留。角色帮助使用 `/help/:section`，每次只挂载一个章节，搜索只筛选目录链接；管理员批量管理、用户角色、完整知识文档、品牌与本地图片均对接真实 API。用户默认资源按类型区分可个人定制与只读，不能再套用「默认全部只读」规则。初始 `admin/admin` 登录后强制改密。

此前使用无头 Chromium 在隔离数据目录完成双角色端到端验收，包括1440px/390px布局、管理员11管理入口、当时的默认发布/同步/只读策略、品牌上传/保存、管理员11模块和用户12模块帮助，详见历史 `docs/admin-browser-verification.json`。该历史验收未调用真实付费模型/SSH，业务连通仍取决于实际配置；其中旧默认只读结论不替代上一轮个人副本规则。

字体 DM Sans/Noto Sans SC、Swagger/ReDoc、图标和JS/CSS均已下载并随构建部署，不依赖公网CDN。Markdown使用固定版本react-markdown与remark-gfm，执行原始HTML或自动加载远程图片仍被禁止。
