# 空间模块与团队空间

**2026-10-29：本轮空间模块与团队空间已通过自动化、浏览器及隔离容器验收。** Ruff、286 项专项（团队 148、模块 133、备份 4、schema 1）、WAL/DELETE 各 1308 项通过；前端 lint、122 项测试（团队 UI 7 项）及构建通过，JS 773.05 KB、CSS 227.22 KB，Vite 体积提示非阻塞。浏览器 12 项检查、35 项负向断言、10 项布局检查及镜像无网络持久化检查通过。源码交付位置为 `/home/god-agent/god-agent-workspace/EarthAI-source.zip`；耗时、镜像 ID、报告及验证边界见 [DELIVERY.md](DELIVERY.md)。

## 空间授权不等于删除数据

`User.space_modules?: ('personal'|'team')[]` 为无重复的精确子集，允许 `[]`。公开注册、管理员创建未指定时默认 `["personal"]`；一次性 `space_modules_v1` 只为缺字段旧账号补 personal，不覆盖显式配置，已有坏值拒绝授权。普通用户不能通过资料修改自授；管理员创建、编辑可配置，批改只有勾选“应用开放空间”才替换完整数组，未勾选不改，空数组合法。

关闭 personal/team 只隐藏对应导航、阻止直接访问并拒绝相关 API；entities、个人文件与物理 blob、团队空间及成员关系保留，重新开放仍可访问原数据。永久删除账号另有清理语义：个人文件可删，团队所有者必须先转交，不能连带删除团队。

空间模块、团队角色和 `allowed_control_levels` 独立。开启 team 或被邀请不会授予模型、SSH 或控制等级权限；平台管理员的治理权也不变成普通用户执行权。

## 入口与角色

普通用户入口 `/team-spaces`，管理员入口 `/admin/team-spaces`。团队是独立实体，不属于默认资源模板；启用 team 的普通用户可创建自己的空间，只能读取自己有成员关系的团队。非成员不得读取空间、成员或文件；管理员可全局治理，写操作留审计。

以下权限适用于未归档空间；所有非 owner 成员可自行退出。

| 角色 | 允许的操作 | 明确禁止 |
| --- | --- | --- |
| viewer | 读取空间信息、成员列表和共享文件 | 文件写入、成员管理、空间治理 |
| editor | viewer 权限，以及上传、重命名、替换、确认删除全部共享文件 | 成员管理、空间治理；不能把文件写权限限定为仅本人上传 |
| manager | editor 权限，以及修改空间资料、添加/调整/移除 viewer/editor | 授予或修改 manager/owner、转交、归档/恢复 |
| owner | 全部团队操作，包括 manager 授权、转交、归档/恢复 | 直接退出、降级或移除唯一 owner |
| admin | 管理入口全局治理并审计，包括失活 owner 的救援转交 | 成为普通用户执行者、绕过唯一 owner 或目标账号限制 |

前端是目录/详情双区工作台，详情含文件、成员标签页；两区限高并独立滚动，手机改为上下布局。管理员用户表单用独立空间复选框及批量应用开关，显示“关闭不删数据，可重新开启”的提示；团队表单不得显示仅适用于个人资源的提示。按钮隐藏不能代替服务器实时校验。

## 添加、移除与所有权

- 添加成员使用准确的已有邮箱/账号，API 字段名为 `email`，不公开全用户目录、不创建新账号。目标必须为已启用、无需强制改密的普通账号，否则拒绝。
- 目标未开 team 且未被平台明确阻止时，在添加成员的同一事务将 team 并入当前模块集合，保留 personal、其他账号数据与 grants；原已开 team 不改。新 personal 用户的 `team_invites_blocked` 默认 false。
- 管理员把原已开的 team 关闭时设 `team_invites_blocked=true`。邀请不能绕过，返回 409；管理员重新勾选 team 保存后清除阻止。转交及管理员代建空间也不能绕过目标阻止标记。
- 移除/退出只移除本团队成员关系，不自动关 team（可能仍在其他团队），不删除其上传的共享文件。editor 及以上可操作的文件属于团队，不归上传者私有。
- owner 只能转交给现有活跃普通成员；转交原子更新唯一 owner，原 owner 变 manager。目标若被平台阻止 team，须先由管理员开通。停用账号或关闭模块不会移除所有权，管理员可转交救援失活 owner；空间若已归档，必须先恢复后转交。
- 平台删除账号或将账号升为 admin 前，对整批账号拥有的空间（包括归档）事务预检，冲突返回 409，不能部分操作。非 owner 删号只级联清理其 membership；共享文件及 blob 保留，uploader 变 null。

## 软归档与文件边界

空间 DELETE 仅设置 `deleted_at`，不删除成员或文件。归档后可读基本信息及成员列表，拒绝文件列表、文件信息、下载、上传、重命名、替换、删除和成员写入；owner/admin 可恢复。所有操作者（含管理员）的转交、退出、成员写入与文件写入都须先恢复，不设救援例外。本轮不新增永久 purge。

个人文件 API 与 Agent `list_files/read_file/write_report` 使用最新 personal 授权，成功写结果缓存复用前也要检查。上传在 await 后、落文件前再次检查；模块关闭后不创建、不读内容、不 unlink，原文件 ID 与字节保留。本轮不新增团队 Agent 工具、不自动把共享文件送进模型，也不允许跨团队读取。

## API 清单

用户前缀 `/api/team-spaces`，管理员前缀 `/api/admin/team-spaces`。下列后缀适用于两者，只有 `/leave` 仅供用户。归档时，转交、退出、成员写入及文件写入对所有操作者（含管理员）均拒绝，必须先 `POST /{space_id}/restore`；文件读取/下载也暂停。方法与请求字段以 [team_routes.py](../backend/team_routes.py) 和 [teams.py](../backend/teams.py) 为准；本轮自动化、浏览器与隔离容器持久化验收均已通过。

### 空间

| 方法与后缀 | 请求或结果 |
| --- | --- |
| `GET /?include_archived=true` | 空间列表；不传时默认排除归档，用户只列所属团队，管理员列全部 |
| `POST /` | `{name,description?}`；管理员另须 `owner_id`，目标为可接收团队权限的普通账号；返回空间 |
| `GET /{space_id}` | 空间基本信息，含当前角色、归档状态和成员/文件统计 |
| `PATCH /{space_id}` | `{name?,description?}`，至少一项；manager/owner/admin 可改 |
| `DELETE /{space_id}` | owner/admin 软归档，返回 `{ok:true}` |
| `POST /{space_id}/restore` | owner/admin 恢复，返回空间 |
| `POST /{space_id}/transfer` | `{user_id}`；转交给现有活跃普通成员，返回空间 |

### 成员

| 方法与后缀 | 请求或结果 |
| --- | --- |
| `GET /{space_id}/members` | 当前团队成员列表 |
| `POST /{space_id}/members` | `{email,role}`，role 为 viewer/editor/manager，仍受操作者角色限制 |
| `PATCH /{space_id}/members/{user_id}` | `{role}`；不能直接修改 owner |
| `DELETE /{space_id}/members/{user_id}` | 移除成员，或非 owner 自行退出；返回 `{ok:true}` |
| `POST /{space_id}/leave` | 仅用户入口，非 owner 退出；返回 `{ok:true}` |

### 共享文件

| 方法与后缀 | 请求或结果 |
| --- | --- |
| `GET /{space_id}/files` | 文件列表 |
| `POST /{space_id}/files` | multipart `file`，非空且单个不超过 20 MB；返回文件 |
| `GET /{space_id}/files/{file_id}` | 文件信息 |
| `PATCH /{space_id}/files/{file_id}` | `{name}` 重命名，返回文件 |
| `PUT /{space_id}/files/{file_id}/content` | multipart `file` 替换内容，返回文件；保留文件 ID |
| `GET /{space_id}/files/{file_id}/download` | 鉴权 attachment 下载 |
| `DELETE /{space_id}/files/{file_id}` | editor/manager/owner/admin 可删全部共享文件，前端须确认；返回 `{ok:true}` |

未启模块/角色无权拒绝访问；非成员资源按不存在处理。归档、平台阻止邀请、所有权保护等冲突返回 409。精确字段和状态码以最终实现为准，不虚构管理员用户搜索接口。

## 升级、NAS 与备份

启动幂等补建 `team_spaces/team_members/team_files` 及索引，空间模块使用 `users.data` JSON 与 `space_modules_v1`。不清用户库、不重置原数据或主钥，不把 `CREATE TABLE IF NOT EXISTS` 当作通用 ALTER 框架；具体列定义以 `teams.py` 为准。

团队 blob 使用随机 `team-<uuid>` 名称，平铺在既有 `/app/data/uploads/`，不另加持久盘。[backup.py](../scripts/backup.py) 收集上传目录的平铺文件，备份专项 4 项已通过。不同无网络容器复用同一临时 bind → `/app/data` 的扩展持久化检查已通过：个人与共享文件原 ID/字节、原 key 摘要、owner＋manager 成员、owner 模块 `[]` 与阻止邀请标记、成员 team 模块及归档状态保留；管理员无模块可治理并 restore，owner 重开两模块后原文件可读。邀请自动开启/显式关闭 409 及 owner 删除/升管理员 409 通过。未使用真实 NAS 或用户 volume；备份中数据库与 blob 的一致性仍依赖停写和同一窗口。

唯一 `compose.yaml` 不定义服务或顶层 volumes；平台必须持续保留原 `10.53.10.5:/nas` → `/app/data` 挂载。数据库、原主钥、品牌与 uploads 全部直接读写同一 NAS，DELETE/FULL、单 worker、单写容器和 root-only 不变；不做 split、启动复制或异步写回。Compose 单独启动不能证明持久化，DELETE 也不是 NAS 安全认证。部署和原主钥保全步骤见 [README.md](../README.md#docker-部署)。

本机无 production 服务；本轮未访问用户真实 NAS、付费模型或生产基础设施，未部署用户服务。核心与自动化检查、浏览器、唯一 Compose 校验、新镜像构建及扩展隔离容器持久化检查已通过。浏览器报告 [team-spaces-verification.json](team-spaces-verification.json) 为 `ok:true`，12 项检查、35 项负向断言、10 项布局检查覆盖双角色桌面/手机、独立滚动、权限与保数据流程；一次受控导航期间成功 PUT 的预期响应中止单独列示，不混作非预期失败。源码交付位置为 `/home/god-agent/god-agent-workspace/EarthAI-source.zip`，排除用户数据、上传、主钥、备份及私有配置。WAL 全套 `1308 passed in 168.02s`、DELETE 全套 `1308 passed in 176.74s`，仅 1 条既有 Starlette/AnyIO 弃用警告；这些隔离结果不能证明真实 NAS 任意故障下零丢失。
