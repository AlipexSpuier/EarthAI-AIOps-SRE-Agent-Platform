# EarthAI 交付验收

## 交付内容

项目位置：`/home/god-agent/god-agent-workspace/earthai`

技术栈：React 19 / TypeScript / Vite + FastAPI / Python + SQLite / FTS5。

后端从同一端口托管应用，部署地址示例为 `http://服务器IP:8000`，仅在客户端到服务器网络可达时可访问，不是公网域名或正式服务已启动的证明。健康检查为 `/api/health`。本轮团队功能已通过自动化、浏览器及隔离容器持久化验收；源码交付位置为 `/home/god-agent/god-agent-workspace/EarthAI-source.zip`。历史数字不代替本轮证据，当前结果见下文。

初始管理员 `admin/admin` 由启动流程幂等创建，首次强制改密；没有测试密钥。此前 `earthai-earthai-1` 容器更新及数据保留报告是[历史记录](container-management-deployment.json)。现机没有运行中的 production 服务；上一轮未部署用户实际服务或迁移数据，不能将旧健康检查或临时实例报告当作当前部署状态。

## 本轮空间模块与团队空间（2026-10-29，已验收）

规则以 [TEAM-SPACES.md](TEAM-SPACES.md) 与 [CONTRACT.md](../CONTRACT.md) 为准。本轮加入个人/团队模块授权、独立用户与管理员团队工作台、共享文件、四级成员角色、精确账号邀请、所有权转交与可恢复软归档；不增加团队 Agent 工具或永久清理功能。

- 新账号 `space_modules=["personal"]`，允许 `[]`；缺字段旧账号由 `space_modules_v1` 补 personal，显式坏值拒绝授权。普通用户不可自授；管理员创建、编辑和显式应用的批改可调整，独立于执行等级。
- 关闭模块只隐藏入口并拒绝 API，entities、文件/blob、团队与成员保留。邀请可为未被平台禁止的普通账号合并开启 team，保留其他授权；管理员关闭原已开的 team 会设置 `team_invites_blocked=true`，邀请 409，须管理员重新开通。退出/移除不自动关 team、不删其共享文件。
- owner 不能直接离开/降级/移除；转交现有活跃普通成员后原 owner 变 manager。删除账号或升 admin 时，对包括归档的 owned spaces 整批事务预检，冲突 409，无部分操作；其他成员删号只清 membership，团队文件保留、uploader 置 null。账号停用/模块关闭仍保留所有权，可由管理员转交救援；空间已归档时须先恢复。
- 空间删除只写 `deleted_at` 软归档，保留文件；owner/admin 可恢复。归档基本信息与成员只读，拒绝文件访问；所有操作者（含管理员）的转交、退出、成员写入与文件写入都须先恢复，不设救援例外。不自动把团队文件送入模型，不改变模型/SSH/控制等级授权。
- 升级幂等补建 `team_spaces/team_members/team_files`、索引及 JSON marker，不清库、不换主钥。blob 平铺于原 `/app/data/uploads/team-<uuid>`，现有备份 glob 可覆盖；不增加持久盘、挂载或其他 Compose。

### 已完成的核心与自动化验证

- **后端静态检查：** `ruff check backend scripts tests` 通过。
- **空间专项：** 团队 148 项、模块 133 项、备份 4 项、schema 1 项，合计 `286 passed`。
- **后端全套：** WAL 为 `1308 passed in 168.02s`，显式 DELETE 为 `1308 passed in 176.74s`；仅 1 条既有 Starlette/AnyIO 弃用警告。
- **前端：** `npm run lint`、`npm test`（122 项，含团队 UI 7 项）、`npm run build` 全部通过。最新 JS 773.05 KB、CSS 227.22 KB；Vite >500 KB 为非阻塞体积警告。团队专用请求的 403 权限刷新已对齐全局 API，新增覆盖工作台在错误模块/强制改密/停用时不发请求，以及 403 清空详情并触发权限刷新的 2 项用例。
- **部署配置与镜像构建：** 唯一 `compose.yaml` 的 `config --quiet` 校验通过，无服务或顶层 volumes，原平台 NAS 约定未变；`docker build` 构建 `earthai:latest` 成功。配置及隔离容器结果都不验证用户平台的真实 NAS 挂载。
- **扩展无网络容器持久化：** 主代理重跑 `sg docker -c '.venv/bin/python scripts/verify_admin_container.py'`，退出码 0，[admin-container-verification.json](admin-container-verification.json) 为本轮 `ok:true`，并记录 `image_id`、`image_created_at`。root-only、103 份本地字体、50 个智能体/50 个知识库/100 项技能及 DELETE/FULL 检查通过；最终容器样本随机初始 367 篇文档，仅为该隔离实例实数，不是固定规模。
- **不同容器重建保全：** 不同 `docker run --rm` 容器复用同一临时 bind → `/app/data`，原 key 摘要、个人及共享文件原 ID/字节、owner＋manager 成员关系、owner 的 `space_modules=[]` 与 `team_invites_blocked=true`、成员 team 模块和归档状态均保留。管理员无空间模块仍可全局治理并 restore；owner 重开两模块后原文件可读。首次邀请自动开启与管理员显式关闭后 409、owner 删除/升管理员 409 均通过；usage `3/1/1`、个人 override/deleted、品牌及凭据保留。未使用真实 NAS 或用户 volume。

### 浏览器最终验收

`node tests/team-spaces-browser.cjs` 退出码 0，[team-spaces-verification.json](team-spaces-verification.json) 为 `ok:true`。Headless Chromium 134.0.6998.35 完成 12 项检查、35 项负向断言、10 项布局检查。

- 1366×900 与 390×844 下 user/admin 均无水平溢出；目录 wheel 350、详情 wheel 420 独立滚动，外层不动。
- 模块关闭/重开后，个人 62 字节与团队 85 字节文件的原 ID、名称、内容及 editor 成员保留；完整 CRUD、角色隔离、邀请自动开启与平台阻止、归档/恢复、管理员全局治理、转交、退出和删号均通过。
- `pageErrors`、`externalRequests`、`unexpectedHttp`、`requestFailures`、`unexpectedConsole`、`backendBlockedOperations` 均为空。另有一次受控导航期间成功 PUT 的响应中止，已单列为 expected；不宣称所有响应中止或请求事件均为 0。
- 脚本已清理浏览器、测试服务和临时数据。

本轮自动化、浏览器与扩展隔离容器持久化验收均通过。现机无 production 服务；未访问用户真实 NAS、付费模型或生产基础设施，未部署用户服务、迁移数据或做物理断电测试；不承诺 NAS 任意故障下零丢失。

### 镜像与源码包最终项

- **最终镜像：** `earthai:latest` 的本地镜像 ID 为 `sha256:ef389add195b19235940607efdd042949e90a0ae42ebbc06be735ae936171d63`，不是仓库 digest。离线检查确认 37 条团队路由及团队前端；最终扩展容器检查退出码 0、报告 `ok:true`，包含 `image_id` 和 `image_created_at` 证据。临时单目录容器重建通过不等于真实 NAS 验证。
- **源码交付：** `/home/god-agent/god-agent-workspace/EarthAI-source.zip`，由 `scripts/package.py` 生成；包含本轮源码、前端构建、唯一 Compose 和交付文档，排除账号数据库、上传文件、主钥、备份、虚拟环境、测试数据与私有配置。不在本文预写未经计算的 hash、文件数量或包大小。平台升级保留原 NAS 挂载和主钥，不清库。
- **报告说明：** [admin-container-verification.json](admin-container-verification.json) 为本轮最新结果；以下旧数字仅为历史，不作为当前报告快照。

## 上一轮目录与控制授权更新（2026-10-29，历史验收）

功能与接口详见 [CATALOG-CONTROL-UPDATE.md](CATALOG-CONTROL-UPDATE.md)：

- 保留 50 个知识库及每库原 2 篇文档，首次升级每库随机追加 1–10 篇真实运维专题，随机结果与 marker 持久化，重启不重抽，不伪造历史/官方资料。标准未改目录技能由 50 增至 100，新增 50 项均有实质运维内容，既有智能体绑定不自动扩充。管理员改删、个人 override/deleted 保留，不重建凑数。500 篇是有正文的候选专题，不是全部落库。
- 管理员/用户的智能体、项目知识库和技能多选支持原生表单及当前组 enabled 项全选/清空，不跨组、不改禁用项。项目新增 `skill_ids`；引擎先按智能体、项目顺序合并技能 ID 并保序去重，再取前 12 个槽位，仅注入其中存在且 enabled 的项，不从后续列表补足。全选关联不改变此上下文上限。
- `allowed_control_levels` 为三种模式的非空精确子集，新注册/管理员新建默认 `["observe"]`；旧字段缺失兼容三种，坏字段 fail closed，个人 `control_level` 不授予权限，普通用户无权改 grants。管理员单改/勾选应用的批改替换集合，空或非法集合全批拒绝；各模式不隐含包含。未授权模式及关联本地智能体/定时任务禁执行，但保留浏览、历史和编辑降级。诊断固定 observe 且需 observe 授权，服务端入口、引擎各轮、工具/审批前后与调度复查最新授权，不允许 observe 包裹绕过 approve 智能体。收紧先保存 grants，再只取消任务或智能体模式被撤权的活动任务并过期审批，不撤销已发远端操作。
- 八类用户资源支持 `POST /api/{kind}/import {items}`，每批 1–200 个对象，先全量校验，再同事务私有新增及审计，不覆盖、不接客户端 ID、不支持批内交叉引用，仅引用现有 owner 资源/默认副本。知识只导入元数据，文档仍 multipart，会话/个人文件不在范围。供应商提交后仅做一次目录发现，失败返 warnings 不诱导重导，密钥密封且不输出；导入定时任务默认关闭并受相同等级授权校验。
- 上一轮无需新增列：授权使用 `users.data` JSON 新 key，项目技能使用 `entities` JSON，目录沿用既有表；保留旧 keys、数据、密文及原主钥。每次容器启动幂等补建缺失表/索引并执行一次性数据迁移，目录 marker 仅随成功事务提交。此范围不包括自动修改已有表列，也不是通用 ALTER 框架。

### 上一轮验证结果

- **后端全套：** Ruff 通过；默认 WAL 为 `1023 passed in 153.91s`，显式 DELETE 为 `1023 passed in 157.84s`，仅有 `StarletteDeprecationWarning`。
- **后端专项：** 目录 63 项与 schema 1 项共 64 项通过，覆盖不覆盖/不复活、事务、并发及全部 500 篇候选正文；用户导入 116 项在正常 lifespan 下通过；控制授权 120 项通过，包含模型等待期间撤权、仅取消被撤模式、审批与关联 agent 校验、项目技能前 12 槽位、受限 agent 仍可改名及被撤权 schedule 可关闭。
- **前端：** `npm run lint`、`npm test`（115 项：新增 UI 专项 44 项 + 既有 71 项）、`npm run build` 通过，0 个编译错误；Vite 主包 733.81 KB 为非阻塞体积警告。
- **旧库完整启动：** 手工构造仅五表的旧库，经完整 TestClient startup 补齐所需表/索引；旧密码哈希、原主钥和密文行，以及管理员修订/删除均保留。`control_grants_v1` 为缺字段旧账号一次性补齐三种授权，不覆盖新账号或管理员已显式配置的 grants；重启前后完整快照不变。这验证上一轮初始化和 JSON 数据迁移，不保证未来任意 DDL 自动升级。
- **浏览器：** `tests/catalog-controls-browser.cjs` 在 1366px 桌面与 390px 移动端通过 7 项检查，报告为 [catalog-control-verification.json](catalog-control-verification.json)。覆盖新账号 observe-only、401/403 API 拒绝及灰显、关联 agent/schedule 授权、管理员/用户智能体和项目全选/清空、项目真实保存 100 技能与 50 库、八类 JSON 入口及实际技能批量导入、单用户授权后焦点刷新、批量授权应用开关；页面错误与站外请求均为 0。
- **隔离目录实数：** 上述浏览器实例初始为 100 项技能、50 个知识库、392 篇文档，每库 3–12 篇。原 100 篇文档保留；追加结果按实例首次随机后持久化，392 不是所有实例固定数量，也不是用户生产数据。
- **环境边界：** 临时验收服务已停止，现机无 production 服务；未访问真实 NAS、付费模型或生产基础设施，未部署用户服务、迁移其数据或进行物理断电测试。

### 上一轮镜像与源码包（历史）

[admin-container-verification.json](admin-container-verification.json) 报告路径现用于最新轮，以下旧数仅历史，不能把当前文件视为旧轮报告快照。

- 当时的 `earthai:latest` 按该轮代码构建并通过断网容器验收，默认目录为 50 个智能体、50 个知识库、100 项技能；该容器实例首次随机共 403 篇文档、每库 3–12 篇，与浏览器 392 篇是不同隔离样本，不是固定或生产数量。
- 当时验证过 root-only、本地字体、初始改密、DELETE/FULL 和临时单目录容器重建后数据/主钥保留，未挂载用户数据或真实 NAS，未覆盖本轮团队功能。
- 当时由 `scripts/package.py` 更新的 `/home/god-agent/god-agent-workspace/EarthAI-source.zip` 包含该轮源码、唯一 Compose、前端产物和说明，排除账号数据库、上传、主钥、备份、虚拟环境和私有配置。该轮完整性通过不代表本轮新包已完成。

## 2026-10-28 功能更新与验收（历史）

当时五项需求已实现并通过隔离验收：

1. **远程打开登记。** default/private 远程智能体每次通过卡片激活链接，`POST /api/agents/{ownerAgentID}/open` 独立写入 `remote_agent_clicks`，不创建模型 run，不在 GET 中计数。左键、键盘、Ctrl/Meta 和中键分别由 `onClick` / `onAuxClick` 正确登记；右键菜单直接打开、复制 URL 或直接访问外部站点无法追踪。登记失败错误 toast，不伪报外站打开或计数成功。
2. **全资源历史统计。** 原 `resource_usage` 的 per-run-resource 去重不变；概览统计所有用户默认及 private 资源，保留资源/模板删除前的历史，metadata 为 `scope:all_resources`、`method:per_run_resource_and_remote_click`。默认管理卡仍按模板来源汇总，与全量概览范围不同；用户 agents/skills/knowledge 单项也返回 `usage_count`。原 `started_at` 不变、不回填旧远程点击；删用户仍清理其全部 usage/click rows。
3. **个人默认副本。** 用户可编辑/删除自己的 skills、knowledge、默认 local agent 副本，知识文档可增删。`default_owner_states` 的 `override|deleted` 保证个人改动不反写他人/模板、整份内容脱离模板管理、同模板 ID 删除不复活，新模板 ID 仍下发，未改继续同步。模板删除或改 remote 不覆盖已有个人 local 内容/类型；排序 metadata 仍跟平台 rank，个人 `agent_orders` 优先。默认 remote 及 providers/servers/projects/schedules 仍只读，用户不可将默认 local 转 remote，private 转换不变。
4. **供应商卡片间距。** 用户 provider-card 标题后的只读徽标局部 `margin-top:10px`，不修改全局徽标或其他卡片间距。
5. **管理员智能体排序。** 「调整排序」使用完整默认智能体列表，上下移动或拖拽后保存/取消，不受过滤或勾选范围限制。`POST /api/admin/defaults/agents/reorder {agent_ids}` 原子校验整表、返回 `{ok:true,count}`；移除数字排序输入及表单 payload，内部 `sort_order` 保留。没有个人 order 的用户跟随平台 rank，个人 order 优先；排序不修改内容，无需因活动 run 阻止保存，新增默认智能体末尾追加。

当时启动幂等补建缺失表/索引，不清空已有 usage 数据、不重置统计起点、不覆盖原主钥；这不代表会自动修改已有表列。完整接口见 [CONTRACT.md](../CONTRACT.md)，个人副本规则见 [PERSONAL-RESOURCES-UPDATE.md](PERSONAL-RESOURCES-UPDATE.md)，统计与存储见 [USAGE-NAS-UPDATE.md](USAGE-NAS-UPDATE.md)。

### 2026-10-28 验收汇总（历史，不代表本轮）

- `ruff check backend scripts tests` 通过；`.venv/bin/python -m pytest -q`：723 项通过；`EARTHAI_SQLITE_JOURNAL_MODE=DELETE .venv/bin/python -m pytest -q`：723 项通过，仅有 Starlette/AnyIO 既有弃用警告。
- `npm run lint`、`npm test`（71 项）、`npm run build` 通过。Vite 保留主包超过 500KB 的非阻塞提示，无编译错误。
- 新专项包括远程与本地 usage 共 74 项、管理员排序 40 项、个人默认资源 34 项；覆盖鉴权、防伪、并发逐次点击、全量历史、事务回滚、owner 隔离、个人状态同步/重启保全和活动任务删除保护。
- [personal-resources-verification.json](personal-resources-verification.json)：隔离 Chromium 在1366px/390px完成五项需求联调。真实默认及 private 本地任务使三类总计各加1；默认远程四种激活及 private 远程共5次打开登记后智能体总计为7；双 owner 编辑/删除/再同步隔离、10px供应商徽标间距、管理员全量排序与无数字输入通过，页面错误与站外请求均为0。
- 当时 `earthai:latest` 已重新构建，并完成断网临时单目录挂载、删除原容器后创建新容器的检查，验证原主钥、账号/聊天/文件/品牌、两次远程点击与个人 override/deleted 状态保留，DELETE/FULL 及 root-only 约束通过。旧报告数字仅为历史；报告路径现用于最新轮，本轮镜像与扩展隔离容器持久化检查均已通过，旧报告数字不代替本轮结果。
- 当时唯一 Compose 配置校验通过，不新增数据卷或挂载，平台仍负责原 NAS → `/app/data`。当时源码包为 `/home/god-agent/god-agent-workspace/EarthAI-source.zip`，由 `scripts/package.py` 更新并排除账号数据、备份、主密钥和私有配置，不证明已包含上一轮改动。
- 当时全部数据操作限隔离环境；没有使用真实 NAS、付费模型或生产 SSH/Kubernetes，也未部署用户实际服务或迁移其数据。

## 保持不变的部署约束（平台管理 NAS 挂载）

唯一部署文件为 `compose.yaml`，设置 `EARTHAI_DATA_DIR=/app/data`、`EARTHAI_SQLITE_JOURNAL_MODE=DELETE`，不设 STATE/UPLOADS 覆盖，服务和顶层均无 `volumes` 定义。部署平台直接将 `10.53.10.5:/nas` 挂到容器 `/app/data`，这是唯一外部持久化挂载；无需宿主机 NAS 路径或 NAS 路径变量，不额外挂载，不做 split、本地 state、启动复制或周期异步写回。

**Compose 本身无持久化定义，单独执行 `docker compose up` 不会获得 NAS 持久化。** 平台导入 Compose、重建和以后升级时，必须在最终部署配置中持续保留原 NAS → `/app/data` 挂载，只有该挂载保留才持久。平台存储及原数据需实际核验，目录存在或健康检查成功不证明挂载正确。

- 数据库、原磁盘主钥、品牌及 uploads 均直接读写平台挂载的 NAS；内存缓存不是唯一数据源。本用户已有原 NAS 直挂，不搬数据。
- root、非 privileged、原安全约束、端口与 `earthai:latest` 标签不变；单 worker、单个写同目录容器。每个物理 SQLite 连接保持 FULL，不关闭 fsync 或持久化同步，DELETE 不消除 NAS 锁/同步或物理故障风险。
- 旧默认命名卷不再是当前默认。其他用户若数据仍在命名卷，须用旧配置保留原挂载，停写备份并确认迁移后才切换，不能直接启动而丢弃原卷，不执行 `down -v`。
- 停写、停全部旧写入者并备份后，通过平台导入唯一 Compose、保留原存储和访问配置及原主钥，再由平台启动并核验原账号、凭据、会话/统计、文件与品牌。不提供未经确认的平台命令或 NFS driver 配置。
- `docker compose -f compose.yaml config --quiet` 仅校验 Compose 配置，不验证 NAS 挂载、持久化或运行状态。完整 `config` 输出可能含主钥，只能在受控终端核对；运行检查依赖平台最终部署配置和原数据。
- 当前镜像不含 `scripts/backup.py`。需有源码及 NAS 权限的维护环境，用其容器或平台实际可见的 NAS 路径执行 Python 标准库备份，清除旧 STATE/UPLOADS 覆盖，输出到同 NAS 的 `backups/`；不假设宿主机有 NAS 路径，也可停写后用 NAS 快照。环境主钥另行安全保管；同 NAS 备份不防 NAS 整体损坏。

唯一平台更新流程及完整备份边界见 [USAGE-NAS-UPDATE.md](USAGE-NAS-UPDATE.md)。

### 上一轮平台 NAS 配置验证（历史，不代表本轮）

- 当时 `ruff check backend scripts tests` 通过，WAL 与显式 DELETE 环境全量各 603 项，21 项单目录专项通过，仅有既有 Starlette/AnyIO 弃用警告。这些不是上一轮新增功能的测试结果。
- 当时唯一 `compose.yaml` 解析通过，无服务/顶层数据卷、无 NAS 宿主路径变量，DATA 为 `/app/data`、日志为 DELETE；此处保留历史，不声称上一轮重新执行校验。
- 当时容器检查静态核对 Compose 将挂载交由平台，并用隔离临时目录模拟外部挂载、删除首个容器后创建新容器验证原数据/密钥保留；没有使用用户数据或实际平台/NAS。报告路径现用于最新轮，这些旧检查说明仅为历史。
- 当时只改配置与说明，沿用已支持 DELETE/FULL 的旧镜像并更新源码包；「无需重新构建」只适用于当时，不能用于本轮正在修改应用的场景。`/home/god-agent/god-agent-workspace/EarthAI-source.zip` 也是历史打包产物，不宣称已包含上一轮全部改动。

以下结果保留为历史证据，不代表本轮测试、镜像或真实平台部署已完成。

## 上一轮单 NAS 隔离验收（历史）

- 当时 `ruff check backend scripts tests` 通过；默认 WAL 与显式 `EARTHAI_SQLITE_JOURNAL_MODE=DELETE` 下全量测试分别为 603 项通过，仅有 Starlette/AnyIO 既有弃用警告。其中 21 项单目录专项覆盖并发新连接 FULL、非法日志拒绝、原 WAL 转换、独立进程重开和热回滚日志恢复；进程异常退出不是 NAS 物理断电测试。
- 当时构建的 `earthai:latest` 支持 DELETE/FULL，镜像内前端生产编译及单目录容器检查当时通过，未使用用户 NAS 或数据目录。报告路径现用于最新轮，此处旧结果不覆盖本轮扩展容器持久化检查，也不能证明实际平台保留挂载。
- 当时的 Compose 配置校验、临时目录 bind 和容器重建记录不验证当前平台部署；前端 71 项测试及浏览器统计报告同属历史。上一轮未部署用户实际服务、迁移数据或测量真实 NAS。

## 更早的统计与双盘方案验收（历史，不代表本轮）

- 上一轮 `ruff check backend scripts tests`、`pytest -q`：582 项通过，包括 29 项统计及 41 项存储/SSE 专项；有 Starlette/AnyIO 既有弃用警告。
- 上一轮 `npm run lint`、`npm test`（71 项）、`npm run build` 通过；Vite 有主包超过 500KB 的非阻塞提示。
- 历史 Chromium 1366px/390px 统计与管理卡验收见 [usage-browser-verification.json](usage-browser-verification.json)，运行错误和站外请求均为 0。
- 更早一轮做过 split 路径和同进程重启检查；该双盘方案不符合当前唯一 NAS 约束，已不作为部署方案。其后改为单目录、不同容器删除重建的隔离检查；这些描述仅为历史，容器报告路径现用于最新轮，不据此证明实际平台挂载。
- 当时 Compose 校验与 SSE 终态尾部补发、断开连接不取消任务、2106 条持久化事件跨批次重连均有通过记录；不代替上一轮测试。

以下自动化与浏览器段落也仅保留为对应功能的历史证据。

## 历史自动化记录

- 既有后端 `ruff check backend tests scripts`、`pytest -q` 有通过记录；不在此复用旧通过数量作为上一轮结果。此前有 Starlette/AnyIO 上游弃用警告。
- 既有前端 `npm test`、`npm run lint`、`npm run build` 有通过记录；此前主包超过500KB产生Vite性能提示。
- 历史部署 YAML 可解析；`start.sh` shell 语法检查通过。
- 历史镜像曾完成 root-only、无网络本地静态资源、默认管理员及单目录容器重建检查；报告路径现用于最新轮，此处旧结果不替代本轮扩展容器持久化验收，也不证明正式服务已启动。
- 既有无公网静态资源验收记录包括登录注册、12 个管理路由、两种字体、Swagger/ReDoc 和移动端，见 `docs/local-static-verification.json`。

## 此前已验证的执行行为

1. 注册、登录、退出、用户资源隔离、配置保存与更新。
2. 密码 scrypt 哈希、凭据 Fernet 密文落库、密钥不回显。
3. 多轮模型工具调用，计划事件、个人空间查询、真实 Markdown 报告文件生成。
4. 审批前不执行，批准后继续，拒绝后该任务其他变更也被阻断。
5. 只读模式拦截变更，高风险与未知 SSH 命令即使在自主模式也需审批。
6. SSE 持久化事件、游标恢复、去重，页面切换继续执行。
7. 任务取消、SSH 握手期间取消后不再发送命令、服务重启标记 interrupted 而不重放变更。
8. 真实本地 SSH 协议握手、密码认证、SHA256 主机固定校验、退出码和输出读取。连接到受控测试服务，不是生产 SSH 服务器。
9. 真实本地 HTTPS Kubernetes API 协议测试，验证 CA、Bearer 认证、资源读取、日志、扩容 PATCH、Server-side Apply 请求。连接到受控测试服务，不是实际 Kubernetes 控制平面。
10. 服务器连接测试期间凭据轮换不会被旧测试结果覆盖。
11. 文件上传/鉴权下载、知识文本索引、中英文检索、项目关联。
12. cron 下次时间计算、手动触发同一 Agent 引擎、告警状态与概览审计。

## 真实浏览器验收

独立 Chromium，1440px 桌面与 390px 移动端，使用独立 SQLite 数据目录和本地 OpenAI-compatible 测试服务。测试模型服务仅用于验收，不进入应用正常对话路径，也未写入交付数据库。

- 浏览器注册与登录完成。
- 从表单填写供应商 URL、API Key、模型并保存，真实 HTTP 连接测试通过。
- 发出自然语言目标后立刻切至概览，后端完成 4 轮调用和 3 次工具执行。
- 浏览器刷新后恢复会话与执行记录。
- Agent 写入的 Markdown 文件在个人空间可见，鉴权下载内容正确。
- 所有管理路由连接真实后端，无 JavaScript 运行时异常。
- 头像标识和深浅主题保存到账号。
- 1440px 桌面及 390px 移动端无水平溢出，移动侧栏可导航。

详细机器可读结果：`docs/browser-verification.json`。

界面截图：`docs/earthai-chat-dark.png`、`docs/earthai-chat-light.png`、`docs/earthai-overview-dark.png`。

## 界面优化更新

已将账户与偏好设置收敛为侧栏单一入口，各管理页创建按钮去重；智能体、项目、服务器、模型和控制等级统一为贴近按钮的自定义浮层。新对话在 1920×1080 到 360×640 的八种视口、100% 缩放下均无多余滚动。长列表和文档保留正常主内容纵向滚动。具体说明见 `docs/UI-IMPROVEMENTS.md`，测量结果见 `docs/ui-verification.json`。

## 资源与交互完善更新

此前资源扩充保留原有实体及供应商配置；更早新账号默认10/10/10与20份手册，2026-10-28 的标准目录基线为50个智能体/50项技能/50个知识库、100份手册。此次在保护管理员改删与个人状态的前提下，标准未改技能增至100，每库原文保留并随机追加1–10篇；本次隔离实例初始392篇的含义见本页上一轮结果。历史正式库计数不代表本轮生产数据，上一轮未访问或更改正式数据库。既有输入框、登录注册及供应商选择改进见 `docs/ENHANCEMENTS.md`、`docs/enhancement-verification.json`。

## 流式输出与执行轨迹更新

模型请求现已真正开启 `stream:true`，公开正文到达前端早于生成结束；工具步骤按时间顺序默认展示目标、目的、命令/参数、实时输出、审批、退出码与耗时。响应解析兼容工具分片、内容块及旧式调用，真正空响应有界重试一次，拒答、长度截断和断流不执行残缺调用。上游只返 JSON 或拒绝 SSE 时明确说明，不伪造流式。详情见 `docs/STREAMING.md`，浏览器原始结果见 `docs/streaming-verification.json`。

## 可靠性与持久配置更新

已按官方Cline/Roo Code实现核对引入分类有限重试、参数校验反馈、工具筛选、结果配对与无进展熔断。当前供应商/模型经真实只读验收可记住兼容控制协议，正常审批不放松。六项聊天配置即时保存到账号；退出账号/关闭浏览器后任务继续执行并可恢复进度已通过真实浏览器验收。详情见 `RELIABILITY.md`、`LIVE-RESULTS.md` 与 `persistence-verification.json`。

## 智能体管理、SSH 信任与审计更新

创建/编辑智能体可选本地或远程；远程仅打开网页，不进入本地执行器。智能体支持拖拽及上下移动后保存顺序，新增追加在末尾，编辑不会改变排名。SSH 新连接默认首次自动固定指纹，之后指纹变化仍拒绝连接；首次信任不能排除首次连接的中间人风险。审计日志支持预设或自定义起止时间，并由后端按账号及时间筛选。favicon、Apple Touch 图标及 manifest 已补齐。功能和移动端真实浏览器验收通过，详情见 `docs/MANAGEMENT-UPDATE.md` 与 `docs/management-verification.json`。

## 局域网静态资源本地化

DM Sans 与 Noto Sans SC 完整 103 个 WOFF2 子集、Swagger UI、ReDoc 脚本及 CSS、内置 Logo、网站图标均已随项目提供，不再通过 Google Fonts 或 CDN 加载。Swagger 在线校验器已关闭，ReDoc 不加载 Google 字体；保留模型、SSH/Kubernetes 和远程智能体等功能性连接。完整字体和资源许可证、来源、校验摘要随包提供。验收见 `docs/LOCAL-STATIC.md` 与 `docs/local-static-verification.json`。

## 管理后台、五十套默认资源与 Docker 要求

该管理后台更新的历史内容包括默认admin首次改密、管理员独立11管理模块、用户角色与批量、七类默认模板及全员同步、当时的普通用户默认只读策略、所有告警、角色化详细帮助，以及系统名称/副标题/字体字号颜色/图标/favicon管理。旧的「默认全部只读」仅描述当时验收，不是上一轮规范；上一轮 skills、knowledge 和 local agent 可个人定制/删除，其余只读边界见本页顶部。Markdown正文使用安全GFM表格渲染。默认资源各50项及100篇手册在当时验收中真实索引，50领域逐项检索通过。受限账号撤权时取消全部活动任务并等待退出，避免删除后回写；旧同大小但不同正文的手册保留。

Docker运行时仅root账号/组，USER root，Compose user 0:0，监听及端口映射0.0.0.0。原配置没有privileged字段，未新增，默认仍为非特权；保留no-new-privileges与必要最小capabilities兼容旧数据卷。历史镜像构建及无网络单目录检查不证明平台部署；容器报告路径现用于最新轮，不再作为旧轮快照引用。此前完整双角色浏览器验收仍见 `docs/admin-browser-verification.json`，功能说明见 `docs/ADMIN-UPDATE.md`。

## 帮助分页、输入焦点与供应商自动同步更新

保留原始管理员11节、用户12节完整内容作为首次初始化，后续数量由管理员维护，均为独立 `/help/:section` 页面，仅挂载当前章节，支持目录/搜索/上下节以及刷新和前进后退。全站输入与搜索的彩色焦点轮廓及变色边框已移除，原有阴影不变；登录注册密码仅保留页面一枚切换按钮，并隐藏重复的浏览器原生显示按钮。管理员与用户新增供应商均可不填默认模型和列表，保存后只请求一次模型目录，成功取首个模型作为默认，失败/空目录保留配置并显示状态，支持重试。编辑不自动同步，手动同步保留仍有效的默认模型。深浅主题、双角色、390px、真实本地目录同步及失败分支已浏览器验证，结果见 `docs/ui-refinements-verification.json`，说明见 `docs/UI-REFINEMENTS.md`。

## 双区工作台、可维护指南与 latest 镜像

用户技能库和知识库目录/详情已按可用高度限高并独立滚动，手机为上下两区；知识库名称/描述查找位于本地索引说明旁，与当前库全文检索分离，筛选不自动换库。两角色顶部均显示问号与「使用指南」文字。管理员从指南页集中进入双角色章节管理，支持增删改、预览、搜索、排序字段与批删，正文存SQLite并只首次初始化完整23章，重启保留管理结果。普通用户只能读取自己角色，独立章节阅读继续保留。

该次更新的自动化检查与1440/1024/390px、多目录长正文/35份文档独立滚动、双角色指南真实CRUD均有通过记录。Compose、构建核验、升级脚本统一 `earthai:latest`，历史镜像构建及断网冒烟记录不代表本轮已更新镜像，也不是当前运行服务证据。说明见 `docs/LIBRARY-GUIDES-UPDATE.md`，原始结果见 `docs/library-guides-verification.json`。

## 全资源调用统计与 NAS 更新

- 上一轮 `resource_usage` 继续以 `(run_id,kind,resource_id)` 去重，远程打开则独立写入 `remote_agent_clicks`。概览包含所有用户默认/private 及已删除资源/模板历史；默认管理卡仍为模板副本汇总，与全量概览范围不同。用户三类目录也返回单资源 `usage_count`；删除用户仍清其全部 usage/click rows。
- 本地智能体首次发起模型请求记一次；技能先按智能体、项目顺序合并 ID 并保序去重，再取前 12 个槽位，仅统计其中存在、enabled 且实际注入的项，不从后续列表补足，全选关联不改变此上下文上限；知识库需命中并送入任务参考。同任务重试/重复命中去重，页面浏览或手工检索不算。default/private 远程卡片每次成功 POST 独立计一次打开登记，不进入 run，不伪称站外调用；原 `usage_started_at` / `started_at` 保持，不回填旧任务或旧远程点击。
- 数据库连接按进程/路径隔离并独占借出，知识列表用 `GROUP BY` 批量计数；默认目录同步在无变化时仅 3 条 SELECT、无 DML（不是整个启动仅 3 条查询）；偏好/排序稳态 GET 不取写锁。前端仅合并在途 GET、无 TTL 结果缓存；SSE 使用进程内通知及十秒心跳，不再每 80ms 空查；cron 用 SQL 筛选到期任务。上述优化全部保留，不关闭 fsync/持久化同步、不增加 worker。
- [nas-performance-verification.json](nas-performance-verification.json) 是上一轮 WAL 隔离 TestClient 模拟：50 库/100 文档、每条 SELECT 人工延时 5ms，等价旧逐项路径与当时接口为查询/借用 52→3，中位数 287.16→20.11ms；20 次顺序读创建 1 个物理连接。不是上一轮 DELETE/NAS 实测、通用加速保证或提交性能证据，远程 FULL 提交仍可能很慢。
- 唯一 Compose 不定义持久化，平台须在最终配置及每次重建保留原 `10.53.10.5:/nas` → `/app/data`，无需宿主 NAS 路径或额外挂载，不能以单独 `docker compose up` 获得 NAS 持久化。本用户已有 NAS 直挂，不搬数据；旧命名卷不再默认，其他用户须用旧配置保留原卷、备份并确认迁移后才切换。旧 split API/脚本仅兼容，本用户未做 split；若已有 split 须先确认有效数据库/主钥位置，不能丢弃旧库后启动 NAS 的旧副本。
- SQLite 官方 [WAL](https://sqlite.org/wal.html) 不支持网络文件系统，[网络文件访问说明](https://sqlite.org/useovernet.html) 仍提示锁/同步风险。单 NAS 使用 DELETE、每个物理连接 FULL；旧 WAL 库停全部旧实例后由 SQLite 切换，不能删 WAL/SHM/journal 或裸复制运行中的库。单 worker、单写容器不等于 NAS 安全认证。
- 保留原环境主钥或磁盘 key，环境主钥不归档。当前镜像没有备份脚本，须在有源码和 NAS 权限的维护环境用 Python 标准库执行 `scripts/backup.py`，DATA 指向容器/平台实际可见的 NAS 路径，清除旧 STATE/UPLOADS，BACKUP 指向同一 NAS 的 `backups/`；不假定宿主 NAS 路径，也可停写后使用 NAS 快照。NAS 整体损坏可能同时丢失原数据与备份，offsite 由用户策略安排，不新增应用挂载；未部署用户实际服务。

## 尚未验证及明确限制

- 本轮 Ruff、286 项专项、WAL/DELETE 各 1308 项、前端 lint/122 项/构建、Compose 校验、镜像构建、浏览器及隔离容器持久化验收均通过；结果仅覆盖隔离环境，不代表用户生产服务或真实 NAS 验证。

- 标准未改目录为 50 个智能体、100 项技能和 50 个知识库，原每库 2 篇文档保留并各随机追加 1–10 篇；管理员/个人改删受保护，因此不以标准数量要求重建资源。本次隔离实例初始 392 篇不是用户生产实数或固定规模，500 篇候选不等于全部落库。
- 上一轮目录扩充、项目技能、授权及导入已通过上述隔离验收，但未逐一调用真实生产组件或付费模型；实际执行仍需真实模型和授权连接。
- 单机单进程交付，非高可用分布式编排。后端重启不自动恢复正在执行的有副作用步骤。
- OpenAI-compatible 工具调用协议；不含 Anthropic 原生协议适配。
- 知识库采用本地文本检索，不含向量数据库或 OCR。
- 头像目前为可更换的文字标识，不是图片上传头像。
- 告警为平台内失败告警和手动录入，未接 Prometheus Alertmanager 等外部告警源。
- 正式公网部署前需要 HTTPS、关闭开放注册、最小权限 SSH / Kubernetes RBAC，并根据实际域名调整同源与 Cookie 配置。

部署、安全边界、备份和首次接入步骤参见 `README.md`。
