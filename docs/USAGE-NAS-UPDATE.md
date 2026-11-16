# 全资源调用统计与单 NAS 存储更新

本轮日期：2026-10-29。目录扩充、项目技能、多选、控制等级授权及用户导入已通过验收：后端 Ruff、WAL/DELETE 各 1023 项测试，前端 lint、115 项测试及生产构建通过；1366px/390px 浏览器 7 项检查和完整旧库启动/重启验收通过。镜像与源码包状态见 [交付记录最终项](DELIVERY.md#镜像与源码包最终项)，完整结果见 [本轮更新说明](CATALOG-CONTROL-UPDATE.md)。现机无 production 服务，临时验收服务已停止；未访问真实 NAS、付费模型或生产基础设施，未部署用户实际服务或迁移数据。

部署约束不变：部署平台将原 `10.53.10.5:/nas` 直接挂到容器 `/app/data`，不存在需要填写的宿主机 NAS 路径。唯一 `compose.yaml` 不定义服务或顶层 `volumes`，不使用 `EARTHAI_NAS_DIR`；由平台保留这一个外部持久化挂载，不增加其他持久目录，不做 split、本地 state、启动复制或周期异步写回。

此前 723/71、603 项测试及旧报告保留为对应轮次历史证据。[旧隔离容器报告](admin-container-verification.json) 与 [旧浏览器报告](personal-resources-verification.json) 记录 2026-10-28 的功能；本轮新报告为 [catalog-control-verification.json](catalog-control-verification.json)。该次隔离实例初始为 100 技能、50 库、392 篇文档，每库 3–12 篇；392 仅为首次随机结果，不代表固定规模或用户生产数据。500 篇是候选专题，不是全部落库。旧临时目录容器和本轮隔离检查都不是实际平台/NAS或物理断电测试。

## 全资源统计口径与三种展示范围

后台概览有三张独立卡：「智能体总调用次数」「知识库总调用次数」「技能总调用次数」，同时显示原有统计起点。概览范围是所有用户的默认及 private 资源，包含已经删除的资源/模板历史；不是仅对当前默认卡片求和。默认管理卡的 `usage_count` 仍按模板来源汇总所有用户副本，用户三类目录的 `usage_count` 则仅统计当前 owner 的单资源。接口返回 0 时显示 0 次，缺失字段时显示「暂无统计」，不能从页面浏览或任务数量推算。

| 资源 | 何时计一次 | 不计算什么 |
| --- | --- | --- |
| 本地智能体 | 任务首次发起模型请求时计一次；不要求请求或任务成功 | 仅选择/查看、未发起请求的配置失败 |
| 远程智能体 | 每次在 EarthAI 卡片激活链接后，成功 `POST /api/agents/{ownerAgentID}/open` 独立落库；default 和 private 均计 | 不代表外站加载、站外模型调用或执行成功；右键菜单直接打开、复制 URL 或直接访问外站无法追踪 |
| 技能 | 智能体、项目绑定 ID 按顺序合并并保序去重，先取前 12 个槽位，仅统计其中存在、enabled 且实际注入的技能 | 未启用、缺失、未注入、仅绑定/浏览；不从后续列表补足，全选不改变上下文上限 |
| 知识库 | 检索命中并进入任务参考时计一次，包括初始参考和任务内 `knowledge_search` 命中 | 未命中、仅绑定、目录筛选、页面阅读或手工知识搜索 |

`backend/usage.py` 保留 SQLite `resource_usage` 和 `(run_id,kind,resource_id)` 唯一键及 `INSERT OR IGNORE`。同任务多轮推理、模型重试、多篇文档或重复命中同库不重复计数；不同任务分别计数，同任务使用不同资源分别计数。新增 `remote_agent_clicks(id,owner,resource_id,template_id,created_at)` 每次 POST 使用独立事件 ID，不创建 run，不参与任务去重，不做 GET 副作用；资源 ID 使用当前用户副本 ID，private 的 `template_id` 为 null。

一次远程点击指卡片的一次链接激活成功写入的一条事件，不是外站访问审计。原生 `<a>` 的普通左键、键盘激活及 Ctrl/Meta 点击由 `onClick` 各 POST 一次，中键由 `onAuxClick` 的 button=1 分支各 POST 一次，不为右键 button=2 或额外 keydown 重复计数。目标网页由浏览器处理；登记失败必须错误 toast，不增加已确认计数或伪报成功，即使登记成功也不能证明外站打开成功。

概览不因资源或模板删除丢掉历史；默认管理卡按记录的 `template_id` 汇总继承/个人定制副本，private 以及已没有卡片的模板历史仍存在于全量总计中，因此卡片之和可以小于概览。删除用户沿用清理其全部 `resource_usage` 与 `remote_agent_clicks` 的规则，包括已删资源对应记录，所以总计仍可下降，不是不可回退账本。个人副本保留来源与既有计数，规则见 [PERSONAL-RESOURCES-UPDATE.md](PERSONAL-RESOURCES-UPDATE.md)。

`platform_settings.usage_started_at` 仅首次初始化，重启/升级不重置；接口以 `started_at` 返回，不从旧任务、聊天或绑定关系回填，也不回填新增远程统计前的点击。混合统计不是供应商 HTTP 请求数、token 用量、任务成功率或计费依据。

- `GET /api/admin/overview`：`usage` 包含 `totals:{agents,knowledge,skills}`、`started_at`、`scope:'all_resources'`、`method:'per_run_resource_and_remote_click'`、`description`；原 `counts` 仍表示资源和任务数量。
- `GET /api/admin/defaults/agents`、`GET /api/admin/defaults/knowledge`、`GET /api/admin/defaults/skills`：每项 `usage_count:number` 为模板来源汇总；智能体同时含其远程点击。
- `GET /api/agents`、`GET /api/knowledge`、`GET /api/skills`：每项 `usage_count:number` 为当前用户单资源统计，无记录为 0；智能体合并本地 per-run-resource 与远程 per-click。
- `POST /api/agents/{ownerAgentID}/open`：当前 owner 的 remote 副本，无必需请求体，返回 `{ok:true}`；default remote 的只读不禁止打开登记，但不能编辑/删除。本地或无权限资源拒绝，不访问目标 URL、不调用模型。

### 启动初始化与本轮数据迁移边界

启动初始化可幂等补建缺失表/索引，保留原 usage rows、起点、数据库及主钥。现有 `CREATE TABLE IF NOT EXISTS` 不会修改已存在表的列，不能称为任意 ALTER 迁移框架，也不能保证未来只修改 CREATE 定义即可升级旧库。

本轮无需新增列：`allowed_control_levels` 写入 `users.data` JSON 新 key，项目 `skill_ids` 写入 `entities` JSON，目录沿用既有表；其他 JSON keys、旧数据、原密文及原磁盘/环境主钥保留，不清库。每次容器启动执行幂等 init；目录内容、首次随机结果和 marker 仅随成功事务提交，重启不重抽，管理员改删与个人 override/deleted 继续保护。

完整旧库 lifespan 已验证：手工五表旧库经 TestClient startup 补齐所需表/索引，旧密码哈希、主钥、密文行及管理员修订/删除保留，重启完整快照不变。`control_grants_v1` 为缺字段旧账号一次性补齐原三种授权，不覆盖新账号或管理员显式配置，坏字段仍 fail closed。本轮已处理缺失表/索引初始化、JSON 授权/项目技能及目录事务 marker，不代表未来任意 DDL 或列变更自动升级。

模式 grants 收紧须先持久化，再仅取消任务或关联智能体模式被撤权的活动任务并使审批过期；已发出的远端操作不能撤销。用户八类导入仍受相同 owner/模式校验，schedule 默认关闭，provider 目录发现只在提交后执行、失败返 warnings，不重导已保存资源。完整契约见 [CATALOG-CONTROL-UPDATE.md](CATALOG-CONTROL-UPDATE.md)。

## 保留的 I/O 优化与历史模拟

- **独占借用连接池**：按进程/数据库路径隔离，借出期间连接只供该调用使用，提交/回滚并清理回调后归还，不让并发请求共享同一连接。
- **列表批量统计**：用户及管理员默认知识列表用 `GROUP BY` 汇总文档/分块数，避免逐库查询。
- **无变化不重同步**：模板、用户及同步版本不变时，`defaults.sync_all_if_needed()` 的同步检查仅 3 条 SELECT、无 DML/重建索引，不是整个应用启动仅 3 条 SQL。
- **稳态 GET 不取写锁**：偏好和排序有效时直接读取；首次初始化、失效引用修复及显式保存仍可能写库。
- **前端仅合并在途 GET**：同会话代次、同路径共享未完成请求，完成即移除，写请求前后失效映射；没有 TTL 结果缓存，串行 GET 仍请求服务端。
- **SSE 进程通知**：事件持久化提交后通知，空闲等待及十秒心跳替代 80ms 空查，保留事件游标和重连恢复；通知不跨 worker。
- **cron SQL 筛选**：仅返回已启用、到期且账号可执行的任务。

[历史模拟报告](nas-performance-verification.json) 由 `scripts/benchmark_nas_io.py` 在上一轮 **WAL 隔离环境**生成：临时目录、TestClient、50 库/100 文档、每条 SELECT 人工延时 5ms，对比等价旧逐项路径与当时列表接口，各采样 3 次。

| 指标 | 等价旧逐项路径 | 当时优化接口 |
| --- | --- | --- |
| 每次列表 SELECT 数 | 52 | 3 |
| 每次列表连接借用次数（checkout） | 52 | 3 |
| 三次样本的中位耗时 | 287.16ms | 20.11ms |

20 次顺序读只创建 1 个物理连接；连接借用不等于物理建连。不变默认目录同步检查为 3 条 SELECT、0 次写入。

**这些数值不是本轮 DELETE/NAS 实测，不能承诺更快。** 模拟未复现真实网络锁、fsync、缓存、并发或断电恢复；远程 `synchronous=FULL` 提交仍可能很慢，不能据此推算用户吞吐量或加速倍数。

## 唯一持久化：平台 NAS → `/app/data`

唯一部署文件为 [compose.yaml](../compose.yaml)，镜像标签保持 `earthai:latest`，不代表旧镜像已包含本轮代码；root、非 privileged、原安全约束及端口不变。服务和顶层均无 `volumes` 定义，NAS 挂载由部署平台管理，不由 Compose 创建。

| 项目 | 最终部署配置 |
| --- | --- |
| 平台存储源 | 原 `10.53.10.5:/nas`，无需宿主机 NAS 路径或 NAS 路径变量 |
| 唯一外部持久化挂载 | 平台将原 NAS 直接挂到容器 `/app/data` |
| Compose 应用环境 | `EARTHAI_DATA_DIR=/app/data`、`EARTHAI_SQLITE_JOURNAL_MODE=DELETE` |
| 数据位置 | `/app/data/earthai.db`、原 `master.key`、`branding/`、`uploads/`，均直接在 NAS 读写 |
| 不使用 | STATE/UPLOADS 覆盖、本地状态盘、额外挂载、启动复制、周期异步写回 |

**Compose 本身没有持久化定义。** 单独执行 `docker compose up` 不会获得 NAS 持久化；只有平台保留原 NAS → `/app/data` 挂载才持久。平台导入 Compose 后若重建容器，必须在最终部署配置中继续保留该存储设置，不能只检查导入文件。目录存在或健康检查通过不证明 NAS 挂载正确，须结合平台配置及原数据核验；内存缓存不是唯一数据源。

### SQLite、密钥与恢复边界

- `backend/store.py` 保留 `WAL` 兼容能力，当前 Compose 显式使用 `DELETE`；每个物理连接设置 `synchronous=FULL`，禁止 `OFF` / `MEMORY` 等不安全日志模式，不关闭 fsync/持久化同步。
- SQLite 官方 [WAL](https://sqlite.org/wal.html) 明确不支持网络文件系统，[网络文件访问说明](https://sqlite.org/useovernet.html) 提醒网络锁和同步实现可能造成损坏。DELETE 仅缓解 WAL 共享内存依赖，不是 NAS 安全认证，不保证任意故障下零丢失。只运行一个 worker、一个写同目录的容器，也不能消除网络文件系统风险。
- 旧 WAL 库先停所有旧实例，再由 SQLite 在新实例启动时切换到 DELETE。不得删除 `earthai.db-wal`、`earthai.db-shm` 或 `earthai.db-journal`，不得裸复制运行中的数据库。
- `EARTHAI_MASTER_KEY` 非空时优先于磁盘主钥。旧实例用环境主钥就持续提供**原值**；仅用磁盘主钥就保留原 `master.key`，不要生成替代密钥，也不要因目录中存在 key 文件而擅自替换原环境值。环境主钥不归档，须另行安全保管，并在以后每次重建继续提供；维护环境需要解密时也必须从原安全渠道取得原值，不在命令行或日志中输出密钥。
- 同一 NAS 数据目录和原主钥重新挂回后可使用已提交记录；执行中任务在进程中断后标记 `interrupted`，不自动重放有副作用的步骤，需核查远端状态。恢复仍受 NAS 锁、同步和数据损坏风险约束。

旧默认命名卷 `earthai-data` 不再是当前默认。**其他用户若历史数据仍在命名卷，不能直接以新配置启动并丢弃原挂载。** 应使用旧配置保留原卷，停写备份并确认迁移完成后再切换，不执行 `down -v`。本用户已有原 NAS 直挂，不搬数据。

旧 split 路径 API 与 `scripts/migrate_nas_state.py` 仅为旧配置兼容，本次不执行迁移脚本。本用户未做 split，直接保留原 NAS。若其他部署已做 split，先确认有效数据库/密钥实际位置并保留全部数据，不能丢弃 split 库或直接用 NAS 中的旧副本启动；下述流程不替代其迁移确认。

## 平台停机更新流程

### 1. 保留原配置并停止全部写入者

在平台核对原服务标识、项目名、镜像、端口、origin、Cookie、注册策略、受保护环境配置及原主钥，确认原 NAS 中数据库、上传和品牌仍在。暂停定时任务和上传，等待或取消所有活动/待审批任务，核查已发往远端的操作；通过平台停止全部写同目录的旧实例。保留原配置供核对或回退，不执行 `down -v`，不删除原卷、NAS 文件或 SQLite 日志。

### 2. 停写后备份到同一 NAS

备份须在**同时有项目源码和 NAS 访问权限的维护环境**执行，不能假定 Docker 宿主机有 NAS 路径。当前应用镜像没有 `scripts/backup.py`，不能假定可在应用容器内直接运行该脚本。

在具备权限的维护容器或平台环境中，确认其真实可见的 NAS 数据根目录（不是 `uploads/`），将 `EARTHAI_DATA_DIR` 指向该目录，清除旧 `EARTHAI_STATE_DIR` / `EARTHAI_UPLOADS_DIR` 覆盖，将 `EARTHAI_BACKUP_DIR` 指向**同一 NAS 根目录下的 `backups/`**，从源码根目录用 Python 标准库运行 `python3 scripts/backup.py`，无需安装应用依赖。只有维护环境实际可见该挂载时，才可用 `/app/data` 作为路径；不需要为应用增加新挂载。若不能提供这种维护环境，可在停写后使用 NAS 自身快照，不用未经确认的宿主路径命令代替。

脚本通过 SQLite backup API 生成一致数据库快照，归档收集 `data/earthai.db`、可用的 `data/master.key`、`data/branding/` 和 `data/uploads/`，权限为 0600。确认备份成功、可读取且文件齐全后再启动新版；跨数据库和文件的一致性依赖停写窗口。环境主钥不会进入归档，须另外安全保管原值。

同 NAS 的 `backups/` 或快照可防部分误操作，**NAS 整体损坏时原数据和备份仍可能一起丢失**。NAS 自身 offsite 由用户备份策略安排，不要求新增应用挂载。

### 3. 导入唯一 Compose 并保留平台存储

将唯一 `compose.yaml` 导入平台，保留原访问策略、受保护环境配置和原主钥。核对平台最终部署配置仍将原 `10.53.10.5:/nas` 挂到 `/app/data`，且只有这一个持久化挂载；Compose 不含 `volumes`，应用 DATA 为 `/app/data`、日志为 DELETE，不设 STATE/UPLOADS 覆盖，只运行一个 worker、一个写同目录容器。不要套用旧升级脚本的命名卷/split 配置。镜像与源码包状态见 [交付记录最终项](DELIVERY.md#镜像与源码包最终项)，不能以同名 `earthai:latest` 标签推定包含新代码。平台更新应使用最终验证的镜像，保留原挂载及主钥，不清库。

可在有 Compose 文件和原受保护配置的环境做静态校验：

```bash
docker compose -f compose.yaml config --quiet
```

`--quiet` 不打印可能包含主钥的完整展开配置；若必须查看完整 `config`，仅在受控终端核对，不对外分享。**配置校验不验证平台存储注入、NAS 挂载成功、数据保留或服务运行。** 平台导入后重建时仍必须保留上述存储设置，不以单独 `docker compose up` 替代平台部署。不提供未经确认的平台 CLI 或 NFS driver 方案。

### 4. 通过平台启动并检查原数据

由平台启动服务后，结合最终部署配置和实际运行数据核对 NAS → `/app/data` 挂载、DATA 路径及 DELETE/FULL 生效情况。再检查健康接口、原账号登录、原供应商/服务器凭据解密、统计与会话、知识文档/个人文件及品牌图片。健康检查成功不等于挂载、原数据或解密已核实；这些运行检查需要平台配置和原数据访问权限，本轮未部署用户实际服务。

后续重建和升级都须保留同一 NAS、原服务标识、访问配置及原主钥，停写后按上述维护环境备份或 NAS 快照流程处理。新版本写入后，旧备份不含新记录，不能称为无损回退。
