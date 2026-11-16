"""Additional reference presets, kept independent of the installation module."""

from __future__ import annotations

_ACCESS = {
    "k8s": (
        "先用 server_info 确认选定服务器、集群、命名空间和授权，未选目标只提供参考。原生 Kubernetes 仅支持 "
        "nodes/pods/deployments/statefulsets/daemonsets/replicasets/services/ingresses/events/PVC；"
        "其他资源、指标、exec 与历史日志必须有本轮已选 SSH、实际可用 kubectl 和相应授权才能补证，"
        "不可访问时明确待补证，不创建调试 Pod 绕过。保留 TLS 与 SSH 主机指纹校验，不读取 Secret 或凭据。"
        "SSH 命令即使意图只读，未被后台识别或未在只读白名单时仍须审批；"
        "不得换 shell、sudo、脚本或客户端绕过拒绝。"
    ),
    "ssh": (
        "先用 server_info 确认本轮已选 SSH 主机、服务实例、责任人和授权范围；没有连接只交付参考，"
        "不假装已验证生产。仅使用主机已存在且获准的客户端，命令缺失只记待补证，不默认扫描、安装软件或写入。"
        "保留 TLS 和 SSH 主机指纹校验，不读取凭据、私钥、环境文件或含秘密的完整配置。"
        "SSH 命令即使意图只读，未被后台识别或未在只读白名单时仍须审批；"
        "不得换 shell、sudo、脚本或客户端绕过拒绝。"
    ),
    "db": (
        "先确认本轮已选 SSH、实例身份、角色、版本和授权；本系统没有数据库专用工具。"
        "只用 SSH 主机上已存在的客户端及经确认的安全连接方式，不在命令、URI 或报告中放密码，"
        "不打开凭据文件、不导出业务记录、不默认扫描、装包或写入。保持 TLS 与主机指纹验证，"
        "未连接或缺权限只记待补证，不假称连接生产验证。"
        "SSH 命令即使意图只读，未被后台识别或未在只读白名单时仍须审批；"
        "不得换 shell、sudo、脚本或客户端绕过拒绝。"
    ),
}


def _document(
    key: str,
    name: str,
    scope: str,
    context: str,
    steps: tuple[str, ...],
    diagnosis: str,
    risk: str,
    change: str,
    verification: str,
) -> dict:
    numbered = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
    return {
        "key": key,
        "name": f"{name}.md",
        "content": (
            f"## 适用范围与输入\n{context}\n\n{_ACCESS[scope]}\n\n"
            f"## 只读步骤与证据\n{numbered}\n\n"
            f"## 判断\n{diagnosis}\n\n## 风险\n{risk}\n\n"
            f"## 审批与恢复路径\n{change}\n\n## 恢复验证\n{verification}\n"
        ),
    }


def _preset(
    key: str,
    title: str,
    description: str,
    skill: tuple[str, str, str],
    agent: tuple[str, str],
    documents: tuple[dict, dict],
    *,
    scope: str = "k8s",
    control_level: str = "observe",
    color: str = "#3b82f6",
) -> dict:
    return {
        "key": key,
        "knowledge_name": f"{title}手册",
        "description": description,
        "skill_name": skill[0],
        "skill_description": skill[1],
        "skill_content": (
            f"{skill[2]}{_ACCESS[scope]}"
            "任何远端写操作先提交对象、字段差异、影响、停止条件与恢复方法，通过后台审批；"
            "observe 只给建议，用户拒绝不得换路径执行。结论区分事实、假设和待补证，记录采集时间与验证范围。"
        ),
        "agent_name": agent[0],
        "agent_role": agent[1],
        "control_level": control_level,
        "color": color,
        "documents": documents,
    }


_WORKLOAD_PRESETS = (
    _preset(
        "deployment-diagnostics", "Deployment 发布诊断",
        "分解 ReplicaSet 扩缩、进度条件和可用性门槛，定位滚动发布为何停止收敛。",
        (
            "Deployment 进度条件与副本链诊断",
            "用新旧 ReplicaSet、generation 和滚动预算定位卡住的发布阶段。",
            "输入 Deployment 名称、命名空间、发布起点和批准镜像；读取 strategy、paused、minReadySeconds、"
            "progressDeadlineSeconds 与 conditions，先比较 generation/observedGeneration，再按 ownerReferences UID "
            "关联 ReplicaSet 和 Pod。核对 maxSurge 向上取整、maxUnavailable 向下取整后的额外容量，区分创建受阻、"
            "调度失败、启动失败与 Ready 后尚未达到可用时长。ProgressDeadlineExceeded 不是自动回滚；"
            "比较新旧副本事件和同一版本的失败分布，报告旧容量是否仍服务以及最小阻断因素。"
            "恢复候选必须使用已核实模板与不可变镜像，并检查数据库兼容性，不以删除 ReplicaSet 强制收敛。",
        ),
        ("Deployment 发布诊断员", "专注 Deployment 的 ReplicaSet 接管、滚动预算与进度停滞，不代替发布批准人。"),
        (
            _document(
                "rollout-stall", "Deployment 进度停滞与滚动预算", "k8s",
                "适用于发布后 updated 增长停止、旧副本不下降或 ProgressDeadlineExceeded。输入对象 UID、发布时间、批准镜像及业务可用副本门槛，先区分发布尚在观察与真正停滞。",
                (
                    "读取 Deployment 的 generation、observedGeneration、paused、replicas、strategy.rollingUpdate、minReadySeconds 和 progressDeadlineSeconds；保存 conditions 的 type/status/reason/lastUpdateTime，旧代状态不能代表新模板。",
                    "按 ownerReferences.uid 读取对应 ReplicaSet，再关联各 Pod；比较 template 镜像、revision 注解、desired/current/ready。revision 只用于定位顺序，不把数字最大或标签 latest 当已知可用版本。",
                    "计算滚动预算：百分比 maxSurge 向上取整、maxUnavailable 向下取整。三副本配 25%/25% 允许一个额外副本但不允许主动损失可用副本；检查 surge 是否被节点请求量、亲和或待补证配额阻断。",
                    "针对新副本读取 FailedCreate、FailedScheduling、Unhealthy 事件和有限容器日志。Ready 已成立但 available 未增加时核对 minReadySeconds 与 Ready 抖动；先按 UID 和时间排除旧实例遗留事件。",
                ),
                "observedGeneration 落后指向控制器尚未处理声明；ReplicaSet 无法创建与已建 Pod 不 Ready 是不同阶段。Progressing=True 不保证业务可用，ProgressDeadlineExceeded 只表示进度期限失败，控制器不会因此自动撤回模板。",
                "暂停发布时不能机械按墙钟超时判断；盲目降低 minReadySeconds、删除健康旧副本或放大 surge 会掩盖启动问题并挤压其他业务。缺少容量与配额证据时不得宣告可安全继续。",
                "只提交已定位阶段的最小修订，例如修正镜像引用或恢复原探针参数。列明原模板、预期新增资源和可用性底线，经后台审批执行；失败时恢复核实过的模板，不默认 rollout undo 可用。",
                "要求控制器观察到新 generation，新 Pod 镜像与批准值一致，并经过完整 minReadySeconds 后保持 available；比较事件增量与原业务路径。仅副本数相等而业务未测，只能报告资源收敛。",
            ),
            _document(
                "replicaset-history", "ReplicaSet 历史与发布现场保护", "k8s",
                "适用于多次发布交错、revision 不连续或回退后仍不健康。输入最近变更批次、当前控制器 UID 与已知可用版本来源，目标是还原模板链，而不是执行通用回滚。",
                (
                    "读取 Deployment selector、template labels、revisionHistoryLimit 和 owner UID；列出受它控制的 ReplicaSet，记录 creationTimestamp、revision、replicas 与镜像身份。同名重建对象必须按 UID 分开。",
                    "比较新旧 ReplicaSet 的非敏感模板字段：image、command 引用、resources、探针、卷和配置引用版本；只记录环境变量键与引用，不输出直接嵌入的敏感值。区分只扩缩容与真正模板变化。",
                    "从 Pod containerStatuses.imageID、启动时间和事件核对实际运行版本；可变标签可能在不同节点得到不同 digest，不能仅凭 Deployment 的 image 文本认定所有副本相同。缺少 imageID 留待补证。",
                    "将发布记录、ReplicaSet 创建和业务错误按时间对齐，确认旧配置引用仍存在且数据库迁移双向兼容。历史可能因 revisionHistoryLimit 被清理，缺少旧模板不能承诺一键恢复。",
                ),
                "新旧副本同时存在是滚动过程的正常现象；多轮模板变化会使前一轮新副本成为旧版本。必须将具体失败 Pod 归到模板，而非把所有重启合并为一次发布故障。",
                "直接修改 ReplicaSet 会与 Deployment 协调冲突；删除历史会破坏取证，也不能恢复已迁移的数据。镜像缓存暂时可用不保证下次重建仍能拉取，恢复前必须确认镜像来源可访问。",
                "需要回退时提交完整、可核实的旧模板和当前差异，说明配置与数据兼容、当前并发变更及失败后的止损办法；经后台审批后才写入，不删除旧证据或覆盖他人变更。",
                "核对回退后新的 generation、Pod imageID、配置引用和 available，确认原失败功能在对应版本上恢复。保留每个模板实际承载流量的证据，不能以 revision 变小或 API 成功代替业务验证。",
            ),
        ),
        control_level="approve", color="#2563eb",
    ),
    _preset(
        "statefulset-ordered-update", "StatefulSet 有序更新",
        "围绕 ordinal、分区、版本和持久身份处理有状态实例更新停滞与安全回退。",
        (
            "StatefulSet ordinal 与更新分区诊断",
            "区分 OrderedReady、partition、OnDelete 和卷身份导致的更新等待。",
            "输入 StatefulSet、ordinal 范围、服务成员角色和复制健康来源；对照 updateStrategy、rollingUpdate.partition、"
            "podManagementPolicy、currentRevision/updateRevision 与 Pod controller-revision-hash。按实际 ordinal 从高到低"
            "定位首个不 Ready 实例，核对有意保留分区和 OnDelete，不把未更新数量直接判为异常。关联 Pod PVC 引用、"
            "serviceName 与持久身份，区分应用入群失败和存储挂载失败。坏模板回退后仍可能被失败 Pod 阻塞，"
            "不得默认删除强推；只有确认成员退出、复制仲裁、卷无双挂载并经批准，才制定单 ordinal 的受控重建方案。",
        ),
        ("StatefulSet 更新顾问", "专注有状态控制器的有序更新、成员身份与单实例恢复门禁，不自动驱逐数据成员。"),
        (
            _document(
                "ordinal-update", "StatefulSet 分区与有序更新卡点", "k8s",
                "适用于 updatedReplicas 停住、某个 ordinal 启动失败或回退后仍不继续。输入控制器 UID、期望副本、批准更新范围和应用成员仲裁要求；不能套用无状态并行重建流程。",
                (
                    "读取 updateStrategy.type、rollingUpdate.partition、podManagementPolicy、minReadySeconds 和副本状态；比较 currentRevision 与 updateRevision。OnDelete 不会自动替换旧 Pod，partition 以上才是该次更新目标。",
                    "按 Pod ordinal、controller-revision-hash、Ready 与 UID 列表建立映射；确认 spec.ordinals.start 是否显式设置，不能假设永远从零开始。OrderedReady 默认逐个等待，Parallel 主要影响扩缩顺序，不等于滚动更新全部并行。",
                    "定位最高待更新 ordinal 及前一个失败实例，读取探针、应用启动日志与卷事件。Ready 抖动会重置可用时长；应用选主、数据重放或加入集群可能远长于容器启动，需负责人给出业务证据。",
                    "核对每实例 volumeClaimTemplates 派生 PVC 名、volumeName 与 serviceName；记录 FailedMount、Multi-Attach、解析失败的不同分支。ControllerRevision 不在原生范围，只能由授权 SSH kubectl 读取必要的非敏感版本元数据。",
                ),
                "分区有意保留旧版本不是卡住；真正失败要定位到首个阻塞的 ordinal。回到旧模板后，坏版本 Pod 有时仍需人为介入才解除等待，不能把模板已回退等同实例已恢复。",
                "强制删除仍运行的成员可能制造重复身份和脑裂；降低 partition 会扩大受影响副本，修改 readiness 伪造就绪可能让下一成员过早更新。没有复制健康证据应停止推进。",
                "提交单 ordinal 操作顺序、业务仲裁、旧模板、卷身份及停止条件，经后台审批。需要重建时先由负责人确认旧进程退出和存储安全；不使用强制删除绕开挂载保护，不删除 PVC。",
                "逐个核对目标 ordinal 的 revision、Ready 持续时间与业务成员状态，再推进下一实例。current/updateRevision 一致只证明控制器版本，复制追平、读写正确和仲裁仍须独立验证。",
            ),
            _document(
                "identity-retention", "StatefulSet 持久身份与缩容恢复", "k8s",
                "适用于缩容再扩容后成员拒绝入群、旧数据身份冲突或 PVC 生命周期不明。输入应用成员表、目标 ordinal、PVC 名和已批准保留策略；重点保护数据，而非以重装替代判断。",
                (
                    "读取 StatefulSet 的 replicas、serviceName、volumeClaimTemplates 和 persistentVolumeClaimRetentionPolicy；字段缺省与集群支持情况需保留原样。分别核对 whenScaled 与 whenDeleted，不假设缩容一定保留卷。",
                    "从 Pod volumes 与 PVC 的 UID、volumeName、storageClassName、accessModes 还原身份链；读取相关事件确认 attach/mount 阶段。PVC Bound 不证明挂载的就是应用期望的成员数据。",
                    "检查用于稳定网络身份的 Service clusterIP、selector 与 Pod hostname/subdomain；Headless Service 只提供发现基础，成员名称还可能受应用配置与缓存影响。DNS 实测需从原失败路径补证。",
                    "对照应用已有只读成员状态，确认被缩容成员是否已从应用集群移除、旧成员 ID 是否可重用。没有数据库或消息系统客户端时仅引用负责人证据，不从 Pod Ready 推导副本完整。",
                ),
                "同一 ordinal 重建通常期望复用其持久身份；应用已经移除成员时，旧数据未必能直接重新加入。网络标识、卷标识和应用内部成员标识必须同时一致，任何一项未知都不是可安全扩回的结论。",
                "更改 retentionPolicy 会影响将来的删除行为，不能修复已经删除的数据。复制旧目录、手改集群 ID 或为试错删除 PVC 可能损坏唯一数据；单副本和本地卷尤其不能靠迁移碰运气。",
                "扩回、迁移或恢复成员需提交数据保护点、成员加入流程、剩余仲裁与原副本恢复方法，经后台审批。存储回收策略、PV 与快照超出原生工具时交存储负责人补证，不虚构已检查。",
                "验证目标 ordinal 使用批准 PVC、稳定名称解析正确、成员状态可服务且复制追平。对比业务读结果和经批准的写验证；没有应用层证据时只能记录身份配置已核对，不能声明数据安全恢复。",
            ),
        ),
        control_level="approve", color="#4f46e5",
    ),
    _preset(
        "daemonset-coverage", "DaemonSet 节点覆盖",
        "从合格节点集合、实际覆盖与更新预算解释系统守护进程缺席和版本不齐。",
        (
            "DaemonSet 合格节点与覆盖差额核查",
            "以节点选择、容忍和逐节点实例映射定位缺席，而非直接要求所有节点有 Pod。",
            "输入 DaemonSet、负责节点池、预期平台架构和镜像版本；读取 desiredNumberScheduled、currentNumberScheduled、"
            "numberReady、numberAvailable、numberMisscheduled 与 updatedNumberScheduled。将 nodeSelector、required affinity、"
            "污点及节点 Ready 映射到实际 eligible 集合，再按 owner UID 和 nodeName 找出缺席、未就绪或多余实例。"
            "读取 updateStrategy、maxUnavailable、maxSurge 和 minReadySeconds，区分 OnDelete 与滚动等待。"
            "对缺席节点核对 hostPort、资源请求、架构、镜像及挂载事件，网络或存储插件故障时避免批量删除自身承载链路的 Pod。",
        ),
        ("DaemonSet 覆盖核查员", "专注节点守护进程的合格覆盖、滚动更新与系统组件自依赖风险。"),
        (
            _document(
                "eligible-nodes", "DaemonSet 缺席与合格节点集合", "k8s",
                "适用于日志代理、网络插件或节点监控在部分节点没有实例。输入负责节点池、控制器 UID、架构要求和当前故障节点；覆盖目标不是无条件等于集群节点总数。",
                (
                    "读取 DaemonSet selector、template 的 nodeSelector/affinity/tolerations、hostNetwork、hostPort 和 requests。记录 desiredNumberScheduled、currentNumberScheduled、numberMisscheduled 与 observedGeneration；状态可能尚未反映最新模板。",
                    "列出 nodes 的标签、污点、allocatable、Ready 与 unschedulable；逐项计算符合硬约束的节点集合。DaemonSet 有部分自动容忍，不能只因节点被 cordon 就断定守护 Pod 必然不能存在或已被驱逐。",
                    "按 ownerReferences.uid 与 nodeName 关联 Pod，分成根本未创建、Pending、Running 不 Ready 和旧版本。对每个缺口读取事件，识别 hostPort 冲突、Insufficient 资源、架构不兼容和镜像拉取失败。",
                    "比较受影响节点和同池健康节点的 OS、architecture、标签及模板版本；只在已选授权 SSH 上读取该节点运行时/服务日志。不从其他节点成功推导缺席节点的网络、存储或主机条件正常。",
                ),
                "numberMisscheduled 表示实例落在不再应运行的节点，不能当缺失数量；numberReady 与 numberAvailable 差异可能来自 minReadySeconds。desired 较少可能是合理隔离，也可能是标签漂移，需与负责人声明比较。",
                "扩大 tolerations、去掉节点选择或改 hostNetwork 会改变安全边界；资源请求较大的守护进程可能挤压业务。网络插件在故障节点重建还可能无法获得网络，批量操作会扩大不可达。",
                "提交针对已确认差异的最小模板或标签修订，列出新增覆盖节点、端口与容量影响，保留原字段，经后台审批。节点标签也属于写变更，不因其是排障辅助而自动修改。",
                "复核 eligible 集合与每节点实例 UID，要求更新后的 observedGeneration、Ready 和 available 对齐。日志采集或网络代理还需验证其真实功能；Pod 都在并不证明它们已成功上传或转发。",
            ),
            _document(
                "daemon-rollout", "DaemonSet 滚动预算与宿主依赖", "k8s",
                "适用于更新停住、部分节点旧镜像长期存在或代理重建导致节点失联。输入发布窗口、关键节点、宿主资源约束和可接受覆盖缺口，避免直接套用 Deployment 的扩容假设。",
                (
                    "读取 updateStrategy.type 与 rollingUpdate.maxUnavailable/maxSurge；确认实际集群版本支持配置组合及互斥约束。OnDelete 要等待人工逐实例替换，不能把 updatedNumberScheduled 不满当控制器失效。",
                    "列出各节点 Pod 的镜像身份、controller-revision-hash、Ready、deletionTimestamp 和事件，关联 updatedNumberScheduled、numberUnavailable。终止中的旧 Pod 仍可能持有 hostPort、设备或宿主文件锁。",
                    "若配置 surge，核对同节点同时运行新旧实例是否允许：hostPort、hostPath 写入、设备和每节点唯一注册身份可能冲突。资源按同节点峰值计算，不能把其他节点余量当此节点可用容量。",
                    "对启动失败的节点比较 minReadySeconds、健康探针和宿主服务依赖；网络插件、日志代理和存储代理分别保留功能证据。历史容器日志需要授权 SSH 的实际 kubectl 能力，原生查询不能假装有 previous。",
                ),
                "maxUnavailable 控制滚动期间覆盖损失，maxSurge 可能降低空窗却引入同节点并存冲突；版本和参数必须按当前 API 实际支持解释。更新停滞也可能是健康门槛正确阻止故障扩散。",
                "一次重启全体网络或存储代理会破坏排障通道和业务卷；强制删除正在退出的实例可能留下宿主状态。不要为推进进度随意提高 unavailable 或取消安全探针。",
                "先选有业务冗余的单节点灰度，提交原模板、同节点资源预算、最大同时缺口和回退版本，经后台审批。失联时由预先确定的节点负责人接手，不承诺当前连接还能执行恢复。",
                "按节点逐个确认镜像、Ready 稳定、旧实例退出和宿主资源交接，再扩大范围。检验实际网络连通、卷操作或日志新鲜度，记录更新期间是否发生覆盖空窗与仍待核实的节点。",
            ),
        ),
        color="#0284c7",
    ),
    _preset(
        "job-cronjob", "Job 与 CronJob 任务",
        "诊断批处理重试、调度错过和并发策略，避免重复执行产生业务副作用。",
        (
            "批处理执行链与定时触发诊断",
            "通过 Job 条件、Pod 退出和 CronJob 时间语义区分执行失败与未触发。",
            "输入任务名、计划时区、业务幂等键和允许补跑窗口；Job/CronJob 不在原生资源范围，只在已选 SSH 的实际 "
            "kubectl 授权下读取 spec/status。检查 completions、parallelism、completionMode、backoffLimit、"
            "activeDeadlineSeconds、podFailurePolicy 与失败 Pod 退出原因；Indexed 任务按完成索引而非 Pod 个数判断。"
            "CronJob 对照 schedule、timeZone、suspend、startingDeadlineSeconds、concurrencyPolicy 和 lastScheduleTime，"
            "关联 owner UID 到 Job。区分没有触发、因 Forbid 跳过和运行后失败；任何手动补跑、解挂起或删除活动 Job "
            "都先确认幂等与外部副作用并经审批，不能把重试等同安全恢复。",
        ),
        ("批处理任务诊断员", "专注 Job 失败策略与 CronJob 调度语义，保护幂等和已完成业务结果。"),
        (
            _document(
                "job-failures", "Job 重试耗尽与完成语义", "k8s",
                "适用于 BackoffLimitExceeded、DeadlineExceeded、任务 Pod 成功但 Job 未完成。输入任务 UID、业务处理范围、幂等约束及实际执行起止时间，先防止重跑已成功的批次。",
                (
                    "Job 需已选授权 SSH 且 kubectl 实际存在；使用 kubectl -n \"$NS\" get job \"$JOB\" -o json，只留 spec 的执行策略和 status，过滤命令、env 中的秘密。不能用原生 list deployments 代替 Job 状态。",
                    "读取 completions、parallelism、completionMode、backoffLimit、activeDeadlineSeconds、suspend 和 status.conditions；版本支持时再读 backoffLimitPerIndex、podFailurePolicy。Failed 条件及终止时机随版本演进，需同时看活动 Pod。",
                    "按 owner UID 关联 Pod，查看 restartPolicy、容器 exitCode、reason、重启与 Pod 终态；OnFailure 可能在同 Pod 内重试，Never 常生成新 Pod，单凭 Pod 个数不能计算尝试次数。",
                    "Indexed 模式对比 completedIndexes/failedIndexes 与实际索引；保存任务自身的已处理批次证据，不读取业务明细。有限日志区分应用错误、OOM、镜像和调度问题，TTL 删除后的历史应标记缺口。",
                ),
                "activeDeadlineSeconds 限定执行期限，不会因增加 backoffLimit 自动解除；任务达到失败条件不代表此前没有成功写入外部系统。完成数达到目标也不能证明每条业务记录都符合约束。",
                "删除 Job、重新创建或解除 suspend 可能重复发通知、扣款和写库；保留 Job/Pod 现场有助于识别部分成功。不能为了保留现场擅自改 TTL 或大规模拉取任务输出。",
                "修正模板后先由业务负责人确认断点、幂等和补跑范围，提交新任务身份、重复结果处理与停止条件，经后台审批。不要覆盖旧 Job 伪装原任务成功，失败时停止后续批次而非盲目增加重试。",
                "用新的 Job UID 核对条件、完成索引与退出码，并由获准业务核对验证批次完整且无重复副作用。只看到 Complete=True 时，结论限定为控制器完成，业务结果仍需负责人确认。",
            ),
            _document(
                "cron-scheduling", "CronJob 漏跑与并发补跑门禁", "k8s",
                "适用于任务未按计划出现、某次周期被跳过或恢复后连续启动。输入 schedule、约定时区、最近应执行时间、允许延迟和幂等证明，不默认采用操作者本地时间。",
                (
                    "通过已选 SSH 的 kubectl -n \"$NS\" get cronjob \"$CRONJOB\" -o json 读取 schedule、timeZone、suspend、startingDeadlineSeconds、concurrencyPolicy 与历史保留数；命令无授权则只列待补证字段。",
                    "记录 status.lastScheduleTime、lastSuccessfulTime、active 引用及控制器事件，按 UID 找对应 Job。未保存历史的成功任务可能已被清理，lastSuccessfulTime 缺失不能直接解释为从未成功。",
                    "对照时区和停机窗口推算错过的计划，使用实际日期工具而非手算时间戳；检查时区字段的版本支持和夏令时。startingDeadlineSeconds 太短可能错过控制器检查，不能直接设零企图立即补跑。",
                    "Forbid 时核查前一 Job 是否仍 active；Replace 会替换活动任务而不是保证业务事务撤销。排查长期运行、suspend 和大量错过计划的控制器报错，不把排程创建时间等同业务完成时间。",
                ),
                "CronJob 提供近似调度，业务需容忍重复或遗漏；Forbid 只约束同一 CronJob 的并发，并不阻止人工复制的 Job。取消 suspend 可能触发错过计划处理，须先测算时间窗口。",
                "直接补跑所有漏掉周期可能造成数据库或下游峰值；改时区可能把每日任务移到另一业务日期。替换仍运行的任务会留下部分结果，控制器终止 Pod 不保证外部调用回滚。",
                "审批单明确应补的业务日期、单次补跑上限、并发数、幂等键和外部副作用；保留原 schedule 与 suspend 状态。所有手动 create job、解挂起、改计划和中止任务须后台审批。",
                "观察至少一个实际计划周期，确认创建时间与时区一致、Job 结果正确且旧活动任务已处理。核对业务日期无缺漏或重复；仅看到下一次被触发不能证明历史漏跑已补齐。",
            ),
        ),
        color="#7c3aed",
    ),
    _preset(
        "hpa-autoscaling", "HPA 弹性伸缩",
        "辨别指标缺失、资源请求偏差、伸缩限制和稳定窗口带来的副本变化。",
        (
            "HPA 指标链与副本决策解释",
            "依据指标有效性、目标引用与 behavior 解释不扩容或缩容延迟。",
            "输入 HPA、目标控制器、指标来源和负载时间窗；仅已选 SSH 上有 kubectl 与权限时读取 HPA 及指标 API，"
            "未接入 metrics-server 或适配器不伪造 CPU 使用率。核对 scaleTargetRef、minReplicas/maxReplicas、metrics、"
            "currentMetrics、currentReplicas/desiredReplicas 和 AbleToScale/ScalingActive/ScalingLimited 条件。"
            "CPU 利用率分母来自 requests，区分资源指标与外部队列指标；缺请求、未就绪与缺样本会影响算法。"
            "结合 behavior 的 stabilizationWindowSeconds、policies、selectPolicy 和多指标取较大建议解释伸缩，"
            "指标出错时不要据剩余低指标承诺缩容；输出受限环节，不手工 scale 与 HPA 反复争抢。",
        ),
        ("HPA 伸缩分析员", "专注伸缩决策输入、指标链和稳定策略，不用手动扩缩掩盖指标故障。"),
        (
            _document(
                "metric-chain", "HPA 指标缺失与利用率分母", "k8s",
                "适用于 TARGETS 显示 unknown、FailedGetResourceMetric 或 CPU 很高但副本不动。输入目标控制器、已接入指标种类、采样时刻与预期扩容信号，不把现场容器数当指标健康证明。",
                (
                    "通过已选授权 SSH 执行 kubectl -n \"$NS\" get hpa \"$HPA\" -o json，核对 scaleTargetRef 的 kind/name、min/max 和 metrics。HPA、metrics.k8s.io 均非原生工具资源，无法访问时列待补证。",
                    "读取 currentMetrics、desiredReplicas 与条件的 reason/message；FailedGetScale 指向目标伸缩子资源，FailedGetResourceMetric 指向资源指标链，FailedGetExternalMetric 则需对应适配器证据，不能一律归咎负载低。",
                    "读取目标 Pod 实际 requests.cpu/requests.memory，包括 admission 后的值，比较 HPA Resource 或 ContainerResource 指定的容器。CPU Utilization 是相对请求而非节点总核数，无请求或容器名不符可能使指标不可计算。",
                    "若当前权限和客户端支持，有限查询 kubectl top pod -n \"$NS\" --containers；它只反映资源指标，不验证外部指标，也不是 HPA 历史。关联 Pod Ready、启动时间、采样新鲜度与适配器近期错误，不全量枚举外部序列。",
                ),
                "业务延迟高但 CPU 低可能是等待下游，HPA 不一定选错；unknown 也不能解释为零负载。新实例未就绪与缺失样本会使建议更保守，必须保留实际样本覆盖范围。",
                "随意调低 targetAverageUtilization 会突然增加副本与成本；增大 requests 会改变利用率分母和调度位置。重装 metrics-server、关闭 TLS 或给适配器全局权限都不是默认排障动作。",
                "提出修正目标引用、补齐合理请求或恢复已有指标链的最小方案，列出副本上下限、容量和恢复值，经后台审批。没有历史峰值时不建议以瞬时值降低最小副本。",
                "复核 ScalingActive、样本时间与目标请求，观察真实负载变化下 desired/actual 是否一致。只恢复 top 输出不等于业务扩容有效，还需新副本 Ready、服务流量和原延迟证据。",
            ),
            _document(
                "behavior-limits", "HPA 稳定窗口与多指标限速", "k8s",
                "适用于持续顶在 maxReplicas、负载下降却迟迟不缩或频繁扩缩。输入 HPA 行为配置、业务最低冗余、峰值窗口与容量边界，先解释算法再讨论改参数。",
                (
                    "使用授权 SSH kubectl 读取 HPA status 的 current/desiredReplicas、lastScaleTime、ScalingLimited 原因及目标控制器 replicas/Ready；记录 observedGeneration，区分已提出建议与实际扩容尚未完成。",
                    "读取 behavior.scaleUp/scaleDown 的 stabilizationWindowSeconds、policies 的 Pods/Percent/periodSeconds 与 selectPolicy；未指定值按实际 API 版本的默认行为解释，不凭记忆写死所有集群相同。",
                    "逐项核对 metrics 的目标与 currentMetrics。多个指标通常采用较大的副本建议；某项错误而其他项只建议缩容时，控制器会保守跳过缩容，不能用一个低 CPU 图推导可安全下降。",
                    "关联近期建议、副本变更与控制器事件，分开稳定窗口、速率限制、min/max 硬边界和新 Pod Pending。HPA 没有自动增加节点的保证，扩 Pod 受调度和配额约束时需列出对应事件。",
                ),
                "缩容稳定窗口可保留近期较高建议，速率策略限制每段时间允许的变化；两者不同。ScalingLimited=True 可能是正常保护而非故障，需对照业务负载与是否长期饱和判断。",
                "手工 scale 会与 HPA 后续协调竞争；删除 HPA 或把 min/max 改成同值会改变控制权。缩容可能中断长连接、任务或状态成员，PDB 也不保证阻止控制器自身缩副本。",
                "若确需调整，提交原 behavior、目标边界、容量证明、负载验证与恢复参数，经后台审批。先在受控窗口修改一类策略，业务峰值和故障冗余未知时保持原最低容量。",
                "在覆盖稳定窗口的真实采样中比对指标、建议与实际副本，确认没有新 Pending、错误或扩缩振荡。负载发生器与模拟写入须单独获批，不以配置保存成功宣告弹性验证完成。",
            ),
        ),
        color="#06b6d4",
    ),
    _preset(
        "pdb-disruption-budget", "PDB 中断预算",
        "解释驱逐被拒、预算取整与健康计数，区分自愿中断和控制器更新。",
        (
            "PDB 选择器与驱逐预算核验",
            "核对目标 Pod 覆盖、健康计数与允许中断，防止用删除绕过保护。",
            "输入计划维护节点、业务最小健康成员和相关控制器；PDB 不属原生工具，需已选 SSH 和授权 kubectl。"
            "读取 selector、minAvailable/maxUnavailable、unhealthyPodEvictionPolicy 及 status 的 observedGeneration、"
            "expectedPods/currentHealthy/desiredHealthy/disruptionsAllowed。按当前 API 版本解释空 selector，百分比取整"
            "结合控制器规模计算，逐 Pod 检查 Ready 和已有 deletionTimestamp。区分 eviction 拒绝、非自愿节点故障、"
            "Deployment 滚动更新与直接删除，不能承诺 PDB 约束所有中断。维护前先验证剩余故障域和复制仲裁，"
            "不自动降低预算、不使用 force/delete 绕过，给出恢复健康或分批维护的审批建议。",
        ),
        ("PDB 维护门禁员", "专注自愿中断预算与维护可行性，明确预算并非所有故障的保护罩。"),
        (
            _document(
                "eviction-denied", "PDB 驱逐拒绝与健康预算", "k8s",
                "适用于维护返回 Cannot evict pod as it would violate the pod's disruption budget。输入目标节点、待驱逐 Pod UID、最小可用业务成员和维护窗口，不先删 Pod 绕过错误。",
                (
                    "在已选 SSH 且 kubectl 获准时，读取命名空间内相关 PDB 的 selector、minAvailable/maxUnavailable 与 status；原生工具不能 list PDB。记录 observedGeneration，旧状态可能尚未处理新选择器。",
                    "按 selector 关联 Pod 标签、owner UID、Ready 和 deletionTimestamp，检查是否覆盖过宽、遗漏实例或同时命中多个预算。policy/v1 的空 selector 可匹配命名空间全部 Pod，不能沿用旧版空选择器印象。",
                    "对照 expectedPods、currentHealthy、desiredHealthy 与 disruptionsAllowed；百分比按对应规则向上取整，小副本集可能因此无法中断一个。读取 disruptedPods 的时间记录，判断是否仍有未完成驱逐占用预算。",
                    "检查其他副本为何不健康：探针、调度、节点故障或发布中；关联事件与真实成员状态。Ready 仅是预算使用的健康信号，不自动等价数据库投票成员或业务可写，维护仍需应用层确认。",
                ),
                "预算为零通常是当前冗余不足或要求不允许损失；先恢复其他副本比降低保护更安全。多个预算重叠或无控制器 Pod 会增加维护复杂度，不把某一个 disruptionsAllowed 正值当整节点可一次排空。",
                "直接 delete、force drain 或关机并不受同样保护；PDB 不保证抵御非自愿故障，也不约束 Deployment 自身滚动策略。将可用性责任推给预算对象可能造成维护期间多数成员离线。",
                "提交分批驱逐顺序、逐步健康门槛和恢复暂停点，经后台审批后执行。调整预算必须获得业务负责人对临时风险的确认、到期恢复原值；单副本服务无冗余时不能假称无损维护。",
                "每次维护后复查预算、新 Pod Ready 与应用成员健康，确保 previous eviction 已收敛再处理下一项。维护结束恢复临时预算并验证原配置；原生无 PDB 访问时注明管理员提供的验证来源。",
            ),
            _document(
                "budget-design", "PDB 与发布维护保护差异", "k8s",
                "适用于已经有 PDB 仍在发布或故障中损失过多副本，或需要设计维护门槛。输入控制器规模、故障域、业务仲裁和实际中断方式，目标是找保护缺口而不是承诺绝对可用。",
                (
                    "读取控制器 replicas、滚动 maxUnavailable/maxSurge、Pod Ready 与节点分布；通过授权 SSH 读取 PDB selector 及预算字段。必须确认两者指向同一组当前 UID 对应实例，不能只凭名称相近。",
                    "还原中断路径：eviction API、控制器缩容、滚动替换、直接删除或节点失联。获取审批和事件时间；预算只面向自愿驱逐流程，不会阻止所有 Pod 终止，发布门槛需另行设置。",
                    "对候选 minAvailable 或 maxUnavailable 以当前及最小副本数分别计算健康要求，检查百分比向上取整影响；不得同时设置两个互斥字段。对于非控制器集合，要核对该预算表达是否受到 API 支持。",
                    "若版本支持 unhealthyPodEvictionPolicy，辨别 IfHealthyBudget 与 AlwaysAllow 对不健康 Pod 的影响；它不创造新健康副本。将同节点、同可用区的相关故障纳入维护计划，不能只看集群总数。",
                ),
                "PDB、发布滚动预算与应用复制仲裁是三个不同门禁；某项通过不证明其他项通过。全部副本位于同一故障域时，预算无法抵消节点或区域同时失效，必须由真实分布证据支持建议。",
                "过严预算可使维护长期无法进行，过松则让维护消耗全部冗余；为疏通维护直接设零保护会让多个操作者并发驱逐。不要在没有业务最小成员数时照搬通用百分比。",
                "提交预算字段、选中对象清单、发布策略配合、故障域和临时例外期限，经后台审批。恢复方案应保留原选择器与值；已有并发维护须先协调，不能通过逐个审批叠加超出总风险。",
                "按新预算读取 status 并核对实际成员，不为测试保护而默认驱逐生产 Pod。需要演练则审批隔离范围与恢复路径；没有真实驱逐验证时明确仅验证了配置与计算，不声称维护无损。",
            ),
        ),
        color="#0d9488",
    ),
    _preset(
        "resource-quota", "ResourceQuota 资源配额",
        "按硬限额、用量、作用域和计数类资源解释准入拒绝，而非误认为节点容量不足。",
        (
            "命名空间配额拒绝与余量核对",
            "关联 exceeded quota、发布临时副本和存储类配额，避免无依据放宽限制。",
            "输入 namespace、被拒资源和完整脱敏 exceeded quota 错误；仅在已选 SSH 且 kubectl 可用获准时读取 "
            "ResourceQuota，原生工具只能从事件与控制器看到失败线索。比对 spec.hard/status.hard/status.used、"
            "scopes/scopeSelector 与请求中的 requests/limits、PVC storageClass 和 count 资源，分别计算各项余量。"
            "节点有空闲不代表命名空间有配额；发布 surge、失败未清理对象和 admission 默认值都可能消耗额度。"
            "多份配额可同时约束对象，不能简单把 hard 相加。给出等待任务结束、核验遗留对象或有容量证明的调整候选，"
            "任何删除、提额和资源模板修改均审批，禁止随意清理未确认所有权的数据资源。",
        ),
        ("资源配额诊断员", "专注命名空间准入预算、作用域和配额失败证据，不以提额作为唯一答案。"),
        (
            _document(
                "quota-rejection", "exceeded quota 与准入余量", "k8s",
                "适用于 FailedCreate、Forbidden exceeded quota 或新副本迟迟未创建。输入命名空间、失败资源、发布额外副本需求和错误中的 requested/used/limited，区分准入拒绝与调度失败。",
                (
                    "从 Deployment/ReplicaSet 事件取得确切配额名、资源键与时间；尚未创建的 Pod 不会有自身事件，不能只查现有 Pod。记录控制器期望和实际数量，确认缺口来自 FailedCreate 而不是 Pending。",
                    "在已选授权 SSH 上用 kubectl -n \"$NS\" get resourcequota \"$QUOTA\" -o json 读取 hard、used 和 scopes/scopeSelector；ResourceQuota 不受原生工具支持，缺访问即待补证。",
                    "分别核算 requests.cpu、requests.memory、limits.memory、pods 与 count/资源键。CPU m 与核、内存 Ki/Mi/Gi 要统一；used 的更新可能有延迟，不能把瞬时差额当可并发分配保证。",
                    "比较实际 admission 后 Pod 与模板中的资源，包括 init、overhead 和 LimitRange 默认值；检查 rollout surge 与旧副本终止重叠。多份配额命中同一对象时每份都必须满足，不能将配额上限求和。",
                ),
                "exceeded quota 表示命名空间准入预算不足，节点空闲与否是另一层。报 must specify requests 或 limits 常因配额要求资源声明，不宜通过无审批删除配额来消除错误。",
                "盲目增加配额会抢占共享集群容量；直接删除旧副本可能破坏发布可用性，删除 PVC 还可能回收数据。失败任务和终态 Pod 的计数口径应以具体资源配额规则核实，不能按列表长度猜测。",
                "给出最小补充声明、调整滚动临时需求或经负责人认可的提额方案，写明容量来源、原 hard 与恢复值，经后台审批。可清理对象须逐一确认 UID、所有权和保留策略，不批量删除试错。",
                "复查 quota used/hard 与控制器是否成功创建新对象，再核对调度和 Ready；准入恢复不保证节点有容量。报告失败事件是否停止新增、是否仍有其他配额命中以及业务验证范围。",
            ),
            _document(
                "quota-scopes-storage", "配额作用域与存储类计数", "k8s",
                "适用于普通 Pod 可创建而特定优先级或存储请求被拒，或配额余量与直觉不符。输入对象类别、PriorityClass、存储类和空间负责人，避免用 CPU 总量解释所有准入问题。",
                (
                    "通过授权 SSH 读取命名空间全部相关 ResourceQuota 的资源键与 scopeSelector；保留 Terminating、NotTerminating、BestEffort、NotBestEffort 或 PriorityClass 匹配关系，不能忽略作用域直接比较总 Pod。",
                    "对被拒 Pod 核对 priorityClassName、activeDeadlineSeconds、requests/limits 与 QoS 相关声明；原生可读 Pod 不代表可读取 PriorityClass 对象，后者需相应 kubectl 权限，缺少定义应标记未知。",
                    "对 PVC 比较 requests.storage、persistentvolumeclaims 和形如 存储类.storageclass.storage.k8s.io/requests.storage 的专属额度。分别记录请求容量与实际绑定容量，不以 df 剩余空间替代 API 配额。",
                    "检查 count/services、count/secrets 等 API 对象数量类报错，只收集必要计数与配额状态，不读取 Secret 内容。资源清单若不可访问，让管理员提供计数时间和口径，不绕过工具白名单。",
                ),
                "同一命名空间可同时受到一般配额、作用域配额和存储类配额约束；只有对象命中的每个限制均有余量才可能准入。配额约束声明资源或对象计数，不能推导底层存储真实可用容量。",
                "把有状态工作负载改成另一存储类可能创建新卷而不是迁移数据；改变 PriorityClass 可影响抢占和调度次序。为绕过作用域随意改 QoS 或 deadline 会把容量问题变成运行可靠性问题。",
                "提额需业务负责人、共享资源管理员确认后给出各资源键的新旧值、容量证明和撤回条件，经后台审批。涉及 PVC 扩容另核对 CSI 与文件系统支持，不将配额修改冒充卷扩容完成。",
                "复查命中的每份配额与实际对象请求，确认 PVC 或 Pod 已准入并进入预期状态。保留原作用域和用量基线，验证没有波及其他优先级业务；数据读写仍须独立授权验证。",
            ),
        ),
        color="#0891b2",
    ),
    _preset(
        "limitrange-defaults", "LimitRange 与默认资源",
        "追踪准入默认值、请求限额比例与 Pod 级约束，解释模板和实际对象的差异。",
        (
            "LimitRange 准入默认与资源比例诊断",
            "对照实际 Pod 和默认规则定位请求缺失、上限冲突与新旧实例差异。",
            "输入被拒对象、模板资源、准入错误及命名空间；LimitRange 需已选 SSH 的实际授权 kubectl，不能用原生"
            "资源列表假称已查询。对照 spec.limits 的 type、min/max、default/defaultRequest 与 maxLimitRequestRatio，"
            "分别检查 Container、Pod 和 PVC 条目。比对实际 Pod 与控制器模板，承认 limit 在特定准入条件下可能复制为"
            "request，不能断言未填 request 就是零。多份 LimitRange 可能产生交叉限制，已有 Pod 不会因规则修改自动重写。"
            "输出每个容器及 init 的差异、QoS 和配额影响，修默认值或模板前说明新建实例的容量变化并审批。",
        ),
        ("默认资源审查员", "专注 LimitRange 默认注入与准入验证，不把资源默认值当实时使用量。"),
        (
            _document(
                "default-injection", "默认资源注入与新旧 Pod 差异", "k8s",
                "适用于模板未填资源但 Pod 出现 requests/limits、新 Pod Pending 而旧实例正常。输入命名空间、控制器模板、实例创建时间及可取得的准入规则，重点比较对象实际值。",
                (
                    "读取控制器 template 中各应用、init 容器 resources，再读取实际 Pod 的同名字段、overhead 与 QoS；记录 UID 和创建时间，防止把不同 revision 的差异误归为准入默认。",
                    "只有已选 SSH、kubectl 可用且授权时，执行 kubectl -n \"$NS\" get limitrange -o json，按 spec.limits.type 分类 default、defaultRequest、min/max 与 ratio；原生工具无法读取此资源。",
                    "核对未指定 request、只指定 limit 与显式零值的差异；部分路径下 limit 会被复制为 request，LimitRange 也会注入默认。其他 admission webhook 可能改字段，无法取得其证据时不要断言唯一来源。",
                    "按容器与 Pod 计算新请求对节点和 ResourceQuota 的影响，结合 FailedScheduling/FailedCreate；检查 init 和可重启 sidecar 规则的版本支持，避免把所有请求简单相加当准确峰值。",
                ),
                "准入规则只影响创建或受验证的对象，不会批量更新已运行 Pod。新旧实例资源不同可由规则变化时间解释，但需证据；模板未声明不代表实际请求为零，也不代表没有内存限制。",
                "提高默认请求可能让整个命名空间的新任务无法调度；设置过低的默认 limit 可造成 OOM 或 CPU 节流。修改 QoS 可能影响节点压力下的驱逐优先级，不能为了准入通过一律抹掉限制。",
                "优先显式修正该业务模板，列出默认变化与作用范围；修改 LimitRange 则评估所有未来新建实例、配额和容量，经后台审批，保留旧规则与回退模板。现有 Pod 是否重建另行审批。",
                "读取获批创建的新 Pod 实际 requests/limits，确认与批准值一致、配额和调度成功。观察对应 OOM、节流与业务延迟的真实证据，未接入使用指标时只报告声明一致，不承诺性能改善。",
            ),
            _document(
                "range-conflicts", "最小最大值与 limit request 比例拒绝", "k8s",
                "适用于 minimum/maximum 约束或 maxLimitRequestRatio 报错，PVC 扩容被命名空间规则拒绝。输入准确资源键、单位、目标对象类型和现有规则，不把所有错误解释为配额不足。",
                (
                    "从 ReplicaSet 事件、API 错误或 PVC conditions 记录校验消息，分清 CPU、memory、storage 和容器名称；maxLimitRequestRatio 是 limit 相对 request 的比率，不是 CPU 使用率或超卖比例。",
                    "通过授权 SSH 读取每份 LimitRange 的 type 与 min/max/default/defaultRequest，构建单容器、Pod 汇总和 PVC 容量三层约束。多个条目同时生效，不能只读命名排序第一份。",
                    "统一 CPU 核与 m、内存和存储的二进制单位，逐项比较请求不大于限制、最小值不高于实际声明、最大值未突破；注意默认注入后才进行的验证可能使表面合理的模板被拒。",
                    "PVC 规则应结合请求容量、现有绑定容量和是否扩容解释；StorageClass 与驱动扩容支持需授权 SSH 补证。已有 Pod 正常运行不代表同模板现在还能创建，新准入条件可能已改变。",
                ),
                "LimitRange 校验对象声明范围，ResourceQuota 校验命名空间累计预算，两者可以先后拒绝同一变更。修复比率后仍可能超总配额；API 接受容量声明也不代表后端卷已扩容。",
                "为满足比例盲目加大 requests 会耗尽调度预算；为满足 max 降低内存 limit 可能触发 OOM。不能通过另建命名空间绕过规则，也不默认删除已有 PVC 重新申请更小卷。",
                "提交该容器或 PVC 的字段新旧值、所有命中约束和容量验证，经后台审批。规则本身错误时由命名空间负责人批准修正，列出对新建业务的影响；回退不能依赖 Kubernetes 不支持的卷缩小。",
                "验证对象成功准入、实际资源值和相关 quota 状态；PVC 还需 conditions、容量与应用文件系统证据。控制器新实例 Ready 且业务稳定后才结束，仍缺底层存储证据时保留待办。",
            ),
        ),
        color="#0e7490",
    ),
    _preset(
        "affinity-antiaffinity", "亲和与反亲和调度",
        "拆解节点和 Pod 亲和表达式、命名空间范围及拓扑标签导致的不可满足约束。",
        (
            "亲和反亲和约束逐项求交",
            "按真实标签和 topologyKey 解释硬约束不可满足，保留隔离意图。",
            "输入 Pending Pod、期望节点池、故障域和隔离目的；读取 nodeSelector、nodeAffinity 与 podAffinity/"
            "podAntiAffinity 的 required/preferred 条目。节点 selectorTerms 间是或，同 term 内表达式是且；"
            "nodeSelector 与 nodeAffinity 还要同时满足。Pod 间约束核对 labelSelector、namespaces/namespaceSelector、"
            "topologyKey 与实际对端 Pod 分布，区分硬拒绝和软评分。记录 FailedScheduling 的每条过滤原因，"
            "拓扑标签缺失不能当独立故障域。隐藏调度 profile 和 namespace 标签不属当前原生范围时由授权 SSH 补证；"
            "不直接去掉反亲和换取 Running，先说明单节点或单区共置风险并给最小审批方案。",
        ),
        ("亲和约束分析员", "专注节点与 Pod 间调度约束的逻辑和故障域，避免牺牲隔离来消除 Pending。"),
        (
            _document(
                "node-affinity", "节点亲和表达式与候选集合", "k8s",
                "适用于 FailedScheduling 提示 node affinity 或 selector 不匹配。输入 Pod UID、允许节点池、隔离标签的权威来源和期望架构，先计算候选集合而不是修改标签碰运气。",
                (
                    "读取实际 Pod 的 nodeSelector、schedulerName、nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution 和 preferred 条目；模板与实际对象都保存关键字段，注意 admission 可能追加约束。",
                    "将 required 的 nodeSelectorTerms 作为或集合，每个 term 内 matchExpressions/matchFields 作为且；In/NotIn/Exists/DoesNotExist/Gt/Lt 按实际类型解释，nodeSelector 必须同时满足，不能把所有条件都当或。",
                    "读取 nodes 标签、Ready、污点和 allocatable，逐节点记录被哪条硬约束排除。标签缺失要保留原状；不要把节点 hostname、架构和业务池标签混用，软偏好无匹配不应单独阻止调度。",
                    "结合 FailedScheduling 的 CPU、内存、卷拓扑和容忍报错继续求交。scheduler profile 的 addedAffinity 等隐藏条件不是原生可见配置，需已选 SSH 上实际授权工具补证，不能凭候选集为空断言调度器故障。",
                ),
                "IgnoredDuringExecution 表示运行后标签变化通常不会自动驱逐现有实例，所以已有实例仍在不证明新实例也可调度。总余量足够却候选集为空是约束问题，不应归咎集群总容量。",
                "给节点加隔离标签会影响所有使用该标签的工作负载，删除 required 会把业务放入未经允许节点池。自动标注节点、绕过安全隔离和修改 schedulerName 均可能扩大故障。",
                "提出纠正拼写、恢复权威标签或经确认调整单条约束的方案，列出新增候选节点、敏感隔离和原字段，经后台审批。若确需新节点，由容量负责人处理，不能假称原生工具已扩节点。",
                "核对 PodScheduled、实际 nodeName 与批准节点集合，检查对应卷和业务 Ready；记录哪些硬约束仍生效。只看到 Pod 已运行不能证明隔离意图保留，要核对最终节点标签与应用功能。",
            ),
            _document(
                "interpod-affinity", "Pod 间亲和范围与反亲和死锁", "k8s",
                "适用于新副本因 pod affinity/anti-affinity 不满足，尤其是单节点集群或发布 surge。输入控制器、目标 labels、允许命名空间和故障域，分清必须共置与必须分散。",
                (
                    "读取 required/preferred 的 labelSelector、namespaces、namespaceSelector 和 topologyKey；默认命名空间语义按实际 API 确认。namespaceSelector 涉及 namespaces 标签，非原生资源，只有已选 SSH 的授权 kubectl 可补证。",
                    "按标签筛选对端 Pod，记录 namespace、UID、nodeName 和真实拓扑标签值，注意终态、待调度或即将删除的实例。只比较名称前缀不能证明它们是同一个亲和目标集合。",
                    "对 required anti-affinity 逐个故障域检查已存在匹配 Pod，结合副本数和可用域数解释是否无解；单节点上的硬主机反亲和无法放下第二实例，增加 surge 还可能阻塞新版本创建。",
                    "对于 affinity 核对是否有可依赖的首个匹配实例、旧版本标签是否变化及拓扑键是否齐全。将调度事件与节点资源、污点一并比较，不把所有匹配失败都归为某条亲和规则。",
                ),
                "preferred 是评分而非保证；required 则必须满足。反亲和冲突可来自自己控制器的旧副本，也可来自另一个命名空间的共享标签。把 matchLabels 设得过宽可能意外把无关业务纳入互斥。",
                "移除反亲和可能让所有副本落入同一故障域；改标签会影响 Service、策略和其他控制器选择器。不要为了释放一个位置自动删除健康对端实例，更不能在不了解仲裁时重排数据库成员。",
                "审批方案明确调整哪个 term、拓扑域新增还是规则软化、对应故障风险和原模板恢复方法。优先补齐合法容量或修正错误 selector，拓扑迁移与应用下线由负责人协调执行。",
                "核对新 Pod 的节点和对端分布是否同时满足目标规则，观察发布能否继续且业务冗余不下降。调度成功后仍需验证真实故障域分散，不能以多个 Pod IP 当多节点证据。",
            ),
        ),
        color="#6366f1",
    ),
    _preset(
        "topology-spread", "拓扑分布约束",
        "使用 eligible domains、maxSkew 与最小域数解释副本分布和硬约束 Pending。",
        (
            "拓扑 skew 与合格域计数核查",
            "对照标签选择器、域资格和版本字段计算分布偏差，不假设平均分布必然发生。",
            "输入目标 Pod、可用区标签、预期故障域和版本；读取 topologySpreadConstraints 的 maxSkew、topologyKey、"
            "whenUnsatisfiable、labelSelector、minDomains 及节点资格策略。只统计 selector 实际命中的 Pod 和合格域，"
            "将 nodeAffinityPolicy/nodeTaintsPolicy 与节点标签纳入计算；域数低于 minDomains 时按受支持语义解释全局最小值。"
            "DoNotSchedule 是硬限制，ScheduleAnyway 仅影响评分，多个约束还需同时满足。比较新旧版本标签及 "
            "matchLabelKeys，留意 API 版本门控，不用集群总副本平均值代替逐域 skew。提出补齐故障域或修选择器的最小方案并审批。",
        ),
        ("拓扑分布核查员", "专注拓扑域资格、偏差和容量约束，不承诺软分布规则能自动重平衡存量实例。"),
        (
            _document(
                "skew-pending", "maxSkew 与最小域数导致 Pending", "k8s",
                "适用于 FailedScheduling 提示 topology spread constraints，或一个故障域掉线后剩余副本无法扩展。输入 Pod UID、业务容灾目标、集群版本及 topologyKey，不预设可用区数量。",
                (
                    "读取实际 Pod topologySpreadConstraints 的 maxSkew、topologyKey、whenUnsatisfiable、labelSelector 与 minDomains；多条约束分别记录。核对模板与实际值，确认是否由默认调度配置或准入机制增加。",
                    "列出节点对应 topologyKey 标签、Ready、污点与 affinity，建立每个域的合格节点集合。缺少拓扑标签的节点不能当独立域；nodeAffinityPolicy/nodeTaintsPolicy 的支持和默认值应按当前 API 核实。",
                    "用 labelSelector 统计各域实际匹配 Pod，保留版本标签和 owner UID，不直接统计整个命名空间。DoNotSchedule 下计算新增实例后的 skew；合格域数不足 minDomains 时，全局最小值可能按零处理而持续限制调度。",
                    "读取事件并检查资源和卷拓扑，确认是分布限制还是同域容量不足。namespace、调度 profile 或版本门控无法通过原生工具确认时，只可在已选 SSH 上用实际授权 kubectl 补证。",
                ),
                "maxSkew 不是允许每域最多多少个 Pod，而是相对于合格域全局最小值的偏差。某区不可用时降低合格域数量可能使硬分布仍拒绝副本，不能凭总节点余量认定应当可以扩容。",
                "提高 maxSkew 或降低 minDomains 会改变容灾承诺；伪造 zone 标签不能创造故障域。硬约束过严可能降低故障时可用容量，过松则集中风险，必须由业务负责人选择而不是自动降级。",
                "列出补容量、修标签或临时放宽单条约束的真实差异、故障域影响、期限和恢复条件，经后台审批。不能为测试约束直接关闭健康节点，也不绕过卷区域限制强行迁移。",
                "复算实际合格域和每域 Pod 数，确认 PodScheduled 且 Ready；要求最终节点符合批准拓扑而非只看到副本增加。临时降级需在域恢复后复查，但存量 Pod 不一定自动重平衡，重排另行审批。",
            ),
            _document(
                "spread-rollout", "软分布与版本选择器的发布偏差", "k8s",
                "适用于配置了分布仍集中单区、更新中新旧版本分布不一致或发布后未自动均衡。输入控制器 selector、发布 revision、目标域和是否允许软降级，重点核对被计数的集合。",
                (
                    "读取 whenUnsatisfiable=ScheduleAnyway 的约束和 preferred affinity；它们影响调度评分而非保证均匀。比较同节点其他评分、污点和资源条件，不将软约束未达理想分布直接定为调度器错误。",
                    "核对 labelSelector 与 Pod labels、控制器模板是否一致；检查 matchLabelKeys 是否引用 pod-template-hash，以及当前版本是否支持其语义。按 revision 分别统计再与整体统计比较，避免新旧副本互相掩盖。",
                    "记录 topologyKey、maxSkew、minDomains 和节点资格策略；maxSkew 对软规则用于评分而不是简单硬门槛，minDomains 等字段有组合约束，不能把硬规则 YAML 原样复制进软规则。",
                    "检查新建 Pod 的调度时刻与节点状态，现有 Pod 不会因后来新增节点或修复拓扑标签必然迁移。需要解释实际调度 profile 时，由已选授权 SSH 读取有限配置，不假称原生工具支持 scheduler 配置。",
                ),
                "整体三副本分散不保证每个新版本也分散；选择器按版本隔离后可能改善发布分布，却增加对故障域容量的要求。软规则允许其他评分胜出，应把偏差和业务风险区分开。",
                "改标签可能影响 Service 和亲和规则；批量重启以重平衡会消耗可用副本且未必获得更好位置。不要虚构已有 descheduler、云区域感知或自动再平衡平台。",
                "提出调整选择器、修正拓扑键或审批后的分批重建，说明每次同时中断数、容量与停止条件，保留原模板。跨区调度涉及存储和流量费用时需相应负责人确认。",
                "按实际新 Pod UID 与 revision 核对每域分布，业务就绪和剩余故障域容量同时通过才扩大变更。只改变约束但未产生新实例时，交付配置验证并明确行为尚未验证。",
            ),
        ),
        color="#8b5cf6",
    ),
)

_NODE_PLATFORM_PRESETS = (
    _preset(
        "taints-tolerations", "污点与容忍",
        "精确匹配 taint effect 与 toleration 时限，区分调度拒绝和运行中驱逐。",
        (
            "污点 effect 与容忍时限核对",
            "逐条判断容忍是否匹配，保留专用节点、故障和维护隔离含义。",
            "输入节点、Pod UID、隔离用途和首次异常时间；读取节点 taints 的 key/value/effect 与 Pod tolerations "
            "的 operator、effect、tolerationSeconds。Equal 和 Exists 按不同匹配规则判断，空 effect 可覆盖多个效果，"
            "不能只见同名 key 就认定已容忍。NoSchedule 影响新调度，PreferNoSchedule 是软避让，NoExecute 还可能驱逐"
            "已有实例；时限只适用于相应效果。关联节点 Ready/Unknown、自动注入容忍和应用副本分布，不把广泛容忍当节点健康。"
            "识别专用节点还需要 nodeSelector/affinity 保证归属，容忍只是允许而非强制放置。移除污点或加通配容忍均需审批。",
        ),
        ("污点容忍核查员", "专注污点匹配、时限和隔离目的，避免取消维护或故障保护来消除 Pending。"),
        (
            _document(
                "taint-matching", "NoSchedule 与专用节点匹配", "k8s",
                "适用于 FailedScheduling 提示 untolerated taint，或业务误落专用节点。输入 Pod、目标节点池、污点责任人与隔离意图，先确认污点是人为维护还是节点条件自动产生。",
                (
                    "读取 nodes.spec.taints 的 key/value/effect 以及 Ready、Pressure 和时间；读取实际 Pod tolerations，不只看 Deployment 模板。记录 operator 缺省、effect 为空与是否存在无 key 的宽泛 Exists。",
                    "对每条 taint 逐项匹配：Equal 检查 key/value，Exists 不要求 value；effect 未指定的容忍范围更宽。仍有未匹配 NoSchedule 则新调度受阻，PreferNoSchedule 则是评分避让而非绝对禁止。",
                    "结合 FailedScheduling 的其他过滤原因，核对 requests、affinity 和卷位置。已有 Pod 仍留在 NoSchedule 节点符合预期，因为该效果本身不驱逐存量实例，不能因此认为污点不生效。",
                    "检查专用业务是否同时通过 nodeSelector 或 required affinity 限定节点池；容忍仅解除拒绝，不能保证优先或只去该节点。对自动节点条件污点核对真实故障，不能删污点代替恢复健康。",
                ),
                "容忍配置存在不代表匹配成功，也不证明目标节点健康。专用节点隔离通常包含限制他人进入和要求自己进入两个方向，污点与亲和需配合解释，不能把它们视为同一个机制。",
                "添加 operator=Exists 的通配容忍可能允许业务进入控制面或故障节点；去掉污点会影响所有新调度业务。节点磁盘或内存压力时扩大容忍可能让故障恶化，并非安全的资源补救。",
                "只在确认隔离意图后提交精确 key/value/effect 的容忍或节点标签修复，列出新增候选节点、容量与原字段，经后台审批。维护污点解除需维护负责人确认，不能因 Pod 等待自动解除。",
                "核对新 Pod 的 nodeName、节点健康及匹配条件，确认既能落在批准节点又未扩大到禁止节点池。原生列表只能证明声明和调度，业务服务能力仍需实际验证，保留缺少主机证据的限制。",
            ),
            _document(
                "noexecute-eviction", "NoExecute 时限与节点失联驱逐", "k8s",
                "适用于节点失联后 Pod 长时间留存、突然批量终止或加入 NoExecute 后服务下降。输入节点异常起点、目标 Pod UID、应用复制状态和存储身份，先区分 API 对象与实际进程存活。",
                (
                    "读取 taints 的 effect 与 Pod tolerationSeconds，记录 node.kubernetes.io/not-ready、unreachable 等条件和 lastTransitionTime。自动注入值与控制器差异需看实际 Pod，不假设所有 Pod 都固定相同秒数。",
                    "检查同 key 不同 effect 的多条容忍，判断 NoExecute 是无限容忍、定时容忍还是未容忍；NoSchedule 的 tolerationSeconds 不能当作驱逐计时。关联 Pod deletionTimestamp 与事件，不能只按墙钟推算已终止。",
                    "读取 Pod owner、节点和卷引用，查看替代实例是否已经创建并 Ready。节点失联时 API 中删除并不证明旧进程退出，有状态成员可能仍在旧机写入，需已选授权 SSH 或负责人隔离证据。",
                    "区分节点控制器、taint eviction controller 与工作负载协调的证据；控制面配置和控制器日志不在原生列表范围，需实际 SSH kubectl 或节点服务访问。证据不足时标记驱逐机制待核实。",
                ),
                "无限容忍可能保留暂时失联节点上的业务，但延迟故障转移；过短时限会使短暂网络抖动触发大量迁移。对象状态无法单独证明旧实例已停、存储已解绑或业务可安全建立新主。",
                "强删失联节点 Pod 可能造成双实例、双挂载和脑裂；对全节点批量改时限会集中消耗 PDB 之外的非自愿故障冗余。不要把 force delete 作为常规恢复步骤，也不要复用未经隔离的旧卷。",
                "时限调整或受控重建需提交每组业务副本、仲裁、旧进程隔离与恢复办法，经后台审批；无主机隔离证据的有状态实例交数据负责人，观察模式停在建议，不另开连接绕过。",
                "在原节点恢复或隔离后核对 taint 清理、替代实例身份、卷归属及复制健康，防止新旧成员同时服务。未确认旧进程停机时必须保留数据一致性风险，不能仅以新 Pod Ready 宣布闭环。",
            ),
        ),
        color="#c026d3",
    ),
    _preset(
        "health-probes", "健康探针设计与故障",
        "将启动、存活、就绪的不同动作与实际探测协议、阈值和应用生命周期对应。",
        (
            "startup liveness readiness 分支诊断",
            "核对 kubelet 探测路径和触发动作，避免通过关闭探针掩盖应用故障。",
            "输入容器、启动时长、失败事件与真实业务健康端点；读取 startupProbe/livenessProbe/readinessProbe 的协议、"
            "initialDelaySeconds、periodSeconds、timeoutSeconds、failureThreshold 和 successThreshold。startup 成功前延后"
            "其他探针，liveness 失败触发重启而 readiness 影响就绪，不混淆重启因果。核对 HTTP 的 scheme/path/port/host、"
            "TCP 监听、exec 退出码或 gRPC 服务名和版本限制；具名端口并非所有探针都支持。事件只提供线索，"
            "主机 curl 成功不等价 kubelet 到 Pod 的探测路径。先关联启动日志和 lastState，再提出最小阈值或端点修正并审批。",
        ),
        ("健康探针诊断员", "专注探针动作、时间预算和探测位置，不以探针变绿替代业务健康。"),
        (
            _document(
                "probe-restarts", "启动慢与存活探针误杀", "k8s",
                "适用于 Unhealthy、Killing 与 restartCount 持续增长。输入具体容器、正常冷启动分布、发布变化和失败端点，不把 CrashLoopBackOff 本身当根因，也不默认所有重启都由 liveness 引起。",
                (
                    "读取 Pod 各容器 state/lastState、exitCode、reason、启动终止时间和重启增量，关联 Unhealthy/Killing 事件的探针类型。OOMKilled、应用自行退出与 kubelet 探针失败要分别保留支持证据。",
                    "读取 startupProbe 和 livenessProbe 的 initialDelaySeconds、periodSeconds、timeoutSeconds、failureThreshold；startup 存在时成功前不会运行其他探针。用实际启动日志判断预算是否覆盖最慢正常启动，不把相乘公式当精确重启时间。",
                    "核对探测端口、协议、HTTP path/scheme/host 与容器实际监听；exec 需看命令退出语义，gRPC 需确认数字端口、service 和版本支持。受保护端点不能把认证凭据嵌入报告，不能用泄露 header 方式排障。",
                    "有限读取当前容器日志，若缺少上一实例日志仅在已选 SSH 的授权 kubectl 上申请 previous。主机直连或 localhost 探测不等价 kubelet 探测源，缺路径实测时明确待补证，不创建特权调试实例。",
                ),
                "存活端点若检查所有下游可导致下游短故障触发整批重启；启动预算不足可在程序尚正常初始化时误杀。HTTP 200 只表示该健康路由成功，不能证明核心业务或数据一致性。",
                "同时大幅调高阈值会延迟真实死锁发现；取消 liveness 可能让永久挂起实例继续占位。重启丢失现场，且有状态服务恢复重放会进一步延长启动，不能连续删除实例验证猜测。",
                "提交一个探针或端点实现的最小修改、原字段、允许启动时长及真实失败检测延迟，经后台审批。先灰度少量实例，若出现启动超时、业务错误或重启仍增长，按批准恢复模板并保留证据。",
                "观察完整冷启动、startup 转为成功及随后多个 liveness 周期，核对 restartCount 无新增且实际业务可用。仅事件暂未出现不能证明恢复，必须有足够覆盖时间与端点实际响应来源。",
            ),
            _document(
                "readiness-routing", "就绪抖动与服务流量摘挂", "k8s",
                "适用于 Pod Running 但 Ready=False、Ingress 偶发无后端或流量在实例间抖动。输入 Service、目标容器、就绪语义与请求失败时段，分开进程存活和可接收业务流量。",
                (
                    "读取 readinessProbe 的失败/成功阈值、超时和初始延迟，Pod readinessGates 以及 conditions；容器 Ready 与 Pod Ready 不完全等价，额外 gate 未满足时不能只修 HTTP 探针。",
                    "从 events 和有限日志关联 Ready 转换、连接拒绝、依赖超时和发布时刻；与同版本健康实例比较，判断是资源压力、业务过载还是探针路径错误。累计重启不是 readiness 失败的必然结果。",
                    "读取 Service selector、publishNotReadyAddresses、ports 和 Pod label，核对是否被正确选中。EndpointSlice 实际 ready/serving/terminating 条件不在原生范围，仅在已选 SSH 的实际授权 kubectl 下补证。",
                    "核对 preStop、terminationGracePeriodSeconds、deletionTimestamp 与退出过程，确认实例摘流与连接排空的证据。不要把删除 API 成功当作存量长连接已结束，边车或网关传播延迟需各自来源。",
                ),
                "就绪应描述当前实例能否安全接流量；过深的依赖检查可能在下游故障时把所有实例同时摘掉。readiness successThreshold 可抑制抖动，但延迟重新入流，参数需依据业务而非追求绿色。",
                "开启 publishNotReadyAddresses 会改变发现语义，不是通用修复；去掉探针或把所有状态返回成功可向未初始化实例送流量。修改终止宽限期可能中断事务和长请求，不能只用短连接测试判断。",
                "提交端点语义、阈值或排空时序的单项差异、流量影响和原模板恢复方法，经后台审批。若需要后端列表、Ingress 配置或业务探测而当前连接不足，只交付补证任务。",
                "验证 Ready 在完整业务周期内稳定、实际后端集合与期望一致，原请求路径错误消失且排空连接符合批准时长。没有 EndpointSlice 或流量证据时，结论限定为探针与 Pod 状态恢复。",
            ),
        ),
        color="#e11d48",
    ),
    _preset(
        "ingress-certificates", "Ingress 路由与证书",
        "核对入口类、路径匹配、SNI 和证书链，识别边缘 TLS 与后端协议的独立问题。",
        (
            "Ingress host path 与 TLS 证据核对",
            "定位默认证书、路径错配、后端无就绪实例和证书续期缺口。",
            "输入入口域名、请求路径、源位置、预期证书颁发者和批准 Service；读取 ingressClassName、rules、pathType、"
            "backend 与 tls.hosts/secretName 引用，绝不读取 Secret 内容。结合控制器 Pod、事件和 Service 选择器区分"
            "未接管、错误路由、上游协议与后端不就绪。IngressClass、EndpointSlice、Certificate/Issuer 等非原生资源，"
            "只能在已选 SSH 的实际 kubectl 授权下补证。用已有 openssl 的 SNI、主机名及链验证检查公开证书元数据，"
            "不关闭 TLS 校验；区分外部负载均衡终止与 ingress 终止，不能把对象 tls 声明当已部署证书。变更与重载须审批。",
        ),
        ("Ingress 证书诊断员", "专注入口路由和公开证书身份，区分边缘、控制器与上游配置，不读取私钥。"),
        (
            _document(
                "ingress-routing", "Ingress 类接管与路径匹配", "k8s",
                "适用于默认后端 404、同域部分路径错误、502/503 或 Ingress 对象存在但无外部入口。输入 host、原始 path、TLS 终止位置、请求源和预期后端，避免只凭状态码猜根因。",
                (
                    "读取 ingressClassName、rules.host、paths.path/pathType、backend.service.name/port 与 status.loadBalancer；旧 ingress.class 注解需按实际控制器确认，不认为有地址就证明全部规则生效。",
                    "核对 Exact、Prefix、ImplementationSpecific 的语义及重写注解；后者为控制器实现相关，不能套用另一厂商的正则规则。请求 host/SNI、大小写和路径段边界需要与实际错误请求匹配。",
                    "读取目标 Service selector、port/targetPort 与对应 Pod Ready、应用监听日志，区分无后端、错端口和上游 TLS 配置。EndpointSlice 与 IngressClass 非原生支持，需已选授权 SSH kubectl，缺少则明确未验证。",
                    "关联入口控制器 Pod 的部署版本、事件和有限日志，只提取相关 host/path 的脱敏错误。若实际控制器在外部设备或云侧且不可访问，不能假称读取了最终生成配置或完成源路径探测。",
                ),
                "404 可能来自默认后端也可能是应用自身；502 常与上游连接或协议相关，503 可能是无可用后端，但必须由日志确认。不同控制器的注解、重写和证书选择不可混用。",
                "扩大 host 通配、改 pathType 或默认后端会影响其他租户；把服务改公网暴露不是排障捷径。直接修改控制器生成配置可能被覆盖，且绕过声明源，不能默认创建新的入口类抢占路由。",
                "审批方案只修改确认错误的路由或端口字段，列出命中范围、原值、控制器支持和回退方法；涉及 GitOps 时先确认来源。任何 apply、控制器重载与切流都服从后台审批。",
                "在原 host、SNI、path 和源网络复测批准的无副作用请求，核对后端身份与正确状态。对象更新成功仅是声明验证；无法从原源访问时保留端到端待验证，不把另一主机成功冒充恢复。",
            ),
            _document(
                "edge-tls", "SNI 默认证书与续期证据", "k8s",
                "适用于证书过期、域名不符、链不完整或续期任务看似正常但客户端仍报错。输入 FQDN、端口、预期 SAN、终止层和信任根来源，只采集公开证书元数据。",
                (
                    "读取 Ingress tls.hosts、secretName 引用与规则 host，确认 TLS 是否在外部 LB、控制器或应用终止；不读取 Secret、私钥或完整 kubeconfig。记录对象 generation 和事件以便关联传播时间。",
                    "已选授权 SSH 且 openssl 存在时，候选只读探测为 openssl s_client -connect \"$HOST:443\" -servername \"$HOST\" -verify_hostname \"$HOST\" -verify_return_error -brief </dev/null；限定单目标与超时，不使用 -k 或不验证的成功作结论。",
                    "记录握手返回、证书 SAN、notBefore/notAfter、颁发者和链验证错误，区分根不信任、缺中间证书和名称错误。若工具不能输出所需元数据，仅申请有限公开证书查询，不打印会话密钥或私钥。",
                    "如已部署 cert-manager，Certificate、CertificateRequest、Order、Challenge、Issuer 都需授权 SSH kubectl；只看 Ready/Reason、有效期和 challenge 失败元数据。DNS 提供商凭据不可读取，未部署则不虚构自动续期链。",
                ),
                "没带正确 SNI 可能拿到默认证书；对象 tls 引用正确也可能控制器未同步或外部 LB 仍持旧证书。续期颁发成功与最终对外生效是两层，单次某个入口地址成功不能证明所有副本一致。",
                "替换 secretName、切换 issuer 或改 challenge 路径可能影响整个域名续期；关闭校验掩盖中间人风险。不要删除证书资源强制重签，不反复发起 ACME 请求触发频率限制，也不输出内部 DNS 凭据。",
                "提交公开证书链、目标引用、终止层和单点修复差异，经后台审批由证书负责人安全替换或重载；保留上一可信证书与回退路径。私钥交接通过既有安全机制，不经报告或聊天传递。",
                "从原入口使用完整 TLS 与名称验证确认 SAN、有效期和链，比较多个已知入口副本的公开证书身份，检查续期状态与业务路径。无实际握手证据时只报告配置核对，不宣称生产证书已恢复。",
            ),
        ),
        color="#0ea5e9",
    ),
    _preset(
        "coredns-operations", "CoreDNS 服务诊断",
        "围绕插件链、集群域、转发器和缓存解释 SERVFAIL、解析超时及名称漂移。",
        (
            "CoreDNS 插件链与解析范围分析",
            "对照服务发现、Corefile 与原失败源的响应码定位 DNS 服务层问题。",
            "输入完整域名、查询类型、原 Pod 源位置、cluster domain 和失败响应码；读取 CoreDNS 工作负载、Pod、"
            "Service 与事件，区分单节点和跨节点故障。Corefile 所在 ConfigMap、EndpointSlice 及 Pod exec 不是原生能力，"
            "需已选 SSH 上实际 kubectl 与授权，不默认创建测试 Pod。只读检查 kubernetes 的 zone/fallthrough、forward "
            "目标、cache、loop、reload 与错误日志，核对请求是否应由集群内权威插件处理。授权主机已有 dig 才做少量"
            "显式 resolver 查询，并标注源位置；不把主机解析成功当 Pod DNS 恢复，不默认更换公共 DNS 或输出含敏感目标的完整配置。",
        ),
        ("CoreDNS 诊断员", "专注集群 DNS 插件链、上游与响应证据，不把所有解析错误归为网络。"),
        (
            _document(
                "cluster-domain", "集群域与 CoreDNS 服务链", "k8s",
                "适用于 Service 短名失败、FQDN 正常或所有集群域出现 NXDOMAIN/SERVFAIL。输入原查询名、类型、Pod 命名空间、cluster domain 与 resolver 地址，不默认集群域必为 cluster.local。",
                (
                    "读取实际 DNS Deployment/DaemonSet、Pod Ready、Service clusterIP/ports 和事件；由现有标签确认组件，不假设服务名与命名空间固定。区分 CoreDNS 不健康、服务选路失败与查询名字本身错误。",
                    "核对业务 Service 的 namespace、名称、是否 Headless 与相关 Pod Ready；短名扩展受 search 和 ndots 影响。Pod dnsPolicy/dnsConfig 可由原生 Pod 读取，但容器实际 resolv.conf 需原 exec 授权，不能假装已进入容器。",
                    "已选 SSH 的授权 kubectl 可选择性读取 Corefile 非敏感内容，核对 kubernetes 插件 zone、fallthrough、pods 选项与 reload 状态；ConfigMap 和 EndpointSlice 非原生范围，缺权限则列待补证。",
                    "在获准原源且已有工具时，用 dig @\"$DNS_IP\" \"$FQDN\" A +time=2 +tries=1 做有限查询，记录响应码、AA、TTL 和耗时；主机直接访问 ClusterIP 未必可达，失败不得直接归结 CoreDNS 进程。",
                ),
                "NXDOMAIN 表示当前处理链未找到名字，SERVFAIL 表示处理失败，超时则还需路径证据；短名和 FQDN 差异常关联搜索域。仅 CoreDNS Pod Running 不证明 Service 能路由或 kubernetes 插件能同步 API。",
                "把内部查询转发公共 DNS 会泄漏私有名称且未必能解析；硬改 cluster domain 会影响全体服务发现。启用全量 query log 可能产生高 I/O 和业务名称泄露，不应作为默认诊断。",
                "提出修正错误域、恢复 Service selector 或 Corefile 插件配置的最小差异，说明集群影响、灰度与原配置，经后台审批。禁止通过跳过 TLS、扩大 RBAC 或创建特权调试 Pod 绕开证据缺口。",
                "在原失败源复测同类型短名与 FQDN，确认答案属于预期 Service、响应码和延迟稳定；观察 API 同步与 reload 错误不再新增。只在主机验证成功时保留 Pod 侧未覆盖结论。",
            ),
            _document(
                "forward-loop", "CoreDNS 转发循环与上游退化", "k8s",
                "适用于外部域 SERVFAIL、CoreDNS loop 报错退出或偶发解析很慢。输入查询类型、上游 resolver 权威来源、节点配置变化与故障时间，区分集群内部解析和外部转发。",
                (
                    "查看 CoreDNS 容器有限日志和 lastState，记录 plugin/loop、no next plugin found、i/o timeout、no such host 等确切错误；对比内部 Service 域与批准的外部域是否同样失败，限定查询次数。",
                    "通过授权 SSH kubectl 核对 Corefile 的 forward 目标、force_tcp/prefer_udp、health_check、max_concurrent 与 cache 配置，只提必要非敏感字段。CoreDNS 版本不同的选项支持不可凭别处示例直接套用。",
                    "如 forward 引用 /etc/resolv.conf，核对实际挂载和宿主 resolver 是否回指本机 stub 或集群 DNS；主机文件只能在已选授权 SSH 上查看非敏感 nameserver/search 信息，不读取无关网络凭据。",
                    "在可授权位置分别向 CoreDNS 与已确认上游做单目标、带超时的 A/AAAA 查询，比较 UDP/TCP、响应码与缓存 TTL；网络探测需许可。没有源位置或上游访问权限时保留链路待补证，不扫描 resolver。",
                ),
                "loop 检测可发现部分启动期转发循环，不保证排除所有运行期环路；cache 可短暂掩盖上游故障。外部域失败而 kubernetes 域正常更支持转发路径问题，但仍需对应源和时间证据。",
                "随意删 loop 插件可能让循环持续放大；加大并发或缓存可能增加内存、延长陈旧答案。关闭 DNSSEC 或 TLS 验证不是修上游的方法，公共 DNS 也未必被允许访问内部域。",
                "修复已核实的错误转发目标或节点 resolver 来源，提交原值、传播范围、重载策略与回退，经后台审批。若需改 max_concurrent 或 cache 先说明容量和时效权衡，不批量重启全 DNS 副本。",
                "核对进程不再因 loop 退出、reload 生效与上游错误增量，覆盖缓存过期后再从原源验证内部和外部名字。只缓存命中成功不能证明上游已修复，报告未测试的协议与节点。",
            ),
        ),
        color="#0891b2",
    ),
    _preset(
        "cni-network", "CNI 网络数据面",
        "区分 sandbox 创建、IPAM、跨节点转发和策略执行，保留插件与节点差异。",
        (
            "CNI sandbox 与跨节点路径定位",
            "从 FailedCreatePodSandBox 和明确源目标缩小 IPAM、隧道、路由或策略故障。",
            "输入源 Pod/目标 Pod 或 Service、协议端口、节点和失败时间；读 Pod IP、hostIP、nodeName、事件及 CNI "
            "DaemonSet 覆盖，先分 sandbox 创建失败和运行后流量失败。FailedCreatePodSandBox 中的 IPAM 耗尽、插件缺失、"
            "API 超时分别处理，不删除 netns 或 IP 分配记录试错。NetworkPolicy、EndpointSlice、插件 CRD 和 exec 非原生，"
            "需已选 SSH 的实际授权 kubectl；主机网络证据只限选中节点与已有 ip 工具。跨节点异常对照路由、MTU、"
            "封装和节点防火墙，保留同节点成功作为对照但不跳结论。变更 CNI 配置、路由、策略和重启代理全部审批。",
        ),
        ("CNI 网络分析员", "专注 Pod 网络建立与跨节点数据路径，不关闭网络隔离或清空数据面试错。"),
        (
            _document(
                "sandbox-ipam", "Pod sandbox 创建与 IPAM 失败", "k8s",
                "适用于 ContainerCreating、FailedCreatePodSandBox 或某节点新 Pod 全部无 IP。输入 Pod UID、节点、插件类型和近期节点变更；先保留完整脱敏错误链，不把镜像、卷故障混为网络。",
                (
                    "读取 Pod nodeName、podIPs、conditions 与事件中的 failed to setup network、IPAM allocation、plugin not found 或超时；记录 sandbox 尝试时间和影响节点，旧事件不能证明当前仍失败。",
                    "读取 CNI DaemonSet 与各节点实例 Ready、镜像、挂载路径引用及有限日志，比较健康节点。DaemonSet 全覆盖并不证明 CNI 二进制和配置在宿主路径正确，主机实际证据需授权 SSH。",
                    "仅在选定节点且工具获准时，用 ip -br link、ip -br addr 和有限日志看接口与地址，不读取 kubeconfig、token 或完整含凭据的 CNI 文件。只提插件 type、IPAM 类型和明确非敏感字段。",
                    "IP 池、节点 PodCIDR、插件自定义分配资源和状态需相应授权 kubectl；CRD、ConfigMap 并非原生支持。确认池耗尽、泄漏与路由问题的支持证据，没有池状态只能标记疑似而非宣布地址用尽。",
                ),
                "插件无法找到、CNI ADD 超时、IPAM 无可用地址是不同层；已运行旧 Pod 正常可能仅说明故障影响新 sandbox。containerd 重启未必修复地址池，也可能扩大所有容器运行风险。",
                "删除 IPAM 文件、清理 netns 或手动复用地址可能造成重复 IP；重装 CNI、删全体代理或改 PodCIDR 可能中断整个集群。不创建特权调试 Pod，也不通过 hostNetwork 规避原业务网络约束。",
                "提交单节点或单池修复证据、插件官方支持的回收流程、影响和原配置恢复方法，经后台审批。地址清理前必须确认实际使用者与旧 sandbox 生命周期，由网络负责人处理未知占用。",
                "核对获批重建实例取得唯一 Pod IP、sandbox 成功、Ready 及所需网络功能；对原故障节点与健康节点分别比较。无法取得 IP 池或主机证据时，明确未验证分配一致性，不宣布根因已消除。",
            ),
            _document(
                "cross-node-path", "跨节点流量与封装 MTU 判断", "k8s",
                "适用于同节点可达而跨节点超时、大响应挂起或部分 Service 请求失败。输入明确源目标 IP、协议、端口、节点和包大小特征；不扫描网段、不默认抓业务明文流量。",
                (
                    "读取源目标 Pod 的 nodeName、IP、Ready、Service selector 和 targetPort，确认失败目标仍是当前 UID；对照同节点、跨节点与 Service 三种路径，证据必须来自实际源，不用任意主机成功代替。",
                    "CNI 类型、NetworkPolicy、EndpointSlice 与插件路由状态需已选授权 SSH 的实际 kubectl，原生查询不能覆盖。只读列出作用于目标的 selector、方向与端口，不假设没有返回对象就无策略。",
                    "已选 SSH 主机具备 ip 时，候选为 ip route get \"$DEST_IP\"、ip -s link show dev \"$IFACE\" 和 ip -d link show dev \"$IFACE\"；只查询已授权目标，记录选路、MTU、错误增量与封装接口。",
                    "结合已有节点防火墙与插件有限日志，确认 VXLAN/Geneve/BGP 等实际模式后才谈端口或邻居。抓包、主动连通探测需额外限定接口、过滤器、数量和隐私审批，不默认执行 tcpdump 或发送大流量。",
                ),
                "小包成功大包失败支持 MTU/PMTU 假设但不足以定案；跨节点失败也可能是路由、策略、反向路径检查或后端未监听。Service 一部分失败要按实际后端节点分组，避免直接归为 DNS。",
                "全局关闭防火墙、NetworkPolicy 或 rp_filter 会扩大暴露面；改 MTU 可能要求滚动重建网络，临时 route 不一定持久且可能切断 SSH。更不能清空 iptables、nft 或 eBPF maps 试错。",
                "只提交已确认的一条路由、MTU 或策略修正及对等节点要求、回退与失联处置，经后台审批。没有第二管理通路时不冒险修改当前 SSH 所经网络，由网络负责人实施受控维护。",
                "从原源复测批准端口与正常负载尺寸，核对跨节点路径、Service 各后端和错误计数增量。若只验证主机路由，报告限于主机层；不宣称 Pod 网络或策略行为已端到端恢复。",
            ),
        ),
        color="#0284c7",
    ),
    _preset(
        "csi-storage", "CSI 卷生命周期",
        "按供给、控制器附加、节点挂载及扩容阶段核对驱动、拓扑和卷使用身份。",
        (
            "CSI attach mount 与扩容分层诊断",
            "使用卷 handle 引用、CSI 状态和事件定位具体阶段，不强制解绑数据卷。",
            "输入 PVC、Pod、节点、存储驱动及数据负责人；原生先读 PVC phase/conditions/capacity 与 Pod 挂载事件，"
            "将 Pending、FailedAttachVolume、FailedMount 和 FileSystemResizePending 分开。PV、StorageClass、CSINode、"
            "CSIDriver、VolumeAttachment 和快照均需已选 SSH 的实际 kubectl 与授权；只记录必要卷标识，不读取存储凭据。"
            "核对 volumeBindingMode、allowedTopologies、访问模式和旧节点实际卸载，RWO 不简单等于单 Pod。扩容区分请求、"
            "后端容量与文件系统三层，不承诺支持缩容；任何重挂、force detach、扩容或驱动更新先数据保护与审批。",
        ),
        ("CSI 存储生命周期顾问", "专注 CSI 的控制器与节点阶段及卷身份，不把删除 PVC 当挂载修复。"),
        (
            _document(
                "attach-mount", "CSI 附加与节点挂载分界", "k8s",
                "适用于 FailedAttachVolume、Multi-Attach 或 MountVolume.SetUp failed。输入 PVC UID、Pod、节点与数据所有者；优先确定阶段和旧卷使用者，禁止靠强制解绑碰运气。",
                (
                    "读取 PVC volumeName、storageClassName、accessModes、volumeMode、conditions 和 Pod volumes/nodeName/事件。volumeName 关联到具体 PV，不能只用同名 PVC 跨命名空间推断同一卷。",
                    "只有已选 SSH 的授权 kubectl 可读取 PV 的 csi.driver、volumeHandle、nodeAffinity 和 VolumeAttachment 的 nodeName、attached、attachError/detachError；卷 handle 在报告中最小化脱敏，不读取 secretRef 的实际值。",
                    "核对 StorageClass volumeBindingMode 与 allowedTopologies，CSINode 驱动注册和节点 CSI Pod Ready；这些都不在原生支持列表。WaitForFirstConsumer 的 Pending 需结合调度，不直接断言供给器故障。",
                    "attach 成功而 mount 失败时，收集节点驱动有限日志、文件系统错误和权限类报错；旧节点失联要取得进程退出和存储隔离证据。RWO 是节点级写挂载限制，RWOP 等能力需按版本与驱动核实。",
                ),
                "控制面 attached=True 不证明节点文件系统已挂载或应用数据正确；Multi-Attach 可能是正常防护阻止双写。节点插件未注册、拓扑不符与后端权限失败需要各自证据，不宜一起重启。",
                "删除 VolumeAttachment、清理挂载目录、强制卸载或 force detach 可能导致数据损坏；节点已断联不等于数据已停止写。不能把删除 PVC/PV、修改 reclaimPolicy 当常规恢复，更不能读取存储访问密钥。",
                "提交明确卷身份、旧使用者隔离、受支持的单卷恢复流程和停止条件，经后台审批并由存储负责人确认。无旧节点隔离证据时停止强制操作，选择业务保护与等待补证。",
                "复查 VolumeAttachment、PVC 与新节点挂载证据，应用确认所见数据版本和一致性；授权写测试独立审批。只有 PVC Bound 或 Pod Ready 时应说明数据正确性尚未完成验证。",
            ),
            _document(
                "volume-expansion", "CSI 在线扩容与文件系统待完成", "k8s",
                "适用于 PVC 请求已增大但容量不变、FileSystemResizePending 或应用仍报空间不足。输入原容量、目标容量、文件系统和驱动支持证据；不将 API 字段变化当磁盘已经可用。",
                (
                    "读取 PVC requests.storage、status.capacity、conditions 和 resize 事件，比较 Pod 所用 PVC UID；确认该次申请未指向别的卷。记录 Resizing、FileSystemResizePending 或驱动错误出现时间。",
                    "经已选 SSH 的实际授权 kubectl 读取 StorageClass.allowVolumeExpansion、PV capacity、CSI driver 及 external-resizer 相关有限日志；这些超出原生查询，缺失就待补证，不推测所有后端都支持在线扩容。",
                    "区分控制器扩展后端块设备与 kubelet/CSI NodeExpandVolume 的文件系统阶段。volumeMode=Block 与文件系统卷不同；是否需重启 Pod 必须依据驱动和文件系统支持，不能默认删实例就会完成。",
                    "在选中并获准的挂载节点，用已有 df -h、df -i 与 lsblk 核对目标挂载点和设备关系；不做全盘扫描、不读业务数据。扩容配额或后端限额需对应管理员给出证据。",
                ),
                "PVC 请求、PV/后端容量和文件系统可用容量可能处于不同步阶段；文件系统未扩展不一定后端扩容失败。inode 耗尽也不必然随字节扩容自动解决，空间增长后仍要确认增长源。",
                "Kubernetes 通常不支持卷缩小，不能把恢复旧 requests 当可逆回滚；手工运行 resize2fs/xfs_growfs 或改 PV capacity 可能破坏控制器流程。没有备份与存储负责人时不进行设备级修复。",
                "扩容审批明确不可逆容量、费用、配额、数据保护点、驱动支持与失败后的受支持恢复流程。确需重建 Pod 时另审业务中断和成员冗余，不删除 PVC 或用新卷替换冒充原地扩容。",
                "同时核对 PVC/PV 容量、条件清除、目标文件系统和应用可用空间，观察新增 resize 错误。业务写入验证属于写操作需审批；仅获得控制面容量时结论不得延伸到数据面可写。",
            ),
        ),
        control_level="approve", color="#4f46e5",
    ),
    _preset(
        "etcd-operations", "etcd 仲裁与存储",
        "基于成员、Raft 进度、配额告警及快照元数据分析一致性存储风险。",
        (
            "etcd 成员仲裁与空间告警核查",
            "区分 leader 变化、落后成员和 NOSPACE，保护唯一有效数据与恢复链。",
            "输入已确认 endpoints、成员拓扑、版本、证书管理方式与备份负责人；仅用已选 SSH 上现有授权 etcdctl，"
            "连接参数由安全会话提供，不读取或输出凭据。有限查询 endpoint status、member list、alarm list，"
            "记录 cluster/member ID、leader、Raft term/index/applied index、dbSize/dbSizeInUse；endpoint health 会提交提案，"
            "不冒充纯只读检查。根据投票成员数判断法定多数，learner 不计投票，不能凭一个健康端点宣布集群健康。"
            "NOSPACE 先核对后端配额、磁盘与快照，compact/defrag/alarm disarm、成员变更和恢复均写审批，"
            "不在线覆盖数据目录或使用 force-new-cluster 快捷恢复。",
        ),
        ("etcd 一致性顾问", "专注 Raft 仲裁、空间与恢复前置条件，不自动进行成员重建或数据压缩。"),
        (
            _document(
                "raft-quorum", "etcd 成员进度与仲裁丢失", "ssh",
                "适用于 API 存储超时、leader 频繁变化或部分 etcd 成员不可用。输入已授权端点清单、集群版本、成员角色与故障时间，不扫描默认端口找集群，也不复制他人客户端证书。",
                (
                    "现有 etcdctl 的连接和 TLS 参数须由批准的安全会话注入，不在命令中放密码或打印环境；候选只读命令是 etcdctl --endpoints=\"$ENDPOINTS\" endpoint status -w table 与 member list -w table。缺客户端即待补证。",
                    "记录 cluster ID、member ID、isLeader/isLearner、Raft term、raftIndex、raftAppliedIndex 和 errors；比较相同时间采样，跨不同时刻的索引差不能直接量化复制延迟。身份不一致时停止，防止连错集群。",
                    "核对实际投票成员数与可达成员，多数需大于半数，learner 不参与投票；成员清单存在不代表该成员实际存活。只读 endpoint status 不等价线性读或事务成功，etcdctl endpoint health 会提交提案，不能默认当只读。",
                    "在当前选中授权主机看有限 etcd 日志、磁盘延迟和时钟证据，关注 leader changed、apply request took too long、rafthttp 超时。别的成员不可 SSH 就由负责人补证，不推断整集群资源正常。",
                ),
                "少数端点故障但仍有多数与仲裁丢失的恢复策略完全不同；落后成员也可能只是 I/O 暂时拥塞。单个 status 返回成功只能说明该接口可读，不能证明写入或整个集群强一致性服务正常。",
                "误删投票成员会降低剩余容错，多个成员同时重启可丢仲裁；复制活动数据目录不是可靠备份。不能混用不同 cluster ID 的数据，也不默认添加新成员或 force-new-cluster 以绕过保护。",
                "提交成员状态表、法定多数、现有快照证据和单成员恢复顺序，经后台审批并由控制面负责人批准。无多数时进入专门灾难恢复方案，未核实快照与版本前不覆盖数据目录。",
                "逐成员复核相同 cluster ID、稳定 leader 和索引追赶，观察 API 依赖的授权业务请求；真实写健康验证单独获批。仅只读接口恢复时准确限定结论，不能声称已验证所有生产事务。",
            ),
            _document(
                "nospace-maintenance", "etcd NOSPACE 与维护恢复门禁", "ssh",
                "适用于 mvcc database space exceeded、NOSPACE 告警或后端文件持续膨胀。输入 backend quota、磁盘空间、最近可用快照与可接受维护窗口，先区分逻辑存量、空洞和文件系统容量。",
                (
                    "使用已授权现有 etcdctl 的 alarm list 与 endpoint status -w table，记录告警成员、dbSize、dbSizeInUse 和版本；安全会话提供连接，不读取证书私钥或凭据文件。endpoint health 不是本次默认只读步骤。",
                    "在选中成员主机采集 df -h、df -i 和对应日志，核对数据目录挂载点而非仅根盘；后端配额由已有非敏感配置元数据确认。磁盘仍有余量不代表 etcd backend quota 未满。",
                    "比较 dbSize 与 dbSizeInUse 判断可能回收空间，查询最近 compaction/defrag 记录和 snapshot 元数据、校验记录。快照保存会写文件并增加 I/O，不冒充只读诊断；现有快照也需验证格式版本与恢复记录。",
                    "如已有授权指标，核对数据库总量、在用量和写增长；不全量读取 keyspace、业务键值或启用昂贵 hash 检查。找增长来源依赖批准的聚合证据，没有来源不能随意删除 Kubernetes 对象释放空间。",
                ),
                "compaction 清理历史 revision，defrag 才可能回收成员后端文件空洞，两者作用不同；提高 quota 只延缓问题且受磁盘与版本限制。告警解除不代表增长源已消除，须先解决空间与维护条件。",
                "在线 defrag 可阻塞目标成员请求，多个成员并行维护会威胁仲裁；compact 会改变历史读取与 watch 可用范围。禁止删除 WAL、snap 或数据目录，alarm disarm 也不是无风险只读动作。",
                "审批单写明快照保护点、受支持的 compact revision、逐成员 defrag 顺序、leader 与仲裁安排和停止条件。compact、defrag、提额、解除告警及 snapshot save 均需后台审批，失败不盲目重试。",
                "复查每成员文件大小与在用量、磁盘余量、alarm list 和 Raft 追赶，业务依赖恢复且空间增长可解释才结束。保留维护前后证据；未演练恢复时不得把已有快照称为已验证可恢复。",
            ),
        ),
        scope="ssh", control_level="approve", color="#475569",
    ),
    _preset(
        "kubernetes-control-plane", "Kubernetes 控制面",
        "按 API readyz、控制器观察代数和调度链分解控制面退化及多入口差异。",
        (
            "API 就绪与协调调度链诊断",
            "用授权健康端点、工作负载状态和组件日志判断控制面卡点。",
            "输入集群入口、受影响 API 动作、返回码和故障时间；原生先读取 nodes、pods、events 与控制器 "
            "generation/observedGeneration，区分读取可用但写入或协调停滞。readyz/livez、leases、APIServices、"
            "webhook 与组件配置超出原生能力，需已选 SSH 上真实 kubectl 与权限，保留 TLS 验证。有限读取 "
            "kubectl get --raw='/readyz?verbose'，结合 apiserver、controller-manager、scheduler 日志定位 etcd、"
            "准入 webhook、leader election 和调度延迟，不通过已弃用 componentstatuses 判健康。控制面写入、"
            "静态 Pod manifest 修改或证书替换全部审批，不一次重启全副本。",
        ),
        ("控制面诊断员", "专注 API、协调器和调度器的职责边界及多副本证据，不用全量重启掩盖故障。"),
        (
            _document(
                "api-readiness", "API readyz 与准入链退化", "k8s",
                "适用于 kubectl 超时、部分请求 5xx、读取正常但创建失败。输入入口地址、原始 API 路径与动作、错误时间和授权身份，不把 403 当控制面宕机，也不收集完整 kubeconfig。",
                (
                    "用当前原生可读资源确认目标连接，记录错误码、延迟来源和具体对象；服务端缓存、权限、入口 LB 与存储问题需分开。不同入口表现需用已批准地址比较，禁止枚举未知控制面节点。",
                    "已选 SSH 上有授权 kubectl 时，候选为 kubectl get --raw='/readyz?verbose' 和 kubectl get --raw='/livez?verbose'；健康子路径非原生资源，读不到须待补证。结果脱敏，不跳过证书或主机名校验。",
                    "读取 apiserver 有限日志，区分 etcd 超时、admission webhook 无响应、请求限流和认证错误；Mutating/ValidatingWebhookConfiguration、APIServices 需额外资源授权，只读必要 timeoutSeconds、failurePolicy 与引用名。",
                    "对照节点时间、etcd 已有证据和组件资源压力，记录哪一 replica、哪一时间窗出错。readyz 通过只证明该实例检查，不能凭一个 LB 后响应就断言全部控制面或准入写路径可用。",
                ),
                "livez 旨在表明进程是否需要重启，readyz 表示是否可接请求，两者目的不同；API 读成功也不能证明所有 webhook、存储写或聚合 API 正常。禁止依赖已弃用 ComponentStatus 的空结果判健康。",
                "临时把 webhook failurePolicy 改 Ignore 会改变安全准入，删除 webhook 或关 TLS 不是默认恢复。控制面静态 Pod 修改可能立即重建组件，错误配置会切断管理路径，不能全副本并行操作。",
                "针对已证实的单一依赖提交最小差异、剩余健康副本、原配置和失联恢复方案，经后台审批。写路径验证若创建对象也属于写操作，不能用 dry-run 之外的试创建冒充纯只读。",
                "复查各已知入口的 readyz 与有限原失败请求、错误增量和依赖健康；准入写路径经批准测试后单独记录。只读恢复而未经写验证时明确范围，避免宣称整个控制面完全恢复。",
            ),
            _document(
                "coordination-stall", "控制器观察滞后与调度器选主", "k8s",
                "适用于 API 可读但 Deployment 不协调、多个命名空间新 Pod 不调度。输入控制器对象、generation、Pod 首次 Pending 时间及影响范围，区分业务硬约束与协调进程停滞。",
                (
                    "读取多个受影响 Deployment/StatefulSet/DaemonSet 的 generation/observedGeneration、条件和事件时间；单个对象落后也可能是控制器专属错误，需与同类型健康对象比较，不直接诊断全局控制面死锁。",
                    "对新 Pod 查看 nodeName、PodScheduled、schedulerName 与 FailedScheduling；有详细资源/亲和拒绝时先处理约束，完全无新调度事件且跨范围受影响才增加调度链假设。事件过期或无权限需保留限制。",
                    "读取可见的 scheduler/controller-manager Pod Ready、重启和有限日志；leader election 的 Lease、组件配置和静态 manifest 超出原生范围，只有已选 SSH 的真实授权工具可补证。不得读取 kubeconfig 或 token。",
                    "核对 leader 续约失败、API 限流、工作队列错误与主机时钟，记录当前 leader 的来源和更新时间。Lease 存在不代表租约仍有效，缓存旧对象也不能证明当前 leader 正在处理该资源。",
                ),
                "控制器将期望转成实际对象，调度器为未绑定 Pod 选节点；有新 ReplicaSet 无 nodeName 与根本无 ReplicaSet 是不同链路。API 可用不保证协调服务健康，单个 Pod Pending 也不足以证明调度器失效。",
                "直接删除选主 Lease、手改 nodeName 或批量重启组件可能制造协调冲突、掩盖原始错误。不能绕过安全调度与卷约束，也不假设静态 Pod 有常规 Deployment 式回滚。",
                "只对已确认的组件或配置提出维护方案，列明健康副本、选主过渡、原 manifest 和失联处置，经后台审批。一次一个控制面实例，缺少管理入口冗余与备份时先停止执行。",
                "确认 observedGeneration 持续追上新声明、合理 Pod 能获得节点、Lease 新鲜且工作队列错误不再增；业务资源 Ready 与服务探测需另验。不能只因 leader 名称变化就认定故障解除。",
            ),
        ),
        color="#334155",
    ),
    _preset(
        "kubelet-node-agent", "kubelet 节点代理",
        "将节点心跳、驱逐阈值、CRI 和静态 Pod 关联到单节点生命周期故障。",
        (
            "kubelet 心跳与驱逐链诊断",
            "核对 Node 条件、Lease 新鲜度与选中节点服务日志，不批量重启节点代理。",
            "输入节点、Pod 失败阶段和起始时间；原生记录 Node conditions、allocatable、Pod 状态和事件，"
            "再仅在本轮选中该 SSH 节点时用 systemctl show kubelet、journalctl -u kubelet 的有限窗口补证。"
            "Lease、kubelet 配置与证书元数据不属原生范围，需授权实际工具，严禁输出完整凭据或私钥。"
            "区分心跳通信、RuntimeReady/NetworkReady、eviction 阈值、imagefs/nodefs/containerfs 和静态 Pod 失败；"
            "压力信号需结合字节、inode、PID 与真实阈值，不能只看 free。改 eviction、重启服务、清容器文件和证书操作"
            "均先列业务影响并审批，不删除 /var/lib/kubelet 或强制重新注册节点。",
        ),
        ("kubelet 节点诊断员", "专注节点代理心跳、驱逐和运行时接口，不把服务重启当所有节点故障的修复。"),
        (
            _document(
                "heartbeat-runtime", "kubelet 心跳与 CRI 就绪故障", "k8s",
                "适用于 NodeNotReady、Ready=Unknown 或容器不能启动。输入节点身份、异常起点与本轮选中 SSH 是否就是该节点；不能在管理机查看 kubelet 日志后冒称已检查工作节点。",
                (
                    "读取 Node conditions 的 Ready reason/message/lastTransitionTime 和对应 Pod 事件，区分 Unknown 心跳失联与 False 具体健康失败；保存 nodeInfo 的 kubeletVersion、runtimeVersion 和 bootID 等非敏感身份。",
                    "当前确为选中授权 SSH 节点时，用 systemctl show kubelet -p ActiveState -p SubState -p NRestarts -p ExecMainStatus 与 journalctl -u kubelet --since \"$START\" --until \"$END\" -n 150 --no-pager；日志脱敏且时间范围有界。",
                    "识别证书过期、Unauthorized、API 连接超时、PLEG is not healthy、RuntimeReady/NetworkReady 等分支；CRI 可用性需现有授权 crictl，只读版本与状态，不运行清理。Lease 需 SSH kubectl 授权，原生不支持。",
                    "检查 kubelet 到已批准 API 地址的路由、时间同步和运行时服务状态；不扫描端口、不读取 kubeconfig。静态 Pod 镜像、磁盘和 manifest 错误仅取非敏感有限证据，不把 API 镜像 Pod 删除视为宿主静态实例已停止。",
                ),
                "kubelet Active 不代表它能向 API 汇报或 CRI 可用；Unknown 也不能证明主机已经宕机。PLEG 延迟可能是运行时或 I/O 退化，需要时间相关证据，不以单次重启后变绿认定根因。",
                "重启 kubelet 可能影响探针、生命周期协调和静态组件；删除节点对象或状态目录会破坏身份和挂载追踪。证书或网络修复不能跳过 TLS、主机指纹或复用其他节点凭据。",
                "针对确认分支提交单节点服务或配置维护、当前业务与卷清单、原状态、失联通道和恢复办法，经后台审批。控制面节点尤其要证明剩余可用性，无法确认数据成员安全时停止重启。",
                "在多个心跳周期复查 Ready、Lease 新鲜度、CRI 状态和受影响 Pod 的启动/Ready，观察同类错误是否仍增加。主机不可访问时只报告 API 观测，不宣称节点服务已经直接验证。",
            ),
            _document(
                "eviction-thresholds", "kubelet 驱逐信号与保留资源", "k8s",
                "适用于 Evicted、DiskPressure、MemoryPressure 或 PIDPressure 反复出现。输入节点、被驱逐 Pod、实际驱逐信号与业务保留资源，避免将所有磁盘压力视为同一个文件系统。",
                (
                    "读取 Node Pressure 条件、allocatable/capacity 与 Pod 终止消息中的 threshold、available、resource；按 UID 和时间区分历史驱逐。requests/limits 与 Priority 只提供驱逐排序线索，不直接证明进程峰值。",
                    "已选授权 SSH 的该节点可用 df -h、df -i、free -m 与有限 ps 信息补证；nodefs、imagefs、containerfs 是否拆分需实际版本和 CRI 支持，不能套用单盘假设或全盘递归统计。",
                    "只提经授权配置中的 evictionHard/Soft、evictionSoftGracePeriod、evictionMinimumReclaim、systemReserved、kubeReserved 与相关阈值；配置文件可能含敏感内容，不完整导出。缺权限则由管理员提供字段。",
                    "关联 kubelet 日志的 eviction manager、image GC 和容器统计错误，判断是阈值确已触发、指标异常还是资源回收跟不上。没有历史利用率时不量化安全超卖比例，不能把 requests 总和当真实内存。",
                ),
                "Pressure 条件有转换与滞后，瞬时 df 正常不排除先前阈值触发；磁盘字节和 inode、主机与容器写层必须分开。提升阈值容忍度可能减少驱逐但把风险转成节点整体失效。",
                "清 /var/lib/containerd、/var/lib/kubelet、截断数据库或关闭 eviction 可破坏存储与节点稳定。降低系统保留资源会挤压关键守护进程；删除日志也可能丢失事故证据，不能默认执行。",
                "提交已确认增长源的保留策略内清理、容量或资源校准方案，经后台审批，列明路径、原阈值、数据保护和恢复条件。若需维护节点，另查中断预算与存储成员，不能直接 drain。",
                "复查原压力信号、可用字节/inode/PID、驱逐增量及系统服务，覆盖正常负载窗口。单次 Pressure=False 不够，业务副本恢复且增长源得到解释才结束；缺指标时明确后续采样需求。",
            ),
        ),
        color="#64748b",
    ),
    _preset(
        "containerd-runtime", "containerd 运行时",
        "从 CRI 插件、sandbox、镜像快照与垃圾回收分析运行时故障，不混用命名空间状态。",
        (
            "containerd CRI 与快照故障诊断",
            "使用既有 crictl/ctr 的有界只读状态区分服务活跃、插件失败与快照空间问题。",
            "输入选中节点、containerd 版本、CRI endpoint 与失败 sandbox；用 systemctl show 和有限 journalctl "
            "定位插件加载、shim 退出、snapshotter、镜像解包与磁盘错误。主机已有且获准 crictl 时读取 info、"
            "pods 和明确容器 inspect 状态；输出须过滤 env、mount 与认证字段，不完整导出。ctr 管理命名空间默认不等于 "
            "Kubernetes 的 k8s.io，需明确 namespace，ctr 成功不证明 CRI 兼容。核对配置版本、disabled_plugins、"
            "SystemdCgroup 与 kubelet cgroup 驱动一致性，不默认编辑配置、pull 镜像、prune 或重启。删除快照和内容可能破坏活跃容器，所有维护走审批。",
        ),
        ("containerd 运行时诊断员", "专注 CRI 插件、shim 与 snapshotter 证据，禁止以清存储目录恢复容器。"),
        (
            _document(
                "cri-plugin", "containerd 活跃但 CRI 不可用", "ssh",
                "适用于 kubelet 报 runtime unavailable、unknown service runtime.v1.RuntimeService 或 sandbox 创建失败。输入当前节点、版本、已知 socket 与服务起点，不扫描所有 Unix socket 或擅自修改 endpoint。",
                (
                    "在选中授权 SSH 节点执行 systemctl show containerd -p ActiveState -p SubState -p NRestarts -p ExecMainStatus 与 journalctl -u containerd --since \"$START\" --until \"$END\" -n 150 --no-pager，保留插件错误并脱敏。",
                    "已存在且获准的 containerd --version、crictl version 与 crictl info 可核对版本和 RuntimeReady/NetworkReady；info 输出可能带配置，提交报告前仅保留必要字段。命令缺失不安装、不替换远端客户端。",
                    "用现有授权 ctr plugins ls 检查 CRI 与 snapshotter 状态；CRI 插件 ID 和配置结构随 containerd 大版本改变，不能直接套用另一版本键。核对 disabled_plugins 是否禁用了 CRI，不导出 registry auth 等完整配置。",
                    "对照 kubelet 已配置 endpoint、systemd cgroup 驱动与运行时 SystemdCgroup 的实际非敏感值；只读取必要字段。ctr 可操作某 namespace 的容器不代表 kubelet 使用同一 socket 或 CRI API 正常。",
                ),
                "systemd Active 只证明 containerd 主进程活跃，CRI 子插件可能加载失败；unknown service 常指接口版本或插件状态，而连接拒绝更偏 endpoint/进程。NetworkReady=False 也可能来自 CNI，不能都归为 containerd。",
                "直接重启可影响所有容器生命周期与管理；是否保留既有 shim 需实际版本和配置验证，不能承诺零中断。改 cgroup 驱动可能要求节点维护，随意改 socket 可能连接另一个运行时。",
                "提交明确版本匹配的单项配置或客户端修复、受影响 Pod/卷、维护与原配置恢复方法，经后台审批。无剩余业务冗余时不执行全节点重启，也不删除 runtime 状态目录促使重建。",
                "复核 CRI 版本、插件状态、kubelet RuntimeReady 与原有 sandbox 错误增量；新建容器验证属于写操作须单独获批。仅 ctr 输出正常时不能宣布 CRI 或所有业务恢复。",
            ),
            _document(
                "snapshot-content", "镜像解包 snapshotter 与内容空间", "ssh",
                "适用于 failed to unpack image、snapshot not found、no space left 或镜像可下载但容器不能启动。输入节点、镜像 digest、snapshotter、目标挂载点和原始错误，不把网络拉取失败与本地解包混合。",
                (
                    "读取 containerd 与 kubelet 有限日志，区分 resolve/fetch、内容校验、unpack、mount 和 shim 阶段；记录 snapshot key 时脱敏。对照 Pod waiting reason，镜像层下载完成并不保证快照可挂载。",
                    "用 df -h、df -i、lsblk 核对 containerd 数据目录挂载点的字节、inode 和文件系统错误；仅已选授权节点可查，不从根目录做全盘 du，也不读取容器业务文件。",
                    "若现有 ctr 获准，限定 namespace 的候选为 ctr -n k8s.io images ls、ctr -n k8s.io snapshots ls 与 plugins ls；列表有界且记录版本差异，默认 namespace 的空结果不能当 Kubernetes 无镜像。",
                    "对照实际 snapshotter 类型、内核/filesystem 支持与 image GC 记录，检查活跃任务和镜像引用的元数据；不要完整 inspect 泄露 env 或 registry auth。缺少引用关系不能推断某 blob 无用。",
                ),
                "磁盘字节充足但 inode 耗尽仍会解包失败；只读挂载或不支持的文件系统也可能报 snapshot 错误。镜像 digest 相同而仅单节点失败更支持本地路径，但需日志而非直接删除缓存确认。",
                "手工删除 content/blobs、snapshots 或 metadata.db 会破坏引用一致性；ctr 与 CRI 的垃圾回收视角不同，prune 不能视为只读。运行时正在使用的层被删除后可能在下次重启才显现损坏。",
                "审批方案列明真实增长源、保留策略内候选、受支持 GC 或修复方法、可恢复镜像来源与业务影响。不能以清空 /var/lib/containerd 换空间；涉及文件系统错误时由存储负责人接手。",
                "复查空间、inode、snapshotter 错误与既有容器状态；经审批后再验证同 digest 拉取解包和启动。pull 会写缓存且访问仓库，不能默认为只读探测；没有此验证就保留重建能力待证。",
            ),
        ),
        scope="ssh", color="#475569",
    ),
)

_DELIVERY_DATA_PRESETS = (
    _preset(
        "certificate-rotation", "组件证书轮换",
        "核对公开证书有效期、信任链、签发与加载状态，分离 CA 轮换和叶子证书更新。",
        (
            "组件证书期限与轮换链核对",
            "按用途和加载进程核对证书身份、CSR 状态与可信链，不导出私钥。",
            "输入组件、证书用途、公开证书路径、集群安装方式和维护负责人；仅在选中 SSH 上用现有 openssl "
            "x509 的 noout 元数据检查 SAN、issuer、有效期与指纹，不读取私钥、kubeconfig 或凭据。kubeadm "
            "certs check-expiration 只在确属 kubeadm 且现有命令获准时使用，外部 CA 与托管控制面走原管理流程。"
            "区分磁盘已换、进程已重载与实际握手证书；CSR 需授权实际 kubectl，不能默认 approve 未知请求。"
            "核对 kubelet 客户端轮换与 serving 证书用途、时间同步和信任根过渡，所有签发批准、renew、重载、重启及 CA "
            "替换都列兼容和恢复计划走审批，不设置 insecure 或盲删证书目录。",
        ),
        ("证书轮换核查员", "专注公开证书身份、轮换链与进程加载，不接触私钥或自动批准 CSR。"),
        (
            _document(
                "expiry-inventory", "组件证书期限与实际加载身份", "ssh",
                "适用于 x509 certificate has expired、尚未生效或文件已更新但客户端仍报过期。输入组件端点、公开证书用途、安装方式及责任人，只盘点已知路径，不递归搜索凭据目录。",
                (
                    "在选中授权 SSH 主机记录 date -u 与组件版本，确认是 apiserver 服务端、etcd 对等、客户端还是 kubelet serving 证书；不同用途的 SAN、扩展用途和信任链不能混用，先锁定实际报错进程。",
                    "对明确的公开证书文件候选命令为 openssl x509 -in \"$PUBLIC_CERT\" -noout -dates -issuer -subject -fingerprint -sha256 -ext subjectAltName；只读取证书本体，禁止打开 key、kubeconfig 或完整 PEM 包。",
                    "确属 kubeadm 且命令已存在获准时才用 kubeadm certs check-expiration 核对受它管理的证书；外部 CA、托管组件或其他发行版不能假装适用。记录哪些证书由外部管理、哪些不在清单内。",
                    "用现有授权 TLS 客户端向已批准单端点验证名称与链，保留 SNI 和校验；比较握手公开证书指纹与磁盘证书。多副本分别由已知入口核对，不能因 LB 一次返回新证书就认定所有进程已重载。",
                ),
                "磁盘证书有效但实际仍返回旧证书，可能是进程未加载、另一个副本或 TLS 在上层终止；尚未生效还需时钟证据。CA 有效不代表其签发叶子仍有效，客户端和服务端错误要分别定位。",
                "批量 renew 或重启控制面可能中断 API 和 etcd 仲裁；自建新 CA 会使旧客户端失去信任。不能通过忽略时间、关闭验证、复用他人私钥或删除证书目录换取连接。",
                "审批单写明单证书用途、签发责任人、信任兼容、轮换顺序、进程加载方式和安全备份恢复流程；秘密由已有安全机制交付，不放报告。续签、替换、重载和验证性写请求均先获批。",
                "复查公开指纹、SAN、有效期、原客户端校验与组件健康，确认每个受影响副本加载；业务读写按授权另验。只有文件元数据变化时，明确运行时轮换未验证，保留剩余到期项。",
            ),
            _document(
                "csr-ca-transition", "kubelet CSR 与 CA 过渡门禁", "k8s",
                "适用于 kubelet 客户端轮换失败、CSR Pending 或 CA 切换后节点拒绝连接。输入节点身份、证书用途、签发策略及双信任窗口，不把自动批准所有请求当恢复。",
                (
                    "原生读取 Node Ready、kubeletVersion、事件与受影响 Pod 分布；CSR、ClusterRoleBinding、证书签发配置均不在原生支持列表，只有已选 SSH 上实际 kubectl 获准时才能取得非敏感元数据。",
                    "候选查询 kubectl get csr -o json，仅保留 name、username、groups、signerName、usages、expirationSeconds 与 conditions；不打印 request/certificate 的编码内容。判断客户端和 serving 证书 signer，不能批准错用途请求。",
                    "核对请求发起者与目标节点、组织签发流程是否一致，结合 kubelet 有限日志找 rotate certificates、Unauthorized 或信任链错误。Pending 不等于安全，应由签发负责人验证身份和批准条件。",
                    "CA 变更时核对旧新根分发、双信任阶段、各组件客户端和服务端加载顺序；证据只记录公开指纹和版本。kubeconfig、私钥与 token 不读取，不能凭清单声称所有依赖已接受新根。",
                ),
                "客户端轮换与 serving 证书签发是不同链；某 CSR 已 Approved 也可能尚未签发、加载或满足信任。旧根删除太早会让未更新组件失联，延长旧根信任又需要明确安全期限。",
                "盲目 approve、扩大自动签发 RBAC 或重置 bootstrap 凭据会改变身份安全边界；同步轮换全体证书可能让控制面无法相互认证。不要关闭 TLS 或把所有证书复制到别的节点。",
                "CSR 批准必须逐身份、用途和有效期审批，CA 过渡由安全与平台负责人共同给出阶段、回退和停止条件。任何 approve/deny、信任配置修改与服务重载均走后台审批，不绕过 observe。",
                "确认新证书公开身份、实际加载和原身份授权请求成功，同时未知请求仍未获批；检查节点心跳和控制面互信。未覆盖的客户端列表需保留，不能用一个节点恢复代替整个 CA 迁移验收。",
            ),
        ),
        scope="ssh", control_level="approve", color="#be123c",
    ),
    _preset(
        "image-registry", "镜像仓库与分发",
        "针对 manifest、授权、限流和镜像校验错误定位供应链与节点分发环节。",
        (
            "镜像 manifest 与拉取链证据分析",
            "分离镜像引用、权限、证书和节点本地解包问题，保护仓库凭据。",
            "输入完整脱敏镜像引用、批准 digest、节点和事件时间；从 Pod waiting.reason/message、imagePullPolicy、"
            "imageID 与 imagePullSecrets 引用定位 manifest unknown、unauthorized、x509、429 或超时。只记录凭据引用名，"
            "不导出 Secret、docker config 或 registry auth。授权 SSH 上可用已有客户端有限查询批准镜像 manifest 的平台与 "
            "digest，拉取会写缓存不能冒充纯只读；API 请求也受现有授权与限流约束。核对多架构索引与节点 architecture、"
            "可变标签缓存差异和代理镜像源，修复 TLS 或授权通过原管理流程，任何改镜像、登录、push、pull、清缓存和仓库配置变更均审批。",
        ),
        ("镜像分发诊断员", "专注镜像引用、公开元数据和拉取阶段，不读取登录凭据或用非可信镜像替代。"),
        (
            _document(
                "manifest-auth", "manifest unknown 与仓库授权限流", "k8s",
                "适用于 ErrImagePull、ImagePullBackOff 或特定新标签无法分发。输入批准仓库、路径、标签或 digest、目标节点与首次失败时间；已有副本仍服务与新建失败要分开统计。",
                (
                    "读取实际 Pod image、imagePullPolicy、节点 architecture、waiting.reason/message 和事件；保留 manifest unknown、no matching manifest、unauthorized、toomanyrequests 或 x509 的准确分类，不把 BackOff 当根因。",
                    "核对 Deployment 模板与实际 Pod imageID，检查可变标签是否在不同实例得到不同 digest。imagePullSecrets 仅取引用名，ServiceAccount、Secret 或凭据核查非原生且含敏感内容，不读取其值。",
                    "已选授权 SSH 上已有安全认证会话与 manifest 客户端时，有限查询批准单镜像的 manifest/index、digest 和 OS/architecture，不运行 login、不在 URI 放密码、不打开 config.json。没有安全会话就待仓库负责人补证。",
                    "区分 401 的认证挑战、最终 unauthorized 的访问拒绝与 429 限流，记录批准端点返回及重试时点；不使用循环高频请求。证书错误核对公开链和名称，仓库网络探测限单目标，不扫描镜像源。",
                ),
                "标签不存在、平台不匹配与仓库权限不足分别对应引用、构建和授权环节。已缓存旧镜像启动成功不能证明仓库可用或新标签正确；token 刷新与仓库主体权限需凭原授权流程核实。",
                "改为随机公网镜像会引入供应链风险；关闭 TLS、复制拉取 Secret 或输出访问 token 会泄密。反复 pull 不仅写缓存还可能触发限流与磁盘压力，不能当无限只读试验。",
                "提交修正到批准 digest、恢复最小仓库权限或证书链的方案，列出原引用、平台、受影响发布和恢复版本，经后台审批；凭据由仓库安全流程更新，报告不包含密码或签名 URL。",
                "经批准的拉取/重建后核对 Pod imageID、平台与 Ready，确认新拉取错误不再新增，业务使用的是批准构建。只得到 manifest 查询成功时，说明节点实际分发及启动尚未验证。",
            ),
            _document(
                "proxy-cache-integrity", "代理镜像源与 digest 完整性", "ssh",
                "适用于同标签不同节点表现不一、镜像校验失败或代理缓存返回旧版本。输入实际 runtime、批准源、不可变 digest、节点和仓库责任人，不默认禁用代理或清全节点镜像。",
                (
                    "在选中授权节点读取 runtime 版本与有限日志，识别 resolving、fetch、checksum mismatch、unpack 阶段；比较 Kubernetes Pod imageID 和仓库已知 manifest digest，索引 digest 与平台子 manifest digest 不可直接混为同一值。",
                    "仅取现有运行时配置中镜像源 host、mirror 目标和 TLS 验证模式等非敏感字段，禁止输出 auth、header、私钥与完整配置。配置路径和格式按实际版本核对，不递归搜索用户凭据。",
                    "已有授权客户端可查询单镜像公开 manifest/index 平台与层摘要，比较源与批准代理的响应元数据；不写临时认证文件，不执行 push、tag 或登录，不用未经授权的匿名公网镜像替代。",
                    "结合节点时钟、HTTP 缓存/代理元数据、429/5xx 和运行时错误，辨别源不可达、缓存过期和本地内容存储损坏。只读内容列表需限定 namespace 和目标引用，缺校验证据就保留假设。",
                ),
                "同一可变标签可能按拉取策略和缓存时间指向不同构建，digest 才能固定内容身份；平台索引下各架构 digest 不同是正常情况。校验错误可能来自传输、源内容或本地存储，不能直接认定供应链攻击。",
                "修改镜像源会影响节点所有新拉取，禁用证书验证会扩大中间人风险；清缓存可能移除离线恢复依赖。pull、删除缓存与仓库 GC 都改变系统状态，不能夹在只读检查里执行。",
                "审批单列明单节点灰度、批准源和证书、固定 digest、缓存保留及恢复旧配置的方法；全局镜像源切换需供应链负责人确认。必要 pull 和校验写缓存独立说明磁盘与流量影响。",
                "核对实际解析源、可信链、manifest 平台和运行容器 imageID，经批准启动验证应用功能。无真实拉取验证时只报告元数据一致；不能假称已验证每台生产节点或自动完成漏洞扫描。",
            ),
        ),
        color="#7e22ce",
    ),
    _preset(
        "helm-release", "Helm 发布状态",
        "分析 release revision、渲染差异、hook 和 pending 状态，避免暴露敏感 values。",
        (
            "Helm revision 与 hook 失败诊断",
            "对照 release 元数据、实际对象和渲染字段解释失败与资源漂移。",
            "输入 release、namespace、chart/version、批准 values 来源及变更批次；仅在已选 SSH 上已有 Helm 和集群授权"
            "时查询 helm status/history 的有限元数据。helm get all/values/manifest 可能泄露 Secret 与明文值，禁止默认完整输出；"
            "只比较经过脱敏的模板字段与实际控制器。hook Job 需 kubectl 授权，核对 hook-weight/delete-policy、超时与"
            "外部副作用；pending 状态先排除正在进行的真实发布，不删除 Helm Secret 解锁。回滚不保证数据库迁移、"
            "CRD 或 hook 副作用可逆；upgrade、rollback、uninstall、dependency update 及生产渲染写入均走审批。",
        ),
        ("Helm 发布核查员", "专注 release 状态、hook 与声明差异，不自动解锁 release 或泄露 values。"),
        (
            _document(
                "pending-hooks", "Helm pending 与 hook 超时", "ssh",
                "适用于 pending-upgrade、pending-rollback、context deadline exceeded 或 release failed。输入 release、命名空间、实际 Helm 版本、发布流水线负责人及开始时间，先确认是否仍有合法进程在执行。",
                (
                    "选中授权 SSH 有现有 Helm 时，使用 helm status \"$RELEASE\" -n \"$NS\" --show-resources 与 helm history \"$RELEASE\" -n \"$NS\" --max 10；输出可能带自定义 NOTES/description，进入报告前脱敏，只留状态、revision、时间和资源引用。",
                    "对照流水线实际任务、审批记录与 release 更新时间，区分尚在进行、客户端中断和服务端失败。不能用 pending 持续时长单独认定锁死，更不能删除 sh.helm.release 元数据解除。",
                    "有 kubectl 授权时读取相关 hook Job 的执行条件、失败 Pod 和事件，核对 helm.sh/hook、hook-weight、hook-delete-policy 与 activeDeadlineSeconds。Job 非原生支持，不能假称通过 deployments 查询已验证。",
                    "比较普通资源是否创建但未 Ready，Helm wait/timeout 是否与应用启动时间一致；hook 即使删除也可能已改变数据库或发送消息。禁止完整 helm get all/values/manifest 输出 Secret 或业务配置。",
                ),
                "release failed 不等于所有资源未写入，atomic 也不保证外部副作用自动撤销；hook 创建顺序与删除策略可能使失败现场消失。pending 是发布协调状态，必须与实际执行者和资源状态共同解释。",
                "并发运行 upgrade/rollback 或删除存储 release 的 Secret 可能破坏历史与锁；增大 timeout 无法修复模板错误。回滚 hook 可能再次执行非幂等迁移，不能仅凭上一 revision deployed 就认定可安全恢复。",
                "提交当前实际状态、外部副作用、已知可用 chart/values 来源与单次恢复方案，经后台审批。先停止或等待合法发布者，由负责人确认互斥；缺敏感 values 时从安全交付渠道获取，不读取凭据文件。",
                "复查 release revision 状态、目标控制器和 hook 结果，核对实际镜像与批准 chart 字段。业务原路径恢复才验收，release deployed 单独不足；没有实际连接时只交付待执行清单。",
            ),
            _document(
                "render-drift", "Helm 渲染差异与回退边界", "ssh",
                "适用于相同 chart 升级后资源意外变化、手改被覆盖或拟回到旧 revision。输入受影响非敏感字段、chart 校验来源、批准 values 版本和数据库兼容性结论，不导出完整 release 内容。",
                (
                    "用有限 helm history 和现有发布资料确定 chart/version、appVersion 与 revision，区分 chart 版本和应用镜像版本；旧 chart 仍需可验证来源，不运行 helm repo update 或联网拉取作为默认诊断。",
                    "只对获准脱敏输入做离线 helm template 或由负责人提供渲染差异，排除 Secret、明文 env 与凭据；不把生产 helm --debug 输出贴入报告。渲染本身不证明准入和服务端默认值会一致。",
                    "读取实际 Deployment/Service/Ingress 的关键字段与 managedFields 来源，比较 image、selector、resources、ports 和探针。CRD、hook、外部资源不由常规 release 回滚完整覆盖，需分别列出生命周期和所有者。",
                    "检查 immutable 字段、资源 rename、keep policy 与旧 values 复用策略，确认升级选项是否导致沿用过期值；--reuse-values 与 --reset-values 的选择必须基于发布输入，不自动推断。",
                ),
                "声明差异可能来自 chart 模板、values、admission 默认或外部控制器，不应把所有漂移都归于手改。Helm 回退恢复渲染资源的能力与数据库、CRD schema、不可变字段兼容是不同问题。",
                "强制替换、uninstall 再装可能删除服务入口或数据资源；CRD 降级可能损坏存储对象，keep 也不是可靠备份。模板若引用 Secrets，离线输出和差异同样可能敏感，不能为诊断放松脱敏。",
                "审批单明确允许变化字段、chart 来源、values 安全版本、迁移兼容、灰度及恢复方法；upgrade/rollback/uninstall 均按远端写审批。GitOps 管理的 release 要从真实声明源提交，避免控制器反复覆盖。",
                "同时核对 Helm 状态和实际对象字段、Ready 与业务验证，检查有无孤儿资源和不兼容 hook 遗留。只完成离线渲染时写清未验证准入、生产执行和业务，不宣称升级已成功。",
            ),
        ),
        scope="ssh", control_level="approve", color="#4338ca",
    ),
    _preset(
        "gitops-drift", "GitOps 漂移与协调",
        "区分期望提交、控制器健康和实际对象差异，避免手工覆盖被持续协调的资源。",
        (
            "GitOps revision 与实际声明漂移分析",
            "辨别同步失败、健康失败和忽略字段，保护 Git 源与紧急例外期限。",
            "输入实际 GitOps 产品、应用标识、批准仓库路径/提交和目标集群；Argo CD Application、Flux "
            "Kustomization/HelmRelease 等均不在原生资源范围，只由已选 SSH 上真实授权 kubectl/已有 CLI 只读查询。"
            "对照 desired revision、observed revision、conditions、sync/health 与控制器日志，区分未拉取、渲染失败、准入失败"
            "和资源不健康。读取原生工作负载的 managedFields 和非敏感字段，识别 HPA、副控制器及默认值的合法变化；"
            "不读取 Git 凭据、Secret、私有 values。sync/reconcile/suspend、prune、改 Git 或现场 patch 都需审批并有回归声明源计划，"
            "不能把界面 Synced 或一次 kubectl apply 当业务验证。",
        ),
        ("GitOps 漂移分析员", "专注声明来源、协调状态与字段所有权，不用现场补丁对抗持续控制器。"),
        (
            _document(
                "revision-sync", "GitOps 提交同步与健康分离", "k8s",
                "适用于仓库已更新但集群仍旧版本、OutOfSync 或 Flux Ready=False。输入实际产品、应用对象、仓库路径与批准 commit；不能因为资源标签提到 Argo/Flux 就假定已接入专用工具。",
                (
                    "先读取实际 Deployment/StatefulSet 的镜像、generation、conditions 和 managedFields，记录目前运行身份。GitOps CRD 非原生支持，只在已选 SSH 的实际 kubectl 或已有产品 CLI 获准时查状态。",
                    "Argo Application 对照 spec.source/ sources 的 targetRevision、status.sync.revision、sync.status 与 health.status；Flux 对照 source artifact revision、lastAppliedRevision/lastAttemptedRevision 和 conditions。只记录脱敏仓库标识，不含认证 URL。",
                    "按阶段检查源获取、渲染/build、apply 和资源健康，关联控制器有限日志中的认证失败、路径错误、schema、admission 或超时；仓库凭据、Secret 与完整 values 不读取，无法访问仓库只列待补证。",
                    "确认 sync policy、自动 self-heal、prune、suspend 与维护窗口是否按负责人预期设置。Synced 只表示声明差异的视角，Health 异常可能是工作负载探针或依赖，不能不断同步试图修业务故障。",
                ),
                "desired commit、已获取 artifact 与已应用 revision 是不同节点，查错分支或仓库路径会使正确集群看似漂移。多源应用需逐源比对版本，不能用一个 revision 文本证明所有配置已同步。",
                "sync/reconcile 是写操作，prune 可能删除数据与入口；取消 suspend 可能一次应用积累变更。手动修改集群会被 self-heal 覆盖，盲目重试还可能重复运行 hook 或扩大发布。",
                "提交精确 commit、字段差异、prune 清单、不可逆迁移与停止条件，经后台审批再同步；仓库修改也需批准。缺少目标 revision 证据时不执行强制同步，不通过关闭安全准入解决 apply 失败。",
                "核对控制器应用 revision、实际镜像/配置引用与 observedGeneration，再验证业务路径和 hook 结果。只有 Synced/Ready 的状态文本时准确注明控制器判断，业务与外部依赖仍需独立验证。",
            ),
            _document(
                "field-ownership", "字段所有权与紧急漂移收敛", "k8s",
                "适用于 replicas 被改回、服务端 apply conflict 或 ignoreDifferences 隐藏真正偏差。输入字段路径、期望声明源、现场变更时间和所有控制器，重点判断谁应管理字段。",
                (
                    "读取目标原生资源 managedFields 的 manager、operation、time 与字段路径，不输出完整敏感 spec。对照 generation、GitOps 标签与审批记录，区分 HPA 管 replicas、admission 默认及人工 patch。",
                    "通过已选 SSH 的授权工具读取 GitOps 差异规则和协调策略：Argo ignoreDifferences/RespectIgnoreDifferences 或 Flux 对应 patch/healthCheck 行为；具体字段按实际版本核对，不能混用产品配置。",
                    "把 live 对象与批准脱敏渲染结果比较，过滤 status、默认字段和随机生成值，不把 Secret 数据或证书私钥纳入 diff。managedFields 能说明写入管理者，但不能单独证明该写入有业务授权。",
                    "紧急现场修复需确认 self-heal 是否会覆盖，以及 suspend/prune 例外期限；从真实 Git 提交回收补丁的路径必须清晰。原生不支持 GitOps CRD、HPA 或仓库查询时保留依赖字段待补证。",
                ),
                "字段冲突常来自多个管理者同时声明，不能一律用 force-conflicts 接管；忽略差异可以消除噪声也可能隐藏安全偏差。HPA 与固定 replicas 同时由声明管理可能产生循环改写，需要明确所有权边界。",
                "扩大 ignoreDifferences 到整个 spec 会降低审计能力；暂停控制器会积累待执行变更，之后恢复可能集中发布。删除 GitOps 应用时 finalizer/prune 可能连带删除业务，不作为普通解锁手段。",
                "审批方案指定唯一字段所有者、临时例外、有效期、声明源提交和恢复同步顺序；suspend、现场 patch、force apply、Git 写入都走审批。先保留原差异与并发变更，避免覆盖他人更新。",
                "在多个协调周期确认字段不再反复翻转、批准 revision 与 live 一致、临时暂停已恢复；业务与告警继续验证。没有实际协调周期证据时只报告方案或静态差异已核对，不声称漂移闭环。",
            ),
        ),
        color="#7c3aed",
    ),
    _preset(
        "mysql-operations", "MySQL 事务与复制",
        "用受限会话与性能元数据分析锁等待、连接和复制，不查询业务数据或直接终止事务。",
        (
            "MySQL 锁链与复制状态诊断",
            "通过事务年龄、等待元数据与复制线程状态区分阻塞、连接压力及复制中断。",
            "输入实例版本、主从角色、故障时间、允许 schema 和客户端安全连接来源；只在选中 SSH 的现有 mysql "
            "客户端中使用已批准安全会话，不设密码参数、不读取登录文件。查询 SELECT VERSION(), @@read_only, "
            "@@super_read_only 及连接计数；对锁读取 performance_schema.data_lock_waits/metadata_locks 和 "
            "information_schema.innodb_trx 的必要字段，不输出 SQL_TEXT、键值或完整 processlist。MySQL 8.0.22+ "
            "优先 SHOW REPLICA STATUS，旧版按实际语法，GTID、IO/SQL 线程与延迟需一起判断。"
            "KILL、全局参数、跳复制事务、主从提升和写验证均审批，不能用 Seconds_Behind 值承诺零数据损失。",
        ),
        ("MySQL 事务复制顾问", "专注 MySQL 元数据、事务阻塞和复制证据，不读取业务表、不自动杀连接或提升主库。"),
        (
            _document(
                "locks-connections", "MySQL 事务锁与连接耗尽", "db",
                "适用于 Lock wait timeout exceeded、Too many connections 或接口等待升高。输入版本、实例角色、允许查询范围与业务超时起点，不默认 root 权限，也不将数据库名当生产连接证明。",
                (
                    "使用已存在 mysql 客户端的批准安全会话，候选 SQL 为 SELECT VERSION(), @@read_only, @@super_read_only; 与 SHOW GLOBAL STATUS WHERE Variable_name IN ('Threads_connected','Threads_running','Max_used_connections','Aborted_connects'); 不传密码或读取凭据。",
                    "获准时查询 information_schema.innodb_trx 的 trx_id、trx_state、trx_started、trx_mysql_thread_id、trx_rows_locked，限制返回行数；不选 trx_query。长事务年龄是阻塞线索，不是可安全杀掉的授权。",
                    "MySQL 8 用 performance_schema.data_lock_waits 建立 requesting/blocking 事务关系；metadata_locks 只取对象类型、锁模式、状态和线程 ID，不读锁键、SQL_TEXT 或业务参数。旧版本表不存在时明确兼容缺口。",
                    "对照 max_connections、连接池已有聚合指标与阻塞起点，区分活跃执行、空闲持有事务和连接泄漏；不默认 SHOW FULL PROCESSLIST 或导出完整会话。权限不足不提权、不安装诊断插件。",
                ),
                "Threads_connected 高不等于 CPU 忙，Threads_running 和锁链需同时看；空闲事务可能持有锁，单条慢查询也可能只是受害者。只看等待会话无法判断根阻塞事务业务价值和回滚成本。",
                "KILL 连接会触发事务回滚并可能长时间占 I/O；提高 max_connections 会增加内存并压垮数据库。读性能视图也有开销，限制范围和频率，不开通 general log 或全量采集业务 SQL。",
                "提交阻塞链、事务年龄、业务所有者、回滚代价与连接池修复候选，经后台审批。KILL、全局参数和应用重启均是独立写变更；无事务所有者确认时只交证据，不将线程 ID 当操作许可。",
                "用相同有限元数据复核锁等待、活跃连接和错误增量，负责人验证原业务恢复且无异常回滚。没有真实安全会话时报告待补证；仅等待消失不能证明事务结果与业务数据一致。",
            ),
            _document(
                "replication-gtid", "MySQL 复制线程与 GTID 恢复判断", "db",
                "适用于复制停止、延迟增长或读副本返回旧结果。输入实例角色、通道、版本、复制拓扑和允许的数据丢失目标，先确认当前不是被误连的其他实例。",
                (
                    "在授权现有 mysql 安全会话读取 VERSION、server_uuid、read_only 与 super_read_only；MySQL 8.0.22+ 用 SHOW REPLICA STATUS，旧版按实际支持 SHOW SLAVE STATUS。仅保留线程状态、位置、错误码和时间，过滤连接信息与错误中的业务值。",
                    "核对 Replica_IO_Running/Replica_SQL_Running、Last_IO_Error/Last_SQL_Error、Source_Log_File/Read_Source_Log_Pos 与 Exec_Source_Log_Pos；多通道逐项记录，不以一行 Yes 推断全拓扑。",
                    "GTID 模式下对照 Retrieved_Gtid_Set、Executed_Gtid_Set 和源端已授权摘要，区分网络接收与 SQL 应用停滞；集合包含关系与 purged 范围需实际来源，不能只比较字符串长度或最新数字。",
                    "Seconds_Behind_Source 为零、NULL 或突变时结合线程、采样新鲜度、并行 worker 错误与源负载判断；有权限才读取 performance_schema.replication_applier_status_by_worker 的脱敏错误元数据，不查询业务行。",
                ),
                "IO 线程停止可能是连接、认证、TLS 或源 binlog 已清理，SQL 线程停止可能是冲突或执行错误，两者修复不同。延迟数字为零不证明已接收到源的最新事务，更不能承诺切换零丢失。",
                "跳过事务、RESET REPLICA、改 GTID_PURGED 或从错误源接复制可能破坏一致性；提升副本前未隔离旧主会脑裂。禁止把只读开关或一次 SHOW 输出当作安全切换证明。",
                "复制修复需提交准确错误、日志链、可恢复点、源身份、停写/隔离和一致性验证方案，经后台审批。重新初始化、重放、主从切换与验证写入均批准；错误含业务值须脱敏，不复制到工单。",
                "复核接收/应用线程、GTID 追赶和原错误不再新增，由负责人执行获准一致性与业务校验。未取得源端或业务证据时只报告副本线程恢复，不能声称复制零延迟或数据无损。",
            ),
        ),
        scope="db", control_level="approve", color="#0284c7",
    ),
    _preset(
        "postgresql-operations", "PostgreSQL 事务与 WAL",
        "针对阻塞会话、复制槽和 WAL 保留建立只读证据，避免误删日志或强制提升。",
        (
            "PostgreSQL 阻塞与 WAL 保留诊断",
            "用会话元数据、复制位置和槽活动状态区分锁阻塞、落后和空间积压。",
            "输入 PostgreSQL 版本、实例角色、目标数据库与事件时间；仅选中 SSH 的现有 psql 安全会话，"
            "以 -X 避免用户启动脚本，命令不含密码且不读取凭据。只读查询 pg_stat_activity 的 pid/state/"
            "wait_event_type/xact_start 和 pg_blocking_pids，不输出 query 或业务内容。用 pg_is_in_recovery、"
            "pg_stat_replication、pg_replication_slots 核对角色、write/flush/replay LSN 与 restart_lsn，差值须在同时间"
            "与合法角色解释；无写入时 replay timestamp 的年龄不等于真实复制延迟。cancel/terminate、删槽、"
            "checkpoint、改参数和 promote 都走审批，不删除 pg_wal、归档或重置复制状态试错。",
        ),
        ("PostgreSQL WAL 顾问", "专注事务等待、复制与 WAL 保留元数据，保护恢复链和主从角色边界。"),
        (
            _document(
                "pg-blocking", "PostgreSQL 等待事件与长事务阻塞", "db",
                "适用于连接堆积、lock timeout、idle in transaction 或迁移停滞。输入数据库、服务角色、版本和业务时段，不默认读取 SQL 文本、绑定参数或所有用户的连接详情。",
                (
                    "只在选中授权 SSH 的现有 psql 安全会话执行，采用 psql -X -v ON_ERROR_STOP=1，连接由批准机制提供，不含密码或凭据 URI。先 SELECT version(), pg_is_in_recovery(), current_database(); 核对角色与实例。",
                    "有限查询 SELECT pid,state,wait_event_type,wait_event,xact_start,pg_blocking_pids(pid) FROM pg_stat_activity WHERE datname=current_database() ORDER BY xact_start NULLS LAST LIMIT 30; 不选择 query、client 信息或业务参数。",
                    "按 blocking pid 建等待链，区分 Lock、IO、ClientRead 与空闲事务；用同一时间基准计算事务年龄。并行 worker 与后台进程需按 backend_type 版本支持解释，权限隐藏项标未知而不是正常。",
                    "需要锁种类时有限读取 pg_locks 的 pid、locktype、mode、granted，与已知关系元数据关联；不全库反复扫描。对照迁移与应用池聚合证据，阻塞者可能是合法长事务，不以年龄直接判可杀。",
                ),
                "active 不代表正在用 CPU，wait_event 表示等待类型；idle in transaction 可能持锁或保留快照，单纯空闲连接则未必。取消当前语句与终止会话的回滚影响不同，必须由业务事务所有者判断。",
                "pg_cancel_backend 与 pg_terminate_backend 都改变远端执行，不能夹在只读查询里；终止事务可能触发大量回滚、重试和业务重复。开启 log_statement、auto_explain 或导出 query 可泄漏敏感 SQL。",
                "提交阻塞链、事务起点、目标 pid 身份复核、回滚成本及应用修复，经后台审批。处理前重新确认 pid 与 backend_start，防止 PID 重用；无业务确认时停在建议，不扩大数据库权限。",
                "以同样有限元数据复核等待链、连接与错误增量，原业务由负责人验证，确认没有重试风暴。会话消失只是执行结果，不证明事务已按预期提交；未连接时明确待补证而非已验证生产。",
            ),
            _document(
                "wal-slots", "PostgreSQL 复制槽与 WAL 积压", "db",
                "适用于 pg_wal 盘增长、复制断开或逻辑消费停住。输入版本、主备角色、复制槽归属、归档策略和最近恢复点，先保留恢复链，不以清目录释放空间。",
                (
                    "在授权现有 psql -X 安全会话 SELECT pg_is_in_recovery(); 主库查询 pg_stat_replication 的 state、sent_lsn、write_lsn、flush_lsn、replay_lsn 与 sync_state；备库按版本读取 pg_stat_wal_receiver 的必要元数据，不导出 conninfo。",
                    "主库有限读取 pg_replication_slots 的 slot_name、slot_type、active、restart_lsn、confirmed_flush_lsn，版本支持时再看 wal_status/safe_wal_size；记录消费者归属，不猜 inactive 槽就一定废弃。",
                    "在主库同一次采样用 pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn) 估算槽保留字节；物理/逻辑槽意义不同，备库函数与角色限制需遵循实际版本。差值不是文件系统精确占用，也不是恢复时间。",
                    "结合现有 pg_stat_archiver、归档失败元数据与选中主机 df，区分复制槽保留、归档失败和普通增长。备库 pg_last_xact_replay_timestamp 的年龄在源无事务时会增长，不能独立作为延迟值。",
                ),
                "inactive 槽仍可能是合法停机消费者，删槽会使其无法继续原位消费；restart_lsn 卡住可能来自长事务或逻辑解码需求。write/flush/replay 分别代表接收写盘、持久化和应用，不能混作零丢失承诺。",
                "删除 pg_wal、归档或手改控制文件可能使数据库无法恢复；删槽、promote、checkpoint 和修改同步复制配置都是写操作。没有旧主隔离证据不得提升，不能把只读状态当防脑裂机制。",
                "提交槽所有者、保留需求、磁盘余量、可重建消费者方案与恢复点，经后台审批选择扩容、修归档或受控槽处理。容量不可逆及数据重新同步代价须明确，不能默认创建新基线覆盖唯一备份。",
                "复查保留字节增长、归档成功新鲜度、复制 LSN 追赶与磁盘余量，并由消费者确认数据连续。只看到槽 active 或备库流式状态不足，业务一致性和恢复能力未演练就保持未验证。",
            ),
        ),
        scope="db", control_level="approve", color="#2563eb",
    ),
    _preset(
        "redis-operations", "Redis 内存与复制",
        "分析内存淘汰、阻塞客户端和副本角色，避免读取键值、全量扫描或误触发持久化。",
        (
            "Redis 内存策略与副本证据核查",
            "用 INFO 的分区统计区分容量、淘汰和复制中断，不以 PING 证明可写可恢复。",
            "输入 Redis 版本、单机/Sentinel/Cluster 模式、角色和允许实例；仅选中 SSH 的现有 redis-cli 安全会话，"
            "不使用 -a 密码、不读取 ACL 或凭据。有限 INFO memory/stats/replication/persistence 与 CLIENT LIST 的"
            "聚合元数据，禁止 KEYS *、默认 SCAN、MONITOR、业务 GET 或完整慢日志。核对 used_memory、maxmemory、"
            "mem_fragmentation、evicted_keys 增量和策略来源，RSS 高不等于键内存泄漏。复制按 master_replid、offset、"
            "link 状态和持久化状态判断；Cluster/Sentinel 专属元数据需实际模式与授权。CONFIG SET、FLUSH、SAVE、"
            "BGSAVE、切主与清键都写审批，不承诺异步复制零丢失。",
        ),
        ("Redis 内存复制顾问", "专注统计、淘汰与副本角色，不扫描业务键、不默认清缓存或触发持久化。"),
        (
            _document(
                "memory-eviction", "Redis 内存上限与淘汰增长", "db",
                "适用于 OOM command not allowed、延迟升高或缓存命中率下降。输入实例模式、版本、内存策略权威来源和异常时段；Redis OOM 错误与 Linux OOMKilled 不是同一现象。",
                (
                    "仅在选中 SSH 的现有授权 redis-cli 安全会话查询 INFO memory、INFO stats、INFO clients；安全连接不在命令放密码，不读取 ACL 文件或打印认证参数。INFO 返回需过滤不必要主机标识。",
                    "记录 used_memory、used_memory_rss、maxmemory、maxmemory_policy、mem_fragmentation_ratio 与 allocator 指标的版本可用性；RSS/逻辑内存差可能来自分配器、fork、客户端缓冲，不直接认定键泄漏。",
                    "在两个有间隔采样比较 evicted_keys、expired_keys、keyspace_hits/misses、rejected_connections 和 blocked_clients 的增量；累计值不能证明当前正在淘汰，分母为零时命中率记无样本，不报告零或百分之百。",
                    "需要客户端证据时只收集数量、flags 和缓冲聚合，不默认完整 CLIENT LIST 暴露名称地址。禁止 KEYS *、默认 SCAN、MONITOR、业务 GET 和 SLOWLOG GET；这些可能放大负载或泄露命令参数。",
                ),
                "noeviction 下到达上限会拒绝部分写入，淘汰策略则可能损失缓存命中；volatile 类策略还要求可淘汰键具有过期。是否可删取决于业务语义，缓存名称不证明数据可以重建。",
                "提高 maxmemory 可能触发宿主 OOM，清键可能击穿后端；FLUSHALL/FLUSHDB、CONFIG SET 和客户端终止都不是只读。触发 SAVE/BGSAVE 会写盘或 fork，内存紧张时风险更大，不默认执行。",
                "提交容量、策略或客户端缓冲的单项修正、主机余量、后端承载和原参数，经后台审批；删除候选需业务所有者证明可重建和具体范围。没有策略权限时由管理员补字段，不扩大 ACL。",
                "比较相同窗口内内存、淘汰和拒绝增量、主机压力及原业务延迟，确认后端未因缓存变化过载。只看到内存下降不等于恢复；业务与持久数据影响未核实时保留风险。",
            ),
            _document(
                "replication-durability", "Redis 复制偏移与持久化风险", "db",
                "适用于 replica link down、全量重同步频繁或切换后数据疑似缺失。输入模式、当前主副角色、故障时间、数据重要性和已确认恢复目标，禁止默认把 Redis 当无持久性的缓存。",
                (
                    "在现有授权 redis-cli 安全会话只读 INFO replication 与 INFO persistence，记录 role、master_link_status、master_replid、offset、backlog 和重同步状态；不在命令写密码，不读取连接秘密或业务键值。",
                    "对照主副同时间的 replid 与 offset，差值必须在同一复制历史下解释；replid 改变、全量同步或落后时间会影响判断。副本在线不保证已确认最新事务，异步复制无法仅凭连通承诺零丢失。",
                    "核对 rdb_last_bgsave_status、aof_enabled、aof_last_write_status 与重写/fork 元数据，结合有限服务日志和磁盘余量；RDB 成功记录不是实际恢复验证，不主动触发 SAVE 或 BGSAVE 试探。",
                    "确属 Sentinel 时只读取批准主服务的 SENTINEL MASTER/REPLICAS 元数据；确属 Cluster 才有限 CLUSTER INFO/NODES，脱敏拓扑地址。没有对应模式与 ACL 授权就待补证，不能虚构专用故障转移工具。",
                ),
                "副本落后、backlog 不足和链路抖动可能触发全量同步并放大网络与内存；持久化错误可能导致写保护。主副 offset 相同只是在该采样点复制接近，不能证明磁盘持久或所有客户端结果一致。",
                "REPLICAOF、FAILOVER、Sentinel 配置与 Cluster 槽迁移都会改变数据拓扑；强制提升而旧主未隔离可双写。FLUSH、重写 AOF、复制数据文件或删除持久化文件都不是恢复前只读准备。",
                "提交旧主隔离、候选副本历史、持久化和恢复点、客户端路由及失败撤回方案，经后台审批。切主与恢复写验证由数据负责人批准，不把审批通过叙述成已经生产切换。",
                "复核角色唯一、原链路稳定、offset 在同历史下持续追赶、持久化错误不再新增，并由业务验证允许范围的数据一致性。没有恢复演练就不能宣称 RPO 达成，未接实例只交待补证清单。",
            ),
        ),
        scope="db", control_level="approve", color="#dc2626",
    ),
    _preset(
        "mongodb-operations", "MongoDB 副本与查询",
        "基于 hello、复制状态和受限操作元数据诊断选主、oplog 窗口和查询等待。",
        (
            "MongoDB 副本状态与操作等待核查",
            "对照 term、optime、oplog 窗口与有限操作统计，避免暴露文档和查询条件。",
            "输入 MongoDB 版本、副本集/分片角色、预期集合范围和故障时间；仅已选 SSH 的既有 mongosh 安全会话，"
            "命令或 URI 无密码，不读取凭据。使用 db.hello()、rs.status() 的成员状态与 optime，过滤 host 标识；"
            "serverStatus 只取连接、缓存和复制汇总，currentOp 只取已授权有限操作元数据且排除 command/查询内容。"
            "oplog 时间窗口来自实际首尾时间和容量证据，不扫描业务集合，secondary 为主不代表可无损提升。"
            "不默认 explain executionStats、profile、建索引、killOp、stepDown、reconfig 或 compact，所有可能执行/写入"
            "和复制拓扑变更须审批并有版本兼容和旧主隔离方案。",
        ),
        ("MongoDB 副本诊断员", "专注副本成员、复制窗口与操作元数据，不读取业务文档或自动改变投票拓扑。"),
        (
            _document(
                "replica-election", "MongoDB 选主与 oplog 窗口", "db",
                "适用于 NotWritablePrimary、ReplicaSetNoPrimary、成员 RECOVERING 或复制落后。输入集群身份、成员角色、版本和写关注要求，不将 mongosh 连接成功等同副本集多数健康。",
                (
                    "只用选中授权 SSH 的现有 mongosh 安全会话，候选 db.hello() 和 rs.status()；不在 URI 放密码、不打印完整连接信息。保留 setName、term、isWritablePrimary、成员 stateStr、health 与 optime，主机标识最小化。",
                    "比较成员投票配置的已授权元数据与实际可达状态，primary、secondary、arbiter、hidden 的含义不同；仲裁节点没有业务数据，不能计为完整数据副本。配置版本、term 与采样时间需同时记录。",
                    "在有相应本地库读取授权时只取 oplog 首尾时间或使用现有 rs.printReplicationInfo/rs.printSecondaryReplicationInfo 的摘要，不导出 oplog 内容。窗口取决于写入速率，不能以容量大小直接换算固定可恢复小时。",
                    "关联有限 mongod 日志中的 election、rollback、too stale、heartbeat 与网络/TLS 证据；成员落后超过窗口可能需要 initial sync，其 I/O 和网络成本要单列。无日志权限不得推断从未发生回滚。",
                ),
                "无 primary 可能是失去投票多数、连错种子或驱动拓扑陈旧；secondary 可读不代表能接受多数写。复制时间差要结合无新写场景和 optime，不能从单个日期推导数据已完整。",
                "rs.reconfig(force)、stepDown 或移除成员可能造成回滚和脑裂风险；改 writeConcern 可能让错误消失却降低持久性。禁止直接拷贝活动数据目录、删 local 数据或清 oplog 试错。",
                "提交成员投票、候选数据新鲜度、旧主隔离、writeConcern 兼容与恢复点，经后台审批后才调整拓扑。重同步和提升需要数据负责人确认，缺少完整成员证据时保持观察，不强制选主。",
                "复查唯一 primary、稳定 term、成员 optime 追赶、原驱动连接及获准业务一致性；写验证独立审批。仅 rs.status 健康不代表所有分片或业务已恢复，未覆盖角色要明确记录。",
            ),
            _document(
                "query-cache", "MongoDB 操作等待与 WiredTiger 压力", "db",
                "适用于连接耗尽、查询延迟或 WiredTiger cache eviction 持续增加。输入版本、实例角色、允许的数据库范围与实际业务时段，不默认分析集合内容或收集完整查询条件。",
                (
                    "现有授权 mongosh 会话通过 db.serverStatus() 只投影 connections、opcounters、globalLock、wiredTiger.cache 等必要统计；不同版本字段和权限需核对，不把完整输出含拓扑、安全或复制内容粘贴报告。",
                    "若确有 currentOp 权限，以有限条件取活动时长、op 类型、等待锁和操作 ID，显式移除 command、query、client 等敏感字段；不得默认全库 currentOp，也不使用命令文本猜测业务重要性。",
                    "比较 cache bytes in use、dirty bytes、eviction 和 tickets/queue 的受支持统计增量，关联进程 RSS 与磁盘延迟；WiredTiger cache 占满可能是正常利用，需实际等待和淘汰压力而非单比率。",
                    "现有慢查询聚合可由负责人提供脱敏 planSummary、耗时和扫描/返回数量；默认不启 profile，不运行 explain executionStats，因为会真正执行查询。queryPlanner 也需限定已授权查询结构，避免业务条件泄露。",
                ),
                "长操作可能是受害者，锁等待、I/O、扫描和客户端消费慢要分支；连接数高不代表活跃执行高。扫描/返回比需要足够样本与查询形态才能支持索引建议，不能用一条日志自动建索引。",
                "killOp 会改变事务或索引工作，增加 cache 可能压缩宿主可用内存；线上建索引、compact 和 profile 都增加负载或写入。禁止删除 WiredTiger 文件、repair 或重启全成员作为日常优化。",
                "提交具体操作类型、聚合证据、业务所有者和最小索引/连接池/资源候选，经后台审批。任何 killOp、参数、索引和 profiling 变更都写明影响、版本限制、停止与恢复办法，不执行未经批准查询。",
                "比较同业务窗口的等待、cache 淘汰、磁盘和响应时间，确认复制未受修复拖慢；索引效果以授权证据验证。没有真实连接和负载时只输出假设与补证项，不声称生产性能已改善。",
            ),
        ),
        scope="db", control_level="approve", color="#16a34a",
    ),
    _preset(
        "kafka-operations", "Kafka 分区与消费",
        "用分区 ISR、消费者位点和控制器元数据诊断积压与副本风险，不消费业务消息。",
        (
            "Kafka ISR 与消费者位点证据分析",
            "分清日志末端增长、消费暂停和副本不完整，避免重置位点与不洁选主。",
            "输入 Kafka 版本、已批准 bootstrap、topic/group、安全连接来源和时间窗；仅选中 SSH 上已有 Kafka CLI，"
            "认证由既有安全会话管理，不读取 client properties 或命令中的密码。有限 kafka-topics.sh --describe 与 "
            "kafka-consumer-groups.sh --describe 核对 leader/replicas/ISR、CURRENT-OFFSET/LOG-END-OFFSET/LAG，"
            "区分提交位点与真实处理完成；不运行 console-consumer 读取消息。副本少于 min.insync.replicas、离线分区、"
            "KRaft controller 和旧 ZooKeeper 模式按实际版本处理。reset-offsets、reassignment、删除 topic、改 retention、"
            "unclean election 和 broker 重启全走审批，保留消息与幂等边界，不承诺积压归零即无丢失。",
        ),
        ("Kafka 分区消费顾问", "专注分区副本和消费者元数据，不读取消息、不自动重置位点或降低持久性。"),
        (
            _document(
                "consumer-lag", "Kafka 消费位点与积压增长", "db",
                "适用于 lag 增长、消费组反复 rebalance 或业务处理变慢。输入批准 bootstrap、单个 group/topic、CLI 版本和业务处理语义，不使用全 topic 枚举或默认读取消息。",
                (
                    "选中授权 SSH 上已有 CLI 时，候选 kafka-consumer-groups.sh --bootstrap-server \"$BOOTSTRAP\" --describe --group \"$GROUP\"；认证由已批准客户端会话提供，不打开安全 properties、JAAS、keytab 或输出密码。",
                    "按 partition 记录 CURRENT-OFFSET、LOG-END-OFFSET、LAG、consumer-id 和采样时间；未提交位点与负 lag 要结合 retention、事务隔离和 reset 历史解释。位点提交不证明外部事务已完成，不能直接等价业务处理量。",
                    "在间隔采样比较日志增长和提交进度，区分单个热分区、所有消费者停滞与生产激增。组状态/成员查询仅按实际 CLI 版本已有 --state/--members 支持，避免用无限循环高频拉取元数据。",
                    "关联应用已有聚合日志中的 rebalance、max.poll.interval、会话超时和处理错误，不读取业务消息。分区数限制同组可有效并行消费者数量，简单增加实例可能无收益，还需检查下游承载。",
                ),
                "lag 是已提交位点到日志末端的差，不直接表示时间或丢失条数；单个分区落后与全组停滞处理不同。重平衡、停止提交或 exactly-once 事务会改变可见进度，必须以实际客户端语义解释。",
                "reset-offsets、新建组或改 group.id 可能重复或跳过业务，console-consumer 会暴露消息且影响组位点。增大 poll 参数可能掩盖死锁，盲目扩消费者会把下游数据库压垮。",
                "提交组状态、每分区进度、业务幂等与下游容量证据，经后台审批后才扩容、调参数或重置。位点变更须明确目标、范围、预计跳过/重复和恢复记录，不将 --dry-run 计划当已执行结果。",
                "复查同分区进度、rebalance 稳定和业务端到端处理延迟，验证重复与失败补偿；lag 降到零也可能是位点被跳过。未取得业务结果时只报告提交进度恢复，不宣称消息无损。",
            ),
            _document(
                "isr-controller", "Kafka ISR 收缩与控制器证据", "db",
                "适用于 UnderReplicatedPartitions、NotEnoughReplicas 或离线分区。输入 topic、分区范围、复制因子、acks/min.insync.replicas 的权威配置和实际部署模式，不默认使用 ZooKeeper 工具。",
                (
                    "使用现有授权 kafka-topics.sh --bootstrap-server \"$BOOTSTRAP\" --describe --topic \"$TOPIC\"，记录每分区 leader、replicas、ISR 和不可用状态；安全认证通过既有机制，不读取凭据文件，不全集群列举消息内容。",
                    "核对 ISR 是否满足该 topic 的 min.insync.replicas，producer acks 来自应用批准配置，不能从 broker 设置推断所有生产者。副本数量足够但不同故障域不明时保留容灾风险，leader=-1 要优先升级影响。",
                    "KRaft 模式且版本支持时，有限 kafka-metadata-quorum.sh --bootstrap-server \"$BOOTSTRAP\" describe --status；它需要实际控制器访问权限。旧 ZooKeeper 模式使用已有授权元数据来源，不扫描节点或假设新命令可用。",
                    "关联选中 broker/controller 的有限日志、磁盘错误、复制超时与网络指标；读取目标目录 df 不扫描所有日志段。比较 leader/ISR 变化时间和离线副本身份，不能把单 broker 健康当作 quorum 正常。",
                ),
                "ISR 收缩意味着同步副本减少，不一定已丢消息；min.insync.replicas 与 acks 共同影响写成功条件。控制器 quorum 和数据分区 ISR 是两套不同多数/同步语义，必须分别验证。",
                "降低 min ISR 或打开 unclean.leader.election 可恢复表面可写却增加丢失风险；改 retention、删 topic、重新分配分区可能不可逆。不要手删日志段、复制活动目录或并行重启多个关键副本。",
                "审批单明确副本/控制器健康、数据保护、单 broker 操作顺序、重分配节流与停止条件；重启、参数、reassignment 和选主均需后台审批。没有有效副本证据时转入数据恢复，不强推新 leader。",
                "确认 leader 稳定、ISR 回到批准副本集合、离线分区清除，生产消费按授权验证；业务写和读消息需单独批准。只恢复元数据响应时不得声称复制完整、消息不丢或控制器已完全健康。",
            ),
        ),
        scope="db", control_level="approve", color="#1e293b",
    ),
    _preset(
        "rabbitmq-operations", "RabbitMQ 队列与仲裁",
        "核对 ready/unacked、连接背压和 quorum 成员，防止 purge 或重投造成消息损失与重复。",
        (
            "RabbitMQ 队列积压与集群告警核查",
            "从队列类型、确认与资源告警区分消费变慢、连接阻塞和仲裁不足。",
            "输入 vhost、单个队列、版本、队列类型和消息处理语义；只在选中 SSH 上已有获准 rabbitmqctl/"
            "rabbitmq-diagnostics 安全节点会话中查询，不读取 Erlang cookie、管理密码或消息载荷。有限 list_queues 的 "
            "messages_ready/messages_unacknowledged/consumers/state 与 list_channels 聚合，不运行 get、purge 或重投。"
            "比较内存/磁盘 alarm、publish/ack 统计、consumer capacity 和 quorum 成员健康，版本字段缺失只标记待补证。"
            "classic、quorum、stream 的恢复语义不同；忘记节点、reset、策略、重新入群与重启均审批，不能以队列深度下降证明消息已成功处理。",
        ),
        ("RabbitMQ 队列诊断员", "专注确认、资源背压与队列类型，不读取消息载荷或默认清队列。"),
        (
            _document(
                "ready-unacked", "RabbitMQ ready 与 unacked 分流判断", "db",
                "适用于消息堆积、消费者在线却不下降或发布端阻塞。输入 vhost、目标队列、版本、确认方式和消费幂等，先避免将消息投递、确认与业务成功混为一谈。",
                (
                    "在选中授权 SSH 的现有节点 CLI 安全会话，可用 rabbitmqctl list_queues -p \"$VHOST\" name type state messages_ready messages_unacknowledged consumers；输出规模和 vhost 范围事先限定，cookie 与管理凭据绝不读取。",
                    "对目标队列比较两个时间点的 ready/unacked、消费者数和已有 publish/deliver/ack 汇总速率；字段按实际版本支持选取。ready 高可因消费不足，unacked 高可因处理慢、prefetch 或确认丢失，单次计数不能判断流速。",
                    "经授权有限 list_channels 只取 connection 引用、consumer_count、messages_unacknowledged 与 prefetch，不打印用户敏感地址或消息。对照应用聚合错误与确认语义，不使用 basic.get、管理 API get 或消费工具读取载荷。",
                    "核对消费者是否被单活动、优先级、exclusive 或连接反复断开影响，consumer capacity 名称随版本变化需确认；现有 DLX/TTL 策略只取必要元数据，队列深度下降也可能是过期或死信转移。",
                ),
                "投递后仍 unacked 不等于丢消息，确认成功也不自动证明外部数据库事务成功；自动确认语义更要独立业务证据。增加消费者只在队列语义和下游容量允许时有效，不能机械扩容。",
                "purge、delete queue、重投与关闭通道会改变消息结果，重投可能造成重复与顺序变化；大量 unacked 重入队可引发突发负载。禁止读消息来证明内容正常，也不调整 prefetch 掩盖业务死锁。",
                "提交队列类型、确认链、业务幂等、下游容量和单消费者修复方案，经后台审批。任何清队列、扩缩消费者、策略和连接中止都需明确消息损失/重复范围及可恢复记录。",
                "对比 ready/unacked 和确认速率的真实增量、消费者稳定与业务完成量，核对 DLX/TTL 是否改变统计。仅积压减少时报告处理证据不足，不宣称消息无损；无实际会话则待补证。",
            ),
            _document(
                "alarms-quorum", "RabbitMQ 资源背压与 quorum 多数", "db",
                "适用于发布连接 blocked、disk_free_alarm、memory_alarm 或 quorum 队列不可用。输入节点、队列类型、成员拓扑、版本和业务持久性要求，不把重启集群作为默认解除告警手段。",
                (
                    "使用已存在获准的 rabbitmq-diagnostics alarms、status 和 rabbitmqctl cluster_status，限制输出并脱敏；认证使用既有节点安全机制，不打开 .erlang.cookie、环境变量凭据或管理配置。",
                    "记录磁盘/内存 alarm 的节点、阈值与开始时间，选中节点以 df -h、df -i 和有限日志补证。一个节点资源告警可让部分发布连接背压，读取成功不证明生产者仍可发布。",
                    "对已确认 quorum 队列，版本支持并授权时用 rabbitmq-queues quorum_status --vhost \"$VHOST\" \"$QUEUE\" 读取 leader、成员与日志进度；不是 quorum 类型就不套用该命令，缺工具不安装。",
                    "核对在线投票成员和多数、成员磁盘状态及网络分区处理策略的必要元数据；classic mirrored 的旧语义不适用于新版本 quorum。cluster_status 存在节点名不代表各队列获得多数，需要逐目标证据。",
                ),
                "资源背压是在保护存储与节点，解除后仍需找增长源；quorum 多数不可用与单消费者故障不同。镜像/复制配置不能替代真实成员健康，磁盘可用但 Raft 日志异常仍可能阻止服务。",
                "降低 disk_free_limit 或内存水位可把可控背压变成节点崩溃；reset、force_boot、forget_cluster_node 与并行重启可能损坏消息可用性。不能删除 mnesia/队列日志目录或盲目清理持久化文件。",
                "审批单说明资源增长源、持久数据保护、剩余 quorum、单节点顺序和原参数恢复；节点遗忘、队列成员变更与重启须数据负责人批准。没有多数和可恢复数据证据时停止拓扑操作并升级。",
                "复查 alarm 清除、目标队列 leader/多数和日志追赶，再由批准业务发布确认与消费结果验证。测试消息是写入须单独审批；仅节点 Active 或告警消失不能证明所有持久消息完整。",
            ),
        ),
        scope="db", control_level="approve", color="#ea580c",
    ),
)

_HOST_OBSERVABILITY_PRESETS = (
    _preset(
        "nginx-operations", "Nginx 上游与工作进程",
        "按虚拟主机、上游阶段和工作进程资源解释 499、502、504 及平滑加载问题。",
        (
            "Nginx 上游阶段与平滑加载诊断",
            "把错误日志、连接资源与配置来源关联，不用延长超时掩盖上游故障。",
            "输入服务单元、批准 host/path、upstream 和失败时间；在已选 SSH 上读取 systemctl show nginx、有限错误日志"
            "及已有聚合 access 指标，不输出完整带查询参数日志。核对 upstream connect/read timeout、no live upstreams、"
            "too many open files 等错误与 worker 数、连接和 FD 限额。Nginx -T 可能泄密，禁止默认完整导出配置；"
            "nginx -t 可能打开日志等文件，属于需要授权的配置测试而非绝对只读。对照 server_name、location、"
            "proxy_pass URI、upstream TLS/SNI 和 resolver 的明确非敏感字段，不套用错误的斜杠重写规则。"
            "reload、改超时、切 upstream、日志轮转与任何受控测试写入均审批，验证新旧 worker 排空和原请求路径。",
        ),
        ("Nginx 上游诊断员", "专注代理阶段、虚拟主机与工作进程加载，保留上游 TLS 和访问日志隐私。"),
        (
            _document(
                "upstream-errors", "Nginx 499 502 504 的阶段证据", "ssh",
                "适用于客户端中断、上游拒绝连接或响应超时。输入 server_name、批准无副作用路径、upstream 地址来源、故障窗口与日志格式，不从单个状态码直接判断服务器过载。",
                (
                    "选中授权 SSH 用 systemctl show nginx -p ActiveState -p SubState -p NRestarts -p ExecMainStatus 与有限 journalctl -u nginx，错误文件由负责人确认路径后限时限量读取，脱敏查询参数、Cookie、Authorization 和业务响应。",
                    "保留 connect() failed、upstream timed out 的 while connecting/reading response header、no live upstreams 与 too many open files 阶段；499 表示客户端断开，可能是客户端超时或链路，不能直接归为后端错误。",
                    "从已有聚合访问证据比较 request_time、upstream_connect_time、upstream_header_time、upstream_response_time 与 upstream_status；多次尝试可能是数组串，不把横线或多个上游值简单当单次耗时。没有对应 log_format 则待补证。",
                    "仅核对非敏感 proxy_connect_timeout、proxy_read_timeout、proxy_next_upstream、resolver 与后端 TLS/SNI 字段；不默认 nginx -T 完整导出。单目标带超时的批准业务探测保留证书验证，不发可能重复写入的请求。",
                ),
                "连接失败偏向监听、选路或 TLS，读头超时偏向上游处理；request_time 含客户端收发，不等于后端执行时间。重试可能把一次请求变成多次上游执行，业务幂等需单独确认。",
                "一味增大 timeout 会占用更多连接；开启非幂等请求重试可能重复支付或写库。禁用 upstream TLS 验证或把错误路径直接暴露公网不是修复，抓全量访问日志可能泄露业务数据。",
                "提交确认阶段的单项 timeout、端点、解析或应用修复建议，列出原字段、连接预算、幂等和回退，经后台审批。nginx -t 可能打开文件，配置校验与 reload 都需明确授权，不默认执行。",
                "比较原 host/path 的实际状态与阶段耗时、上游错误增量及连接占用，确认没有把超时延后而已。只能读日志未能从原源请求时，报告证据边界，不声称全部用户路径已恢复。",
            ),
            _document(
                "workers-reload", "Nginx worker FD 与平滑加载", "ssh",
                "适用于 reload 后仍旧配置、worker 长时间不退出或 too many open files。输入 systemd 单元、master/worker PID、配置版本和长连接类型，避免把 reload 信号成功视为配置已生效。",
                (
                    "从 systemctl show nginx -p MainPID -p LimitNOFILE -p ActiveState 和有限 ps 的 pid/ppid/lstart/comm 建 master-worker 关系，不打印进程 args 或环境。按实际 PID 读取 /proc/PID/limits，仅记录文件描述符上限。",
                    "核对 worker_connections、worker_processes、worker_rlimit_nofile 的非敏感已知配置，单 worker 连接预算还受 OS FD 限制；代理一条业务连接可能同时占客户端和上游 FD，不能机械相乘得到精确容量。",
                    "读取有限错误日志的 reconfiguring、start worker、gracefully shutting down 与配置失败，比较新 worker 起始时间。reload 失败时旧 worker 可继续服务，不能因 nginx Active 就认定新声明被加载。",
                    "已有授权连接统计可按监听端口和 PID 聚合，避免全量 peer 地址泄露；核对 WebSocket、长轮询与 worker_shutdown_timeout。nginx -T 完整配置和 /proc/environ 不读取，确需 -t 校验先说明其文件访问行为。",
                ),
                "旧 worker 长期存活可能是在排空长连接而不是内存泄漏；FD 上限分 systemd、进程和 Nginx 配置层，修改一层不一定作用于已有进程。虚拟主机命中还要看 host/SNI，不能只测默认站点。",
                "强杀旧 worker 会断长连接，restart 相比 reload 更可能产生空窗；调大 worker_connections 可能把压力转给上游和内核。配置校验、日志 reopen 与轮转也不是无副作用的默认检查。",
                "审批方案明确进程层限额、配置差异、内存与 FD 容量、长连接排空上限和原配置恢复；reload/restart 或 systemd drop-in 修改均先获批。不要在无备用入口时重启唯一代理。",
                "确认新 worker 加载批准配置、旧 worker 按窗口退出、FD 余量与连接错误改善，并验证原虚拟主机及长连接行为。只 MainPID 未变或 reload exit 0 不足以验收，保留未覆盖协议。",
            ),
        ),
        scope="ssh", color="#15803d",
    ),
    _preset(
        "haproxy-operations", "HAProxy 后端与队列",
        "结合 stats、终止标志、健康检查和 master-worker 加载解释代理排队与路由故障。",
        (
            "HAProxy 后端状态与排队证据核对",
            "用 qcur、scur、check_status 和进程代际区分容量、检查与加载问题。",
            "输入 frontend/backend、服务 PID、允许状态接口和失败窗口；只在选中 SSH 使用已有获准工具，Runtime API "
            "仅允许 show info/show stat/show servers state 的只读子集，socket 授权不等于可执行 set/disable。"
            "统计 backend/server 的 status、qcur/qmax、scur/slim、econ/eresp、check_status 与 lastchg，"
            "按版本核对 HTTP/TCP 模式与健康检查路径/SNI，不以 UP 证明业务功能。比较日志计时与 termination_state，"
            "日志不得输出认证头和业务参数。haproxy -c -f 仅在批准已知配置路径并评估读取证书与副作用后校验，"
            "禁止完整导出配置或私钥。reload、runtime 状态切换、权重、超时与持久化均审批，验证长连接排空。",
        ),
        ("HAProxy 后端诊断员", "专注代理队列、检查原因与进程加载，限制 Runtime API 为明确只读命令。"),
        (
            _document(
                "backend-queues", "HAProxy 后端 DOWN 与请求排队", "ssh",
                "适用于 503、队列增加、连接失败或 server DOWN。输入 frontend/backend 名、监听协议、受控 stats 来源与故障窗口，不通过开放管理 socket 或 stats 公网端口来获取证据。",
                (
                    "已选授权 SSH 上读取有限服务日志和 systemctl show haproxy 状态。若已有受控 Runtime API 且工具存在，只申请精确 show info、show stat；不把整个 socket 当只读，禁止 set weight、disable server 等写命令。",
                    "按指定 backend/server 筛选 status、qcur/qmax、scur/slim、econ/eresp、check_status、check_duration、lastchg；统计字段随版本核对。BACKEND 汇总与单 server 行不能混加，累计错误要看时间增量。",
                    "核对 mode http/tcp、option httpchk/http-check、预期状态码、check port、inter/rise/fall 和 TLS SNI 的已批准非敏感字段。L4CON、L6RSP、L7STS 指向不同阶段，不能一律放宽健康检查。",
                    "如果已有脱敏日志，比较队列、连接和响应计时与 termination_state，按实际版本格式解释；不要输出 URL query、Cookie 或授权头。单个批准目标探测有超时并保留 TLS，无法访问原源就标缺口。",
                ),
                "server UP 只说明所配置检查通过，不证明真实业务正确；qcur 上升可能来自 server maxconn、后端慢或检查摘除。放大 frontend maxconn 不一定增加处理能力，反可能将排队转移到内存和应用。",
                "Runtime API 可立即改变生产流量，enable/disable、set weight 和 shutdown sessions 都必须审批；健康检查改成永远成功会把流量送到故障端。不能禁用证书验证或提高超时掩盖后端失败。",
                "提交已确认瓶颈、单 server 修复或容量调整、原限额与回退条件，经后台审批。状态修改还需决定是否持久到声明配置，避免 reload 后反转；未知后端所有者时停在补证。",
                "复查队列消退、错误增量、check_status 与真实原请求，确认恢复不是单纯增加等待时间。未做业务验证时只能报告检查/代理统计改善；不假称当前机器已连生产 stats 或完成流量切换。",
            ),
            _document(
                "master-worker", "HAProxy master worker 与无损加载边界", "ssh",
                "适用于 reload 后配置不一致、旧 worker 残留或长连接中断。输入 HAProxy 版本、启动模式、服务单元、配置来源与连接生命周期，先核实是否真实 master-worker 模式。",
                (
                    "用 systemctl show haproxy -p MainPID -p ActiveState -p ExecMainStatus 与有限 ps 的 PID/PPID/comm/开始时间记录进程代际，不打印 args 或 /proc/environ。已授权 show info 可读 version、uptime、process_num 等必要字段。",
                    "核对服务 reload 日志、新 worker 创建、旧 worker stopping 与 socket 接管证据；master 活跃不证明新 worker 已加载。多进程、多线程与 master CLI 的区别按实际版本解释，不用别处 PID 假设。",
                    "仅查看批准的 nonsecret 配置字段、server-state-file 策略、hard-stop-after、maxconn 和监听；完整 haproxy.cfg 可能含认证，证书 bundle 可能含私钥，不直接读取或粘贴。haproxy -c -f 需授权后才验证已知路径。",
                    "比较加载前后 show stat 的目标 server 状态、队列和会话基数，核对 drain/maint/disabled 是否来自运行时且有持久化；进程切换时计数可能重置，不把归零直接当故障恢复。",
                ),
                "平滑 reload 允许旧 worker 排空，长连接使退出延后不一定异常；hard-stop 会限制排空但可能断开会话。配置语法正确不代表证书链、后端权限或真实路由可用，必须分层验证。",
                "restart、关闭旧 worker 或修改 Runtime API 状态都可能中断流量；丢失状态文件可让维护中后端意外恢复接流。不能为排障暴露 admin socket，也不复制私钥或关闭 SSH/TLS 校验。",
                "提交单次加载的配置差异、连接排空时限、后端状态继承、备用入口与回退，经后台审批；若配置测试会读取受保护文件由负责人安全执行。不要连续 reload 生成多代旧 worker。",
                "确认批准配置在新 worker 生效、旧进程按预期退出、后端维护状态保持且长连接符合约定；原入口业务必须单独验证。只有命令成功与新 PID 时只能报告加载动作，不承诺零中断。",
            ),
        ),
        scope="ssh", color="#0f766e",
    ),
    _preset(
        "systemd-services", "systemd 单元生命周期",
        "按退出状态、启动限制、依赖图和定时单元解释服务失败，不把 Active 等同业务正常。",
        (
            "systemd 单元退出与依赖链核查",
            "从 Result、ExecMainStatus 和依赖时序找启动失败，保护原始现场。",
            "输入单元全名、选中 SSH 主机、业务监听与故障窗口；用 systemctl show 的指定属性和有限 journalctl "
            "关联 Type、Result、ExecMainCode/Status、NRestarts、ActiveEnterTimestamp 与 TriggeredBy。读取依赖只限 "
            "systemctl list-dependencies 的目标图，区分 Requires/Wants、After/Before 与服务真正 Ready。"
            "StartLimitHit、203/EXEC、217/USER、依赖失败与 watchdog 分支分别检查非敏感路径/用户元数据；"
            "systemctl cat、Environment 与 ExecStart 可能含秘密，不默认完整输出。reset-failed、daemon-reload、"
            "enable、restart、drop-in 和 timer 修改均是需审批的状态变更，不用连续重启碰运气。",
        ),
        ("systemd 服务诊断员", "专注单元状态、退出与依赖时序，不自动清失败状态或重启依赖树。"),
        (
            _document(
                "unit-failure", "systemd 退出码与启动限制", "ssh",
                "适用于 failed、activating 持续、Start request repeated too quickly 或崩溃循环。输入服务全名、业务责任人、原启动时间和允许日志窗口，不将 systemctl status 输出全量复制以免泄密。",
                (
                    "选中授权 SSH 用 systemctl show \"$UNIT\" -p ActiveState -p SubState -p Result -p ExecMainCode -p ExecMainStatus -p NRestarts -p MainPID -p Type；属性明确列出，不输出 Environment、ExecStart 或完整 unit。",
                    "有限 journalctl -u \"$UNIT\" --since \"$START\" --until \"$END\" -n 120 --no-pager，保留第一条失败与 systemd 动作的时间关系，过滤凭据和业务数据。StartLimitHit 是反复失败保护，不是最初根因。",
                    "203/EXEC 检查已知可执行路径存在、权限、挂载 noexec 或解释器；217/USER 检查已批准服务账户元数据；超时与 watchdog 结合 Type=notify/forking/simple 的语义，不默认调大 TimeoutStartSec。",
                    "核对 ActiveEnter/InactiveEnter 时间、重启策略和 RestartSec 的非敏感字段，比较服务自身退出与外部 stop。coredump 可能含秘密且读取有成本，不默认导出；需要应用日志或崩溃分析时列单独范围。",
                ),
                "Active=active 只表示 systemd 对该 Type 的生命周期判断，oneshot/exited 也可能正常；MainPID 为零不适合所有类型同一解释。连续重启失败可能是配置、权限或依赖，不能用清理 failed 代替修复。",
                "reset-failed 会清掉启动限制/失败状态，restart 可中断业务并丢现场，daemon-reload 也改变管理器状态；都不是只读。不能自动 chmod 可执行文件、改用户、禁用沙箱或关闭 MAC 安全策略。",
                "提交确定退出分支、最小路径/配置/服务修复、原值、业务影响与停止条件，经后台审批；应用机密由既有安全流程处理。无稳定修复依据时保持失败现场，不连环 restart 整个依赖树。",
                "复查 Result、实际进程、NRestarts 增量和新日志，并验证业务监听和请求；观察窗口覆盖至少原故障复现周期。只 Active 恢复时准确限定为服务状态，不宣称业务已经完整可用。",
            ),
            _document(
                "dependencies-timers", "systemd 依赖顺序与 timer 漏触发", "ssh",
                "适用于依赖看似启动却连接失败、timer 没执行或重启后任务补触发。输入目标 service/timer、期望日历、时区、依赖所有者与任务幂等，重点分清激活关系和就绪关系。",
                (
                    "用 systemctl list-dependencies \"$UNIT\" --all --no-pager 查看授权目标图，指定读取 Requires/Wants/After/Before 等属性；Wants/Requires 拉起依赖，After 只管顺序，不保证应用实际可接流量。",
                    "核对依赖 Type=notify、socket 激活、network-online.target 的真实提供者和业务启动重试；网络 target 到达不保证 DNS 或远端数据库可用。服务 unit/ExecStart 可能含秘密，字段由管理员选择性脱敏提供。",
                    "timer 用 systemctl list-timers \"$TIMER\" --all --no-pager 与 show 的 LastTriggerUSec、NextElapseUSecRealtime、Persistent 等元数据，核对 OnCalendar/OnBootSec/OnUnitActiveSec 和 RandomizedDelaySec 的实际配置。",
                    "对照 date、时区、时钟同步与 service 的有限日志；timer active 不代表 service 成功执行，任务仍在 active 时重复触发语义也需核实。日历验证仅可用现有 systemd-analyze calendar 的无写解析，不启动任务试探。",
                ),
                "依赖顺序不能替代应用 readiness，timer 的随机延迟和持久补触发会造成计划时间偏移。Persistent 常用于 OnCalendar 漏触发补偿，不应误以为所有间隔 timer 都会补齐全部历史次数。",
                "修改依赖可形成循环或延迟启动，enable/disable/mask 会改变开机行为；解 mask 或启动 timer 可能立刻触发非幂等业务。停止服务也可能按依赖传播，不能只评估一个 PID。",
                "审批方案列出图中受影响单元、任务幂等、补触发范围、配置旧值与回退；daemon-reload、enable、start、timer 修改都须后台审批。无业务确认时仅给依赖/日历修正建议，不主动补跑。",
                "在真实批准周期确认 timer 触发、service 结果和业务批次一致，验证依赖不再在启动竞争中失败。仅 calendar 解析或 next 时间正确时，只报告计划配置核对，不冒称任务已成功执行。",
            ),
        ),
        scope="ssh", color="#475569",
    ),
    _preset(
        "linux-fd-pid", "Linux 文件句柄与 PID",
        "区分进程 FD、系统文件表、线程与 cgroup pids 上限，避免盲目提高系统阈值。",
        (
            "FD 与线程 PID 限额分层诊断",
            "用选定 PID 的 limits、fd 数量和 cgroup 事件定位 EMFILE、ENFILE 与 EAGAIN。",
            "输入已确认服务 PID、单元、错误文本和 cgroup 版本；在选中 SSH 用 /proc/PID/limits、/proc/PID/status "
            "及指定 fd 目录的有界计数采集，不读取 fd 内容、environ 或进程参数。EMFILE 指进程 FD 限制，ENFILE "
            "关联系统文件表，fork Resource temporarily unavailable 还需线程、RLIMIT_NPROC、cgroup pids.max/events "
            "与内存证据。核对 systemd LimitNOFILE/TasksMax 与容器 pid limit，宿主 shell ulimit 不能代表目标服务。"
            "不全盘 lsof、不逐 fd 扫敏感路径，不默认 kill 或改 sysctl；提限可能扩大泄漏，先定位增长类型再审批最小修复。",
        ),
        ("Linux 句柄线程诊断员", "专注进程、系统及 cgroup 限额证据，不用提限和杀进程掩盖泄漏。"),
        (
            _document(
                "fd-limits", "EMFILE 与 ENFILE 文件表分界", "ssh",
                "适用于 too many open files、accept 失败或服务不能打开日志。输入准确 errno、服务 MainPID、systemd 单元和故障时间，先确认当前进程仍是原服务，避免 PID 重用误读。",
                (
                    "选中授权 SSH 读取 /proc/PID/limits 的 Max open files 与 /proc/sys/fs/file-nr、file-max，必要时 systemctl show \"$UNIT\" -p MainPID -p LimitNOFILE；只读目标字段，不以当前 SSH shell 的 ulimit -n 代替服务限制。",
                    "对明确 PID 的 /proc/PID/fd 仅做目录条目计数，可用已有受控 Python os.scandir 且设置数量上限；不跟随 symlink、不读取文件内容或完整路径。计数是瞬时值，采样期间进程变化需标记误差。",
                    "EMFILE 对照进程软硬上限，ENFILE 对照系统文件表已分配与上限；file-nr 字段语义按内核版本确认，不把第二字段当通用空闲量。若需区分 socket/文件类型，只取脱敏聚合并限定该 PID。",
                    "比较有限间隔增长、服务请求量和连接统计，识别连接堆积、日志句柄或应用泄漏候选；容器 PID namespace 与宿主 PID 需映射证据，映射不明时不读取任意宿主进程，也不运行全系统 lsof。",
                ),
                "单进程接近 limit 与全系统耗尽需要不同方案；FD 数高但稳定可属合法连接规模，持续增长且无回收更支持泄漏。打开文件数、连接数和系统 file table 分配不是完全相同口径。",
                "提高 file-max 或 LimitNOFILE 可能放大内存与上游压力，不能修代码泄漏；关闭目标 fd、kill 或重启会中断连接。/proc/fd 路径与进程参数可能泄露业务数据，不能为分类全量导出。",
                "提交增长类型、实际上限、容量证明和应用修复或临时提限方案，经后台审批。systemd 限额变更对现有进程是否生效需明确，涉及 restart 单独评估；保留原值和恢复窗口。",
                "复核目标 PID 新旧身份、软硬限额、FD 增长曲线与原 errno，验证连接和业务稳定。只错误消失但 FD 仍持续增长是暂时缓解，不能宣称泄漏修复，缺类型证据则继续列待补证。",
            ),
            _document(
                "pids-cgroup", "fork EAGAIN 与 cgroup 线程上限", "ssh",
                "适用于 cannot fork、Resource temporarily unavailable、Java unable to create native thread 或 PIDPressure。输入服务 PID、容器身份、cgroup 版本与错误起点，不将所有 EAGAIN 都解释为全机 PID 用尽。",
                (
                    "从 /proc/PID/status 只读取 Threads、NSpid 等身份/计数与 /proc/PID/limits 的 Max processes；用 systemctl show \"$UNIT\" -p TasksCurrent -p TasksMax -p LimitNPROC 取得目标单元限制，不读 environ 或 cmdline。",
                    "通过 /proc/PID/cgroup 确认该进程 cgroup 路径与 v1/v2，再只读对应 pids.current、pids.max、pids.events；容器路径需安全映射，不递归扫描所有 cgroup。events.max 增量可支持触及 cgroup 限制。",
                    "读取 /proc/sys/kernel/pid_max、threads-max 与有限进程/线程聚合，RLIMIT_NPROC 常按真实 UID 计线程，root 等特权例外需核实；全机 PID 空间、用户限制和单 cgroup 上限不是同一个数。",
                    "结合 free、内核有限 OOM/分配错误日志和服务线程增长，EAGAIN 也可能伴内存不足或调度限制。僵尸需看父进程是否回收，不能把 Z 状态当可用 kill 清掉的普通进程。",
                ),
                "pids.max 计任务包含线程，应用进程数少也可能触顶；pid_max 是标识空间范围，不等同当前可创建线程保证。TasksMax 与用户 nproc 可同时约束，必须找实际最先触及的一层。",
                "批量 kill、调高 pid_max、解除 TasksMax 或容器 pids limit 可让线程风暴拖垮主机；线程池配置错误不是无限提限能修。僵尸直接 kill 无效，重启父进程又可能影响全部子任务。",
                "审批方案列明目标 cgroup/UID、增长源、原限额、内存余量和业务影响；修线程池、回收逻辑或临时提限先获批。容器资源变更通过实际编排源，不手改被控制器管理的 cgroup 文件。",
                "比较 pids.current/events、线程数与原 fork 错误增量，观察正常峰值和线程回收，验证关键服务无新增超时。缺少内存或父进程证据时不得把 EAGAIN 根因定死，只说明已验证层级。",
            ),
        ),
        scope="ssh", color="#78716c",
    ),
    _preset(
        "time-synchronization", "时间同步与时钟",
        "按 chrony、timesyncd 和单调时钟分解时钟偏移、源失联与日志时间误读。",
        (
            "时钟来源与偏移可信度核查",
            "确认实际时间守护进程、源状态和测量误差，不默认强制校时。",
            "输入主机、错误时间范围、时区、业务对跳时的限制和实际同步服务；在选中 SSH 使用 date -u、"
            "timedatectl show 的指定属性，chrony 环境已有 chronyc 时读 tracking/sources -v，timesyncd 则用 "
            "timedatectl timesync-status。不把 NTP synchronized 标志等同偏移已达业务要求，核对 leap、stratum、"
            "last offset、root dispersion、样本新鲜度与来源可信度；命令不存在不安装或启动另一守护进程。"
            "日志时间受时区、时钟跳变和采集延迟影响，比较应保留原时区与单调序列。改时间源、makestep、date -s、"
            "时区或服务重启都审批，数据库、证书和租约系统需先确认跳时风险，不扫描外部 NTP。",
        ),
        ("时钟同步核查员", "专注同步源、误差与时间线可信度，不自动 step 系统时钟或替换内网时间源。"),
        (
            _document(
                "source-offset", "chrony 与 timesyncd 同步证据", "ssh",
                "适用于证书尚未生效、租约漂移、日志时间明显错位或 NTP 告警。输入主机、预期内部时间源、业务允许误差与实际守护进程，不能默认运行两套时间服务。",
                (
                    "选中授权 SSH 用 date -u 与 timedatectl show -p Timezone -p NTPSynchronized -p NTP -p LocalRTC，保存采样时间和时区。UTC 与显示时区区别需保留，时区不同不自动意味着系统 epoch 不一致。",
                    "实际使用 chrony 且客户端已存在获准时，读 chronyc tracking 与 chronyc sources -v；记录 reference ID、stratum、leap status、last/RMS offset、root delay/dispersion 与 reach，reach 非满位需结合启动和采样时长。",
                    "实际使用 systemd-timesyncd 则读 timedatectl timesync-status 的 server、poll、offset 与 root distance 等受支持字段；版本不支持或未用此守护进程就待补证，不安装 chrony，也不启动其他同步服务。",
                    "关联有限同步服务日志和已批准时间源的网络证据，检查 source unreachable、falseticker、unsynchronised。虚拟机暂停或宿主时钟问题要有平台证据，当前主机无法确认时由虚拟化负责人补证。",
                ),
                "NTPSynchronized 是粗粒度状态，不能替代当前偏移与误差界；高 stratum、陈旧样本和较大 dispersion 影响可信度。源不可达不代表必须切公共 NTP，内部域和安全策略可能要求专用来源。",
                "makestep、date -s 或重启某些服务可能跳时，影响数据库事务、JWT、证书、租约和定时任务；改时区也会改变作业解释与日志显示。主动探测未知 NTP 或全网扫描没有授权不能执行。",
                "提交源列表、实际误差、slew/step 选择、业务停写或维护要求、原配置与恢复路径，经后台审批。只在负责人确认时间敏感组件后执行校时，不通过关闭证书时间检查掩盖根因。",
                "覆盖多个轮询周期确认选中源、偏移与误差界达批准标准，原证书/租约错误消退且无异常任务触发。若只读到 synchronized 标志，结论只能是状态标记，不承诺精确同步或全链时间一致。",
            ),
            _document(
                "clock-jumps", "时钟跳变与跨系统事件对齐", "ssh",
                "适用于日志时间倒退、监控尖峰或事故时间线互相矛盾。输入各系统时区、原始日志时间、采集端延迟和事件身份，不把同秒时间戳自动当严格先后关系。",
                (
                    "在选中授权主机用 date -u、uptime 与受限 journalctl 的 realtime/monotonic 证据定位当前 boot；可用 journalctl -u \"$TIME_UNIT\" --since \"$START\" --until \"$END\" -n 100 --no-pager，过滤敏感业务输出。",
                    "从已有日志找 time jumped、clock step、source change 或 VM resume 记录，区分墙钟校正和单调时间流逝。跨 reboot 的 monotonic 值不能直接相减，需保存 boot ID 与可靠边界，不手算 epoch。",
                    "比较应用、容器、数据库和日志平台时间字段的时区、格式、事件时间/采集时间含义；容器通常共享内核时钟但显示配置可不同，不读取业务 payload。只有当前主机证据不能推断远端全部同偏移。",
                    "对关键事件用 request ID、Pod UID、事务摘要或审批记录交叉定位，保留脱敏标识。需要换算用现有 Python datetime/zoneinfo 或 date，保留原值与误差范围；DST 重复本地时间不得强行排唯一顺序。",
                ),
                "时钟倒退会让墙钟计算出负耗时，监控 counter 的 rate 也可能受样本时间异常；采集积压与主机偏移不是同一原因。误差范围重叠时只能说明可能顺序，不能据此确定根因先后。",
                "为让日志对齐而直接改服务器时间可能制造新的任务重复、令牌过期或租约异常；修改历史日志会损坏证据。禁止清缓存重启全服务试图消除时间错位，也不把人工修订当原始记录。",
                "时间源或应用时区变更仍需提交受影响定时任务、证书与数据系统、原设置和回退，经后台审批；报告修订只增加解释层，保留原记录。没有跨系统授权时输出各方需补的最小字段。",
                "确认新事件墙钟与单调顺序一致、同步测量可信并原错误不再新增，重算事故耗时须标明依据。未得到其他系统测量时仅交付本机结论，不声称整个生产时间线已精确校正。",
            ),
        ),
        scope="ssh", color="#0369a1",
    ),
    _preset(
        "host-firewall-routing", "主机防火墙与路由",
        "对单条批准流量核对路由、策略表、规则计数和反向路径，保护远程管理连接。",
        (
            "Linux 单流路由与规则计数诊断",
            "根据源目标和链路位置解释丢弃，不清空规则、不扫描网段。",
            "输入源 IP、目的 IP、协议端口、接口、预期 NAT 和当前 SSH 路径；在选中 SSH 主机用 ip route get、"
            "ip rule show、ip -s link 和批准范围的 nft/iptables 只读列表，输出脱敏且有界。不默认全量规则集泄露拓扑，"
            "确定实际 nft/iptables 后端并区分 ingress、forward、output 与 NAT 链。规则计数是累计数据，要同流量窗口"
            "比较且不能把未命中直接等价允许；策略路由、conntrack、rp_filter、IPv4/IPv6 需实际证据。"
            "查询缺工具/权限即待补证，不安装网络工具。任何 route/rule/sysctl/防火墙变更、conntrack 清理或抓包均"
            "先写精确范围、失联风险、第二通道与自动恢复安排并审批，不执行 flush 或全局 accept 试错。",
        ),
        ("主机选路防火墙分析员", "专注授权单流的选路、规则和反向路径，避免切断 SSH 或扩大网络暴露。"),
        (
            _document(
                "route-policy", "策略路由与反向路径核对", "ssh",
                "适用于单目标超时、双网卡回包走错或仅 IPv6 失败。输入明确源/目标、协议端口、接口和当前 SSH 连接路径，不通过 ping 整网段、traceroute 扫描或未知网关试探定位。",
                (
                    "在选中授权 SSH 用 ip route get \"$DEST_IP\"，必要时明确 from \"$SOURCE_IP\"；记录选出的 table、gateway、dev、src。该命令计算内核选路不发送业务包，不能因此证明真实链路或对端服务可用。",
                    "有限读取 ip rule show 与已确认相关 table 的 ip route show table \"$TABLE\"，核对优先级、source、fwmark、lookup；mark 若由应用/CNI 设置需对应证据，不能使用无 mark 查询模拟所有实际流。",
                    "ip -br addr、ip -s link show dev \"$IFACE\" 提供地址、状态与错误增量，IPv4/IPv6 各自核对。仅指定接口读取 rp_filter、forwarding 等实际 sysctl，不能默认关闭反向路径校验。",
                    "将回程路由、NAT 和上游网关证据分别列出；邻居表只限批准目标和接口，缺少对端授权由网络负责人补证。主机查询成功不证明容器 namespace、策略路由或云侧安全组配置相同。",
                ),
                "有默认路由仍可能被更高优先级策略或黑洞表覆盖；非对称路径配严格 rp_filter 可能丢包，但要有接口与返回路径证据。链路 UP 不代表网关可达，单个流成功也不覆盖另一个协议族。",
                "改默认路由、策略优先级或 sysctl 可能切断当前 SSH；临时命令与 NetworkManager/netplan 等持久来源不一致会在重启后反转。不能自动换网关、关防火墙或扫端口找可达路径。",
                "提交单条 route/rule 的旧值、新值、匹配流、管理链路影响和失联恢复方案，经后台审批。没有第二通路或可靠回退时由具备带外管理的负责人维护，不在远端盲改唯一管理路径。",
                "先复查内核选路与持久声明，再对原批准源目标做有限带超时验证，并确认 SSH 与无关关键流量未受损。仅 ip route get 正确时只能报告选路配置，不能宣称对端服务已恢复。",
            ),
            _document(
                "firewall-counters", "nftables iptables 规则与状态跟踪", "ssh",
                "适用于连接被拒、建立后中断或 NAT 仅部分失效。输入单流五元组、主机转发角色、实际规则管理器和故障窗口；禁止通过 flush ruleset 或设置全局 ACCEPT 来验证猜测。",
                (
                    "先确认现有 nft/iptables 工具及实际后端与管理来源；仅在授权范围读取指定 nft table/chain 或 iptables -S \"$CHAIN\"、iptables -L \"$CHAIN\" -n -v -x。规则可能含敏感拓扑，输出仅保留目标流相关条目，不完整导出所有表。",
                    "核对 hook、priority、policy、输入/转发/输出链和 NAT 前后地址；nft 多个 base chain 的 accept 不一定阻止后续链丢弃。iptables nft/legacy 混用可能存在两套视图，不能看一套空表就宣称无规则。",
                    "比较同一窗口的规则包/字节计数，记录是否有明确 drop/reject 命中；累计计数需算增量，不重置 counters。无命中可能是查错 namespace、family 或更早链丢弃，并不等价允许。",
                    "只在已知工具与授权下看目标 conntrack 状态或聚合，关联 NEW/ESTABLISHED、NAT 和超时；conntrack 全表可能巨大，不能默认列全、delete 或 flush。抓包需单独审批过滤器、数量与隐私，不默认捕获载荷。",
                ),
                "SYN 被 drop、明确 reject 和已建连接被状态规则丢弃的表现不同；既有连接成功不能证明新连接规则允许。CNI/eBPF、云防火墙和应用监听不在本机规则证据内，必须保留覆盖限制。",
                "全局放通会扩大暴露面，清 conntrack 会中断活跃连接，规则 reload 可能丢管理会话；无序追加规则也可能被更早链覆盖。不要为排障关闭安全代理、TLS 或 SSH 主机指纹校验。",
                "只提交单流最小 permit/修正、原规则位置和计数、有效期及可执行回退，经后台审批；确认规则管理源避免自动覆盖。涉及 SSH 路径须预置带外或可靠定时回退，由负责人确认后实施。",
                "观察目标流新计数与原连接结果，确认规则顺序、持久配置和管理连接保持，删除临时例外也需审批。没有端到端证据时只报告本机规则推断，不假称网络全域已验证。",
            ),
        ),
        scope="ssh", control_level="approve", color="#b45309",
    ),
    _preset(
        "prometheus-cardinality", "Prometheus 高基数",
        "分析 head series、标签组合和抓取限额，区分序列爆炸、churn 与查询压力。",
        (
            "Prometheus 基数来源与抓取限额分析",
            "以有界 TSDB 统计、样本增量和标签设计证据定位高基数来源。",
            "输入实际 Prometheus 实例、版本、受影响 job、授权只读 endpoint 与时间窗；仅选中 SSH 上已有客户端和"
            "安全连接查询，未接入不能虚构指标 API。优先已有 prometheus_tsdb_head_series、head_series_created_total、"
            "scrape_samples_scraped/post_metric_relabeling 和 scrape_series_added 的限范围结果。"
            "必要时获准请求 /api/v1/status/tsdb 的小 limit，标签值可能敏感应脱敏，不默认 /series 全量枚举或读取完整配置。"
            "区分活跃序列、标签值组合和短命 churn，核对 metric_relabel_configs、sample_limit、label_limit 的版本支持；"
            "仅丢标签可能造成冲突样本。删序列、改 scrape/remote_write、reload 和 retention 均写审批，不使用高基数查询再次拖垮实例。",
        ),
        ("Prometheus 基数分析员", "专注时间序列规模、标签设计和抓取边界，不默认全量标签枚举或删除监控数据。"),
        (
            _document(
                "head-series", "Prometheus head series 与 churn 溯源", "ssh",
                "适用于内存激增、TSDB head series 告警、WAL 膨胀或抓取变慢。输入真实实例、job、抓取周期与已有指标来源，未选 SSH 或未接监控时只列补证，不假装拥有 Prometheus 专用工具。",
                (
                    "通过选中授权 SSH 上现有安全 HTTP 客户端，有限查询已有 prometheus_tsdb_head_series、prometheus_tsdb_head_chunks 与 rate(prometheus_tsdb_head_series_created_total[5m])；实际名称和存在性需验证，不在 URL 放 token 或读取凭据。",
                    "比较特定 job 的 scrape_samples_scraped、scrape_samples_post_metric_relabeling、scrape_series_added 和 scrape_duration_seconds，按受限目标统计；缺来源就待补证，不默认全实例 sum by 复杂聚合。",
                    "必要时经许可读取 /api/v1/status/tsdb?limit=10 的受控统计，提 metric 名和计数，标签值脱敏。API 开销与版本支持先确认，不请求 /api/v1/series 全量、label values 全表或全量 exporter metrics。",
                    "对照近期 exporter/业务发布，检查 user_id、request_id、URL path、容器 UID 等无界标签来源和短命目标 churn；只用聚合及批准配置片段，不打印真实用户标识或完整 scrape_config/remote_write 凭据。",
                ),
                "一个标签值很多不一定等于全部组合数量，真正 series 由 metric 名与完整标签集定义；活跃 head 和历史块不是同一规模。新建序列速率高但 head 相对稳可能是 churn，仍会增加 WAL、索引和内存成本。",
                "直接 count({__name__=~'.+'}) 或大范围查询可能加剧内存压力；单纯加内存不解决增长源。删除 series 不保证立即回收 head 或磁盘，使用 admin API 会改变数据，不能作为只读统计。",
                "提交定位到 metric/job 的标签治理、受限抓取或容量候选、原值、失去的诊断维度与回退，经后台审批。变更先灰度，确认告警依赖和 remote_write 影响，不无差别丢掉 instance/job 标签。",
                "在多个抓取周期对比 head、创建速率、抓取耗时与查询延迟，确认关键告警和业务指标仍新鲜；历史块回收需等待真实保留周期。仅内存下降或重启后暂空不能宣布高基数源已消除。",
            ),
            _document(
                "relabel-limits", "metric relabel 与抓取限额安全设计", "ssh",
                "适用于拟通过 drop、labeldrop、sample_limit 限制指标，或抓取出现 sample limit exceeded。输入具体 metric、标签设计、告警依赖与真实 Prometheus 版本，不提供全局删除标签的万能配置。",
                (
                    "取得目标 job 经过脱敏的 metric_relabel_configs、sample_limit、label_limit、label_name_length_limit 和 label_value_length_limit 片段，核对字段由版本支持；不读取完整配置中的 bearer_token、basic_auth 或 remote_write 密钥。",
                    "将抓取前样本、metric relabel 后样本与 up、抓取错误对齐；超 sample_limit 可能导致整次抓取失败，而非只少几个样本。target relabel 与 metric relabel 处于不同阶段，external labels 也不用于限制本地序列创建。",
                    "对候选 labeldrop/drop 用批准的有限脱敏样本做离线推演，核对去标签后是否出现同 metric 同时间标签集冲突；不能直接把 request_id 标签删掉就假设实现了正确聚合，聚合应在 exporter/应用语义层设计。",
                    "已有 promtool 时，check config 对明确安全配置副本进行获准校验，必要只读引用可能触及敏感文件需先评估；不以远端生成测试配置、reload 或写规则冒充纯分析。未有安全样本时保持方案未验证。",
                ),
                "metric relabel 可减少存储样本但 exporter 产生与传输成本可能仍在；recording rules 不能消除已抓入的原始基数。限额是一道保护而非完整治理，整次 scrape 失败可能让关键告警无数据。",
                "丢标签可合并原本不同序列并产生 duplicate sample 或语义错误；全局 drop 可能掩盖事故。删数据、改 retention 和 remote_write 队列均不可轻易回退已丢历史，不能承诺无损节省。",
                "审批单写明精确匹配规则、有限样本结果、关键告警兼容、灰度目标、停止条件与原配置恢复，所有远端配置/reload/删除均先获批。若需业务代码聚合，由指标所有者确认语义后实施。",
                "确认 up 与样本仍新鲜、无 limit/duplicate 错误，head 新增速率降低且关键仪表盘/告警仍正确；观察足够多个抓取周期。只 promtool 通过表示语法检查，不代表数据治理已在生产生效。",
            ),
        ),
        scope="ssh", color="#ea580c",
    ),
    _preset(
        "grafana-query", "Grafana 查询与面板",
        "按数据源身份、变量展开、时间范围和单位解释空面板、超时与误导聚合。",
        (
            "Grafana 面板查询链与变量核查",
            "分离前端变量、数据源权限、查询结果和面板转换，避免把 No data 当恢复。",
            "输入 dashboard UID、panel ID、datasource UID、原查询时间/时区和脱敏请求；没有 Grafana 专用工具，"
            "只经已选 SSH 上已有安全客户端访问获准只读 API 或由负责人提供 Query Inspector 证据，不获取 API token。"
            "检查模板变量 multi/all/regex 展开、interval/rate_interval、step/maxDataPoints、transformations 和单位，"
            "核对数据源实际 tenant 与权限。指标 counter 先 rate 再聚合，分位数不平均，空结果与零值区分。"
            "查询执行本身有负载，先缩时间、单面板和显式标签，不默认全量 dashboard JSON 或 datasources 配置。"
            "保存面板、改数据源、权限、变量和告警都走审批，不假称接入并在生产验证。",
        ),
        ("Grafana 查询核查员", "专注查询输入、时间与面板变换，不把显示正常或无数据替代真实遥测证据。"),
        (
            _document(
                "no-data-variables", "Grafana 空面板与变量展开", "ssh",
                "适用于 No data、变量下拉为空、面板 403 或不同用户看到不同数据。输入 dashboard UID、panel ID、数据源 UID、用户授权范围和原时间窗，不索取登录密码或导出安全数据源配置。",
                (
                    "通过负责人提供的脱敏 Query Inspector 请求/响应，或选中 SSH 上现有获准安全客户端读取单目标只读信息；没有浏览器和 Grafana 专用工具就不假称已点击面板。API 授权由既有会话提供，不读取 token。",
                    "核对 datasource UID、组织/tenant、实际查询语言与后端返回码；Grafana proxy 403、后端认证、查询语法和空数据不同。完整 dashboard JSON 可能含业务参数或敏感 URL，只保留面板相关非秘密字段。",
                    "查看变量 query、refresh、multi、includeAll、allValue 与 regex，检查 :regex/:raw 等格式化在实际后端的展开。PromQL 多选常需 =~，但不能机械替换所有等号；变量值包含特殊字符时要确认转义。",
                    "比较绝对起止时间、时区、面板 time override/timeShift 与查询 step，核对数据最新时间和 retention。无数据可以是窗口错误、标签改名、权限或抓取中断，不能在面板设置里直接填零掩盖。",
                ),
                "Grafana 显示层和数据源取数层是两层；同一查询在不同 tenant 或变量展开下结果可不同。零表示真实样本值，空表示未返回，error 表示失败，三者必须保留在告警与报告解释中。",
                "All 变量无界正则可生成昂贵查询，扩大时间窗或 maxDataPoints 可能拖垮后端；导出完整 dashboard/数据源可暴露敏感地址。提高权限、关闭 TLS 和共用管理员 token 不是正常修复。",
                "提交单变量、数据源引用或时间设置的原值、新值和有限样本验证，经后台审批后保存；修改权限和数据源另需所有者。仅 Query Inspector 请求分析无写入时说明范围，不宣称面板已经修改。",
                "在原用户权限、变量和时间窗确认请求、真实新样本与显示一致，并检查其他面板未被共享变量影响。若只拿到静态截图/请求，结论限定为分析，不能声称实时数据源或生产面板已恢复。",
            ),
            _document(
                "aggregation-performance", "Grafana step 聚合单位与慢查询", "ssh",
                "适用于图形尖峰消失、p99 算法不可信、单位误导或 dashboard 加载超时。输入查询表达式、采样间隔、面板单位、transformations 和后端限制，先分清查询正确性与可视化效果。",
                (
                    "对单 panel 的脱敏 query、step、interval、maxDataPoints、返回点数和查询耗时做基线；只经既有授权数据源查询，不默认全看板并发重放。查询本身可有高负载，先短窗、明确标签与小返回量。",
                    "Prometheus counter 检查 rate/increase 的窗口和 reset 处理，通常先 rate 后聚合；经典 histogram 检查保留 le 标签再 histogram_quantile，native histogram 按实际版本语法。不能平均各实例 p99 当全局 p99。",
                    "核对 $__interval 与 $__rate_interval 的实际展开、scrape interval 和 min step；step 太大会漏短峰，窗口太短样本不足。数据源非 Prometheus 时按真实 SQL/日志语义，不套用 PromQL 规则。",
                    "检查 unit、decimals、null mapping、reduce/join/organize transformations 和 override；毫秒/秒、bytes/bits、百分比 0-1/0-100 错配会制造数量级错误。join 重复维度和面板求平均可能再次改变查询含义。",
                ),
                "后端正确数据也可能被转换或单位误导，图变平不代表业务更稳定；缓存命中与短时间窗查询快也不证明完整业务周期性能。需用真实采样来源和样本量解释延迟、吞吐与错误比例。",
                "增加并发、无界变量、宽时间窗和高分辨率会放大数据源压力；录制规则虽可提速但属于后端配置写入，不能在 Grafana 保存按钮之外悄悄部署。共享面板调整也可能改变告警判断。",
                "提交单表达式/step/单位改动及有限结果对照、受影响面板、告警依赖和原配置回退，经后台审批。需要 recording rule、索引或采样改变时由真实后端负责人分别批准，不虚构自动优化。",
                "对同一绝对时间窗比较修正前后的数值、单位、缺样本和查询耗时，核对真实峰值未被平均掩盖，后端错误无新增。只语法通过或图形好看不是正确性证明，未执行查询则保留待验证。",
            ),
        ),
        scope="ssh", color="#f59e0b",
    ),
    _preset(
        "loki-log-operations", "Loki 日志流与摄取",
        "定位丢弃、时间戳、标签流爆炸和 LogQL 查询成本，保护租户与日志隐私。",
        (
            "Loki 摄取拒绝与 LogQL 成本诊断",
            "用拒绝 reason、流标签与查询统计区分丢日志、查错与高成本扫描。",
            "输入 Loki 版本、tenant、采集器类型、标签选择与时间窗；只经已选 SSH 的现有授权 HTTP 客户端或"
            "组件有限日志获取证据，不假设已接 Loki 专用工具。核对 429、line too long、too old、out of order、"
            "per-stream limit 等实际 reason，区分代理缓冲、distributor/ingester、对象存储和查询链。"
            "标签只用低基数元数据，request_id/user_id 不默认作为 stream 标签；原生 Kubernetes 仅可查采集器 Pod/"
            "DaemonSet 状态，配置和 Loki API 需额外 SSH 授权。LogQL 先具体 selector 与短窗、低 limit、过滤后解析，"
            "不全租户导出日志。调限额、改标签、replay、删除/retention 与重启均审批，不把查询无结果当日志从未产生。",
        ),
        ("Loki 日志链诊断员", "专注摄取拒绝、流标签与有限查询证据，不导出敏感日志或默认回放积压。"),
        (
            _document(
                "ingestion-rejects", "Loki 摄取 429 与时间戳拒绝", "ssh",
                "适用于采集器重试、日志缺段、ingestion rate limit 或 too far behind。输入 tenant、采集器版本、源 Pod/主机、事件时间与摄取时间，不把当前能查询新日志当历史没有丢失。",
                (
                    "在选中授权 SSH 查询采集器及 distributor/ingester 有限日志，或实际获准的聚合指标；只取 loki_discarded_samples_total/bytes_total 的 reason、tenant 脱敏摘要，指标未接入不虚构数值。",
                    "准确记录 429/400、ingestion_rate、per_stream_rate、line_too_long、too_old、out_of_order 等该版本真实 reason；标识发生在采集缓冲、HTTP 接收或存储链，不能凭 429 全部归为同一个限额。",
                    "核对源时钟、日志时间格式、multiline/parser、租户映射和采集位置/offset 的非敏感元数据；positions 文件可能带敏感路径且修改会触发重放，不默认读取全文件或重置。配置凭据、tenant token 不输出。",
                    "若采集器在 Kubernetes，原生仅可核对 Pod/DaemonSet 覆盖、重启和事件；ConfigMap、Loki API 和历史日志需已选 SSH 的实际客户端/授权。对象存储请求错误只能依据已有日志，不读取云密钥或猜测存储接入。",
                ),
                "拒绝 reason、重试策略和缓冲保留决定日志是延迟还是已丢弃；查询时间窗错位也会产生看似缺失。提高 tenant 限额不能修复标签爆炸或错误时间戳，积压回放还可能再次超过限制。",
                "重置 offset、清 positions 或回放会产生重复与流量峰值；关闭时间校验可能污染索引。批量导出日志会泄露业务/个人信息，不能默认打开采集 debug 或安装新采集器替代现有链路。",
                "审批单明确源范围、拒绝量证据、标签/解析/限额单项修订、缓冲与回放预算、停止和原配置恢复；重启采集器、修改 offset 与配置均是写操作。历史缺段不可恢复时准确报告，不伪造补齐。",
                "在同 tenant、源标签和时间范围确认新日志新鲜度、拒绝增量与缓冲消退，验证重复/丢失边界；已有日志未授权不读取载荷。仅指标恢复时只报告摄取链统计，历史完整性仍待证明。",
            ),
            _document(
                "logql-streams", "Loki 高基数 stream 与 LogQL 扫描", "ssh",
                "适用于查询超时、too many outstanding requests、流数增加或 ingester 内存升高。输入受影响 selector、tenant、版本、允许时间窗和实际查询统计，限制日志内容及 API 返回规模。",
                (
                    "通过已选 SSH 的现有安全客户端或负责人脱敏查询记录，保存具体 stream selector、start/end、step、limit 和执行耗时；不在 URL 放 token，不请求全租户 /series 或标签值全集，不默认返回日志正文。",
                    "检查 stream labels 是否包含 request_id、user_id、完整 URL、随机文件名或 Pod UID，结合已有活跃 stream 与创建速率证据；标签组合定义流，不用单标签值数量直接相乘估计全部真实基数。",
                    "LogQL 先用明确 job/namespace/app selector，再做 |= 等字面过滤，必要时解析 json/logfmt 和正则；解析错误 __error__ 与 unwrap 的数值单位按实际表达式核对，过滤顺序应保留业务含义而非机械重排。",
                    "有权限才读取该次 query_range 返回的 stats 中扫描字节、行数、队列和执行时间，限制短窗和结果数量。structured metadata 与 label 的区别及支持按版本确认，不把迁移标签当无需 schema/配置变更。",
                ),
                "高基数 stream 增加索引、chunk 与 ingester 内存，扫描成本也受 selector、时间窗和 pipeline 影响；两者不能混为一谈。日志 rate 不是业务请求率，解析或采集缺口会影响统计分母。",
                "宽正则 selector 与大时间窗查询会加重故障，增加 query parallelism 可能把压力转向对象存储；随意丢标签会改变流与查询语义。delete API、retention、重建索引与回放都改变历史数据，不能默认执行。",
                "提交精确标签治理或单查询改写、有限样本对照、告警依赖、容量与原配置回退，经后台审批。涉及采集器/租户 limits/schema 由实际负责人批准，不把记录的优化表达式说成已上线。",
                "对相同有限时间窗比较扫描量、耗时、解析错误与结果覆盖，确认关键日志检索和告警未失去维度；流数下降需多个真实周期观察。只有查询变快而漏掉日志时不算恢复，未实查则保留待验证。",
            ),
        ),
        scope="ssh", color="#f97316",
    ),
    _preset(
        "opensearch-shards", "OpenSearch 分片与分配",
        "按未分配原因、磁盘水位和分片规模解释集群颜色，避免危险的强制主分片分配。",
        (
            "OpenSearch 分片 decider 与磁盘水位诊断",
            "用受限 cat 与 allocation explain 证据区分副本不足、主分片丢失和磁盘保护。",
            "输入 OpenSearch 版本、单个 index、节点角色、集群健康变化和安全连接来源；只在选中 SSH 的既有"
            "授权 HTTP 客户端读取 _cluster/health、限定 _cat/shards 与 _cat/allocation，不在命令放密码或读取证书私钥。"
            "对一个未分配分片使用获准只读 allocation explain，记录 decider、last_allocation_status、node 和原因，"
            "它虽可为 POST 仍需后台按只读诊断请求授权，不执行 _cluster/reroute。区分 yellow 副本缺口与 red 主分片不可用，"
            "核对 low/high/flood_stage、read_only_allow_delete、awareness 和 tier/filter；不默认全索引扫描查询。"
            "改 replica/watermark、清 block、force allocation、删 index、reindex 与 shrink 全部审批，不能接受数据丢失标志强推。",
        ),
        ("OpenSearch 分片顾问", "专注分片分配原因、磁盘保护与恢复副本，不自动强制分配旧主或删除索引。"),
        (
            _document(
                "unassigned-deciders", "OpenSearch 未分配分片与 decider", "ssh",
                "适用于 yellow/red、UNASSIGNED 或 shard failed。输入明确 index、分片号、primary 标识、版本和节点角色，避免全集群 explain 或搜索业务文档来确认数据存在。",
                (
                    "选中授权 SSH 的现有安全 HTTP 客户端读取 /_cluster/health/目标索引 和 /_cat/shards/目标索引?format=json&h=index,shard,prirep,state,unassigned.reason,node；URL 路径需按真实索引安全编码，不在 URL 放密码或 token。",
                    "yellow 多为副本未分配，red 至少有主分片不可用；记录采样时间和 active/initializing/relocating 数，颜色不是业务完全性证明。节点数和副本配置先核对，单数据节点配一个副本可长期 yellow。",
                    "对一条未分配分片申请 /_cluster/allocation/explain，提交 index、shard、primary 的最小请求；这是只读诊断但 POST 仍需后台明确授权。只保存 decider、decision、explanation、last_allocation_status 与节点引用，不执行 reroute。",
                    "对照 disk_threshold、filter、awareness、same_shard、throttling 等实际 decider，核对节点角色和目标存储层；已有索引设置只取 number_of_replicas、routing.allocation 相关字段，不读取业务 _source 或安全插件配置。",
                ),
                "缺副本与丢主分片恢复路径不同，no_valid_shard_copy 需要可用快照或原数据节点证据；不能把任何 UNASSIGNED 都用降低副本解决。集群颜色恢复 green 也可能是在副本数被降低后发生。",
                "allocate_stale_primary/empty_primary 的 accept_data_loss 会破坏数据，禁止当常规修复；取消分配过滤可能让敏感索引落到错误节点。reroute、删索引、关闭索引与副本设置都是写操作。",
                "提交单分片阻断原因、有效副本/快照、容量和最小配置方案，经后台审批并由索引负责人确认。没有有效主副本证据时先保护现场与恢复点，不反复强制 retry_failed 或接受数据损失。",
                "复查分片在批准节点 STARTED、decider 阻断消退、恢复与迁移队列稳定，再由获准业务验证索引完整性。只 cluster green 而未确认副本策略与数据时，不能宣布消息/文档无损恢复。",
            ),
            _document(
                "watermark-shard-size", "磁盘 flood stage 与分片规模风险", "ssh",
                "适用于 index read-only / allow delete、磁盘高水位、重定位抖动或过多小分片。输入目标索引、节点数据盘、真实水位配置、恢复窗口和索引保留负责人，不先删除索引腾空间。",
                (
                    "安全授权客户端有限读取 /_cat/allocation?format=json&h=node,shards,disk.indices,disk.used,disk.avail,disk.total,disk.percent 与目标 /_cat/shards 的 store；只读元数据并脱敏拓扑，不导出所有业务索引名或文档。",
                    "经授权选择性查询 cluster settings 的 low/high/flood_stage 及索引 blocks.read_only_allow_delete，明确 transient/persistent/default 优先级和百分比/剩余字节语义；不同版本自动解除 block 行为需核实，不凭经验写死。",
                    "对照目标盘 df、分片大小、节点角色与 relocation，disk.indices 与 df 差异可能来自 translog、其他文件或保留，不能当空间凭空丢失。索引删除、段合并和快照成本需独立评估，禁止全盘扫描。",
                    "统计目标索引主/副分片数量、大小分布和真实恢复耗时，过多小分片增加堆/调度开销，过大分片增加迁移恢复时间；没有查询和写入历史不能给统一最佳分片 GB 数或默认 reindex。",
                ),
                "flood stage block 是保护磁盘，空间未恢复前清 block 可能马上重现；high/low 水位控制分配行为，节点全满会让迁移无目的地。降低副本或保留期可释放数据但会改变可靠性和历史覆盖。",
                "force merge、shrink、reindex、删索引和提高水位都可能增加 I/O、临时空间或数据丢失；不能直接 rm 节点数据目录。快照成功记录不代表已可恢复，唯一副本不应作为清理候选。",
                "审批方案列明索引保留、可恢复快照、预计空间、临时峰值、单项设置与原值；清 block 仅在余量足够、版本流程确认后获批。扩容不可逆费用和数据重构风险由业务/存储负责人确认。",
                "复查磁盘余量、watermark、block、分片恢复队列和原索引请求，确保没有持续增长或重定位振荡。真实写验证单独审批，只有元数据可读时不得假称索引写入和数据完整性已经生产验证。",
            ),
        ),
        scope="ssh", control_level="approve", color="#1d4ed8",
    ),
)

_FIELD_NOTES = {
    "rollout-stall": (
        "补取控制器条件时还要分清 Available 与 Progressing：前者只证明当前仍有足够可用容量，后者可能因创建新副本集、扩缩副本或实例变为可用而更新时间。把这两条条件和新旧实例数量放在同一张时间表，才可判断是旧版本托住服务还是新版本已真正接流。若副本正在终止，资源释放往往晚于声明数量下降，应保留终止宽限期和节点实际占用证据，不承诺滚动预算给出的瞬时资源上界绝不会超出。",
        "现场还需检查是否有人修改 paused、replicas 或模板：一次扩缩容与一次模板发布不是同一代变更，旧审批不能自动覆盖后来的差异。事件报 quota 时补配额证据，报卷冲突时转卷生命周期，不把它们统称发布超时。明确停止条件为可用容量跌破已批准底线、健康旧副本意外终止或出现数据兼容错误；达到条件先停止推进并重评，不等待计时器耗尽后再作决定。",
    ),
    "replicaset-history": (
        "核对模板差异时注意 pod-template-hash 不是可人工编辑的发布版本接口，控制器以完整模板变化生成新的副本集；只改副本数通常不应产生新模板。对同标签不同摘要的实例，保留运行节点、实际镜像标识与启动时间，区分仓库标签移动和旧实例缓存。副本集的所有者引用若指向旧控制器或为空，不应纳入当前发布链，更不能为了整理现场把它重新挂到当前控制器。",
        "恢复候选需要回答旧配置是否仍可解析、镜像是否被保留、旧程序能否读懂已写入的数据三个具体问题；不能用旧实例仍在运行代替下一次启动能力证明。若对比发现非本次审批的端口、权限或卷变更，先拆分责任和变更批次再制定回退。对发布效果采用版本分组的业务证据，旧副本持续服务可能掩盖新副本错误，整体错误率正常并不表示新版本已合格。",
    ),
    "ordinal-update": (
        "按序记录每个成员最后一次 Ready 转换、容器重启和应用入群完成时间，确定控制器是在等探针还是应用自己拒绝服务。分区大于副本范围时可能完全不替换实例，低于起始序号时又可能覆盖全部目标，需按实际序号计算，不只写百分比。部分新版提供额外滚动并发能力，只有当前接口确实接受并启用时才能纳入计划，不从别的集群示例假定可用，也不默认一次允许多个数据成员离线。",
        "一次失败更新后，先把期望模板修回批准版本，再重新读取实际坏实例和控制器状态，明确是否需要单独重建才可解除等待。重建前由应用负责人确认该成员不是唯一最新副本、不会因名字复用再次注册为第二个活跃成员。若旧实例仍 Terminating、卷仍指向旧节点或成员状态无法取得，应停止推进；剩余成员表面 Ready 不能替代投票多数、复制进度和数据保护点。",
    ),
    "identity-retention": (
        "存储保留策略之外还要核对实际 PVC 的 ownerReferences、删除时间及 finalizers 元数据，判断控制器是否已建立与当前缩容语义一致的所有权；不要直接移除 finalizer。控制器删除再用同名创建会得到新 UID，旧 PVC 名字相同也不代表自动获得正确应用成员身份。为每个序号保留卷引用、网络名和应用内部成员标识的对应关系，只记录必要摘要，避免把数据目录内容当作身份清单导出。",
        "若业务需要缩容再扩回，先区分临时停用成员与永久移除成员：前者可能复用原数据继续追赶，后者可能要求受支持的重新加入或重新同步。确认下线期间日志保留窗口、复制源可用性和重新同步预算，否则保留卷也不保证能快速恢复。恢复时看到旧记录不等于它们是最新数据，要由负责人核验检查点与复制追赶；没有可用恢复点时不得覆盖原卷做重试实验。",
    ),
    "eligible-nodes": (
        "对缺席节点建立明确的排除理由，不把 desired 与集群总节点的差额直接列为缺陷。新加节点可能缺少业务池标签或运行不同架构，现有守护镜像的多架构索引也可能不覆盖它；只有实际镜像和节点字段支持才作结论。设备插件和安全代理还可能依赖宿主驱动、内核能力或证书注册，这些不能从 Kubernetes Pod 规格自动推导。没有该节点 SSH 时保留宿主依赖待证，而不是宣称插件安装完整。",
        "对 numberMisscheduled 不采用立刻删除作为默认纠正，先确认节点标签何时变化、实例是否仍承担日志转发或网络功能，再由控制器与业务维护流程处理。若该守护组件承担远程访问链路，审批里必须说明失败后由谁通过何种现有通道恢复。验收应有每节点功能证据，例如最近一条上传记录或批准路径的转发结果；仅覆盖率达到百分之百不能排除实例空转、认证失败和代理队列积压。",
    ),
    "daemon-rollout": (
        "更新期间应保留逐节点旧新实例表，尤其注意节点驱逐、污点变化和另一次模板更新是否改变本轮目标。新旧实例并存时同一 hostPath 的写入格式、锁协议和注册 ID 必须兼容，否则所谓无空窗更新反而会损坏宿主状态。滚动百分比换算需要以该控制器当时的合格节点数为依据，节点池扩缩会改变预算，审批不能只引用发布开始时的一个固定数量。",
        "验证系统代理应分别检查进程就绪、宿主资源交接和上游服务确认三层：日志代理需要新日志成功送达，网络代理需要原业务方向连通，存储节点代理需要受支持的卷功能证据。不要通过创建无关测试资源擅自证明能力，也不把已有缓存流量当新链路可用。若更新后只有一部分节点功能下降，先冻结扩大范围并按节点对照旧版本，避免全局回退掩盖单节点宿主依赖问题。",
    ),
    "job-failures": (
        "将任务执行标识与业务批次标识分开保存：同一业务批次可能出现多个 Job UID，同一 Job 也可能有多次容器尝试。核对成功实例的完成时间与外部结果提交时间，若进程在提交之后、报告成功之前退出，控制器重试可能再次处理同一工作项。Indexed 模式的索引只是分配工作的一种机制，不证明应用按索引幂等；索引参数如何传给程序、断点是否持久都需任务负责人确认。",
        "新增重试策略前核对哪些退出码被视为可重试、哪些代表确定性输入错误，只有实际版本支持相应失败策略时才设计规则。对于超过期限的任务，确认它是否仍有外部子进程或异步请求在执行，Pod 终止不能撤销已发出的支付、邮件或数据导入。验收分别报告控制器完成、批次结果完整和重复副作用核对，三者证据不同；只取得第一项时保留业务未闭环，不伪造补跑成功。",
    ),
    "cron-scheduling": (
        "日历解释还应核对控制器版本对时区字段的支持，不能把 TZ 或 CRON_TZ 文本硬塞进 schedule 来代替正式字段。为一次漏跑保存应执行的业务日期、系统应触发时刻和任务真正开始时刻，夏令时重复或缺失小时需显式标注。历史保留数只控制已结束任务的记录数量，不是重试次数，也不代表业务保留政策；修改历史上限可能减少后续排障证据，因此不能为了列表整洁随意降低。",
        "处理挂起恢复时先列出潜在补触发，再核对起始期限和当前活动任务，不能承诺取消挂起一定补齐或一定不会补跑。跨天批处理往往用参数决定业务日期，手工复制模板如果仍取当天日期，会在命令成功时处理错误批次。审批要列出业务参数的非敏感摘要及单批结果核对方式；若前一批次结果未知，先冻结后续补跑，避免用更多定时执行扩大无法追溯的重复工作。",
    ),
    "metric-chain": (
        "对容器资源指标要区分新旧 Pod、容器更名和 sidecar 变化，目标容器名不匹配会使看似正常的总 CPU 无法用于指定容器伸缩。内存 Utilization 也以请求为分母，不是相对 limit 的占用；修改 request 既改变调度预算，也会改变同一实际使用量下的伸缩判断。外部指标的 Value 与 AverageValue 表达不同，需负责人确认队列长度是总量还是按实例平均，不能把两个目标值直接互换。",
        "核查指标采样时间、适配器缓存期限和新实例就绪窗口，避免拿旧指标解释新模板的副本决策。若目标控制器已扩到期望但 Pod Pending，指标链可能已正常，下一步应转调度与容量而非继续降低目标阈值。若应用受连接池或下游配额限制，增加副本可能只增加竞争。验收时把指标可用、控制器建议、实际副本和业务性能分别列出，缺少其中一层时不补写推断结果。"
        "适配器返回拒绝访问与服务不可用应分别记录响应码，前者补核最小读取权限，后者核对已有适配器服务状态；"
        "currentMetrics 缺项不能填零计算副本。若监控图仍有数据，需确认它和 HPA 使用的是同一指标名、标签选择与采样窗口，"
        "不能拿另一个租户或旧容器的数值证明伸缩输入正常。",
    ),
    "behavior-limits": (
        "速率策略中的百分比以当前规模与策略窗口解释，Pods 与 Percent 同时存在时还受 selectPolicy 选择影响，不能把两条允许变化数简单相加。禁用某个方向的伸缩不等价冻结所有方向，保留实际字段与默认行为来源。对 scaleDown 稳定窗口，应说明它保留近期建议而非等待每个低负载样本固定倒计时；连续高低波动可能使缩容被延后，这是保护意图而非必然故障。",
        "副本变化要与其他管理者比较：GitOps、人工 scale、定时任务或另一个控制器也可能写同一伸缩子资源，造成 HPA 看似振荡。通过字段管理者与事件确定控制权后再改算法参数，不能用更长窗口遮住写入竞争。恢复验证覆盖业务高峰和下降阶段，核对最低副本能承受一个故障域损失；只有低峰缩容成功而峰值扩不上去，不能认定弹性策略验收通过。",
    ),
    "eviction-denied": (
        "还需检查预算是否由正确控制器规模推导：Deployment、StatefulSet 与没有可识别控制器的 Pod 在计算预期数量时并不完全等价。若一个 Pod 同时命中多份 PDB，当前驱逐接口可能直接拒绝这种重叠，应以真实 API 返回和版本为准，不假设分别通过就能驱逐。对因 rollout 产生的临时 Ready 波动，等待健康收敛比立即放宽预算更可控；维护审批应引用最新状态而不是昨日健康截图。",
        "对于已经不健康的待驱逐实例，需要区分它是否占用业务写身份以及当前 unhealthyPodEvictionPolicy 的语义，即使驱逐被允许也不代表卷或旧进程安全退出。计划逐节点维护时，每一步应重新计算剩余可用成员和故障域，防止先前批准的多项维护并发耗尽同一冗余。恢复条件除预算数字外还要包含业务复制、流量和新实例稳定时长，不能仅等待 disruptionsAllowed 回到正数便继续下一轮。",
    ),
    "budget-design": (
        "设计预算时给出小规模边界样例：副本从大规模缩到两份或一份后，同一百分比可能因向上取整产生完全不同的允许中断数。明确业务需要的是至少多少健康成员，而不是只表达常见维护百分比；同时核对 HPA 最低规模和发布策略，否则在自动缩容后预算可能不可满足。不同故障域的成员数量还需满足应用投票与数据副本要求，不能用跨区 Pod 数替代实际选主规则。",
        "对临时例外记录责任人、精确对象和到期恢复动作，避免维护结束后长期留着放宽预算。实际驱逐若被其他准入、安全策略或卷生命周期阻断，不能继续下调 PDB 追求命令成功。预算验收至少包括选择器覆盖的正反例、当前健康数计算与受控维护流程检查；没有获批演练时只说计算和配置已审阅，不宣传实现了所有自愿与非自愿故障的零中断保证。",
    ),
    "quota-rejection": (
        "配额事件可能由 ReplicaSet 而不是 Deployment 产生，且聚合事件的最后时间会随重试更新，首次报错与每次重试不应合并成一个精确计数。保存错误里的请求量、当前量和上限后，再用最新对象对照，避免事件属于旧模板。若有多个工作负载同时扩容，当前余量不能被每一份审批重复承诺，命名空间负责人需要协调总预算与发布顺序，而不是各自看到尚有余量就并行推进。",
        "对 CPU、内存请求和限制要分别列预算，资源修改可能解决某一键却触发另一键；未声明的默认请求也应纳入。终止中的实例与资源统计收敛可能存在时间差，不能通过连续创建失败对象逼迫控制器刷新状态。成功创建后还要检查调度、探针和业务容量，配额只是一道准入门，不保证后端存储、节点资源或依赖配额充分。若提额被拒绝，应保留容量缺口而不是改命名空间绕过治理。",
    ),
    "quota-scopes-storage": (
        "核对作用域时必须保留字段是否缺省，某个对象没有显式资源声明但经准入注入之后可能不再属于 BestEffort。优先级作用域与抢占能力也不能混淆，允许该优先级创建并不保证能放置到节点。存储类专属额度的键名应来自真实状态，不能自行拼写后断言未配置；配额用量更新与后端物理占用是两套账，卷快照、精简配置或文件系统余量都不能直接抵扣 API 请求配额。",
        "如果对象计数触顶，首先核对是否存在合法保留的历史资源和安全控制对象，而不是把列表中最老对象当废弃项。Secret 计数可由授权摘要证明，但没有任何必要读取其数据。对 PVC 的扩容审批同时记录一般存储配额、存储类配额和底层容量，且说明失败后的受支持处理；已扩容量不能按普通配置回退缩小，不能以撤回配额声明承诺恢复原磁盘大小。",
    ),
    "default-injection": (
        "将旧 Pod 创建时刻与规则最后修改时间对齐，若缺少审计记录，只能说与准入默认一致，不能断言某条规则历史上何时生效。资源默认值按容器应用，init 容器与可重启 sidecar 的实际字段也要检查；Pod 层的默认和容器层限制不能混算。对工作负载负责方展示模板值、实际值和推定来源三列，避免把准入后的值误当开发者显式配置，进而在下一次发布中无意重复放大请求。",
        "如果命名空间同时存在多份 LimitRange，不依赖默认注入的选择顺序来构建业务保证；关键容器应由负责人批准明确资源，减少不同准入组合造成的变化。恢复验证不能只盯着调度成功，降低 limit 后出现的内存终止或 CPU 限流也要与新字段关联。未取得使用指标时保留风险，并建议按正常峰值补采样，不从空闲实例的一次读取推导可以统一降低所有容器资源。",
    ),
    "range-conflicts": (
        "准入错误可能引用默认注入后的请求或限制，校验时应把缺省值先展开为实际候选，再比较 min、max 和比例，不能只拿模板里的两个字段做算术。Pod 级范围还可能涉及应用容器与初始化阶段的有效资源规则，应按当前集群版本确认，避免把普通容器求和规则套到所有情况。记录单位转换过程，尤其避免内存数量中 m 与 Mi 的误写；这类语法合法但语义错误的值应由业务负责人重新确认。",
        "对于存储请求，规则改变不代表已绑定卷会自动变小或自动迁移，已有 PVC 的后续修改仍可能被当前准入验证拒绝。若最小值高于业务需要，需要命名空间所有者决定治理规则，而不是让业务伪造大量请求以通关。审批前列出其他新建工作负载是否依赖原默认和范围，防止单应用修复造成全空间发布故障；验收保留一份合法值与一份应被拒值的离线判断，不默认到生产创建试错资源。",
    ),
    "node-affinity": (
        "评估节点集合时同时保留标签的存在与值，NotIn、DoesNotExist 等否定表达式容易因缺标签产生与直觉不同的匹配结果，需按 API 实际选择器语义逐项核对。matchFields 支持字段受限，不能当任意节点状态筛选器。若调度器 profile 追加了不可见约束，先记录 schedulerName 和事件返回，不以修改业务模板去抵消隐藏策略，更不能直接指定 nodeName 绕过调度和安全校验。",
        "节点标签在运行后改变通常不会迁移旧实例，所以候选节点和已运行节点需要分别说明。调度恢复后验证最终节点的架构、存储区域和业务池归属，不能把 selector 放宽后偶然进入的节点算作合格。对于硬件或许可绑定工作负载，还需负责人确认其专用设备与授权不因迁移失效；没有证据时给出候选集合和缺口，不建议以删除所有 required 条件作为通用恢复。",
    ),
    "interpod-affinity": (
        "检查跨命名空间范围时，namespaces 与 namespaceSelector 的组合关系按实际 API 展开，不能只选其中一个较窄集合。拓扑域是节点标签值相同的一组节点，缺该标签或命名不统一会让规则无法按预期表达故障域。自亲和的首实例存在特定调度防死锁语义，需核对 selector 是否真的包含自身，不能直接认定没有任何现存同伴就必然无法启动，也不能据此保证复杂多工作负载环一定可解。",
        "发布时若新旧实例都命中同一反亲和选择器，旧实例可能占满所有合法域；修改滚动预算、补域或有意按版本区分选择器各有可用性代价。先列出每个候选方案对故障域损失与剩余业务容量的影响，再由负责人选择。不要改控制器不可变 selector 或共享业务标签来绕开冲突；恢复后保存各副本实际节点与拓扑值，确认新规则没有让另一批次陷入相同等待。",
    ),
    "skew-pending": (
        "计算每条约束时保留其选择器覆盖实例和合格域清单，多个 topologyKey 如 zone 与 hostname 是同时约束，不能分别找到一个满足节点就认定整体可调度。某域有匹配实例但当前没有可调度节点时，要依据资格策略说明它是否参与全局最小值计算。minDomains 只应在当前 API 允许的组合中使用，缺少字段不意味着默认要求多个区域；实际字段、版本支持与业务容灾要求必须分开记录。",
        "故障恢复后即使原域重新出现，调度器一般只处理待调度实例，不自动把已运行副本搬回理想均衡。由此产生的分布偏差需要先评估业务冗余，再考虑独立审批的重排，而不是连续删除 Pod 直到看上去均匀。验收可逐域展示当前匹配数、加入一个实例后的偏差和不符合节点的理由，便于复核算法；不依赖一张集群总副本饼图宣称多区域容灾已经满足。",
    ),
    "spread-rollout": (
        "按版本统计时，pod-template-hash 或其他 matchLabelKeys 值应来自实际入场对象，不能手动重写它们去制造新分组。不同版本 API 对该字段的合并和变更行为可能不同，先查看服务器认可的声明与对象，再设计发布规则。对于软分布，将每域可用 CPU、内存和卷拓扑一起对照，落点偏斜可能是唯一可行容量而不是规则失效；调度评分来源不足时只能给候选解释，不虚构调度器逐项分值。",
        "如果软规则升级为硬规则，先以当前最小副本与单域故障分别推演，确保不会在故障期间因为保均匀而损失可用容量。反向从硬改软则需要负责人接受共置风险，并设置临时期限。对外报告区分声明希望的分布、当前真实分布和故障时可维持的分布，只有后两者有实际容量或演练证据才能称已验证；发布窗口内的偶然均匀不等于长期自动均衡保证。",
    ),
    "taint-matching": (
        "识别自动污点时要查看节点条件与控制器时间线，节点恢复后仍有污点可能是管理者同步滞后，也可能是人工同名隔离，不能看到 key 相似就自动移除。针对专用节点，用明确键值而不是空 key 通配 Exists 描述授权范围；还需检查 Pod 是否通过其他自动注入容忍获得额外资格。若当前只读接口不能解释注入来源，应保留这一证据缺口，不把模板中没有写当作实际没有权限进入。",
        "污点变更与 cordon 是不同机制，维护窗口内两者可能同时存在，要分别记录节点是否可调度及 Pod 是否受污点拒绝。允许业务进入控制面、GPU 或隔离池还可能消耗稀缺设备和影响安全策略，不能只比较 CPU 内存。恢复报告逐条列出匹配与未匹配污点，并核对真实落点；只增加一条宽容忍让实例运行，不代表保留了维护隔离和业务专属节点的原意。",
    ),
    "noexecute-eviction": (
        "驱逐时限的起点与控制器实际处理有关，不应凭 Node lastTransitionTime 简单相加便断言精确删除秒数；节点条件、污点出现和删除请求要分开取证。DaemonSet 或其他控制器可能注入无限容忍，用户模板与最终 Pod 必须对照。部分集群可禁用或替换相关驱逐控制器，只有真实控制面配置能解释此差异，不能拿另一集群默认行为补写当前现场。",
        "对失联有状态成员，管理平面的对象删除与主机上的进程停止是两件事；在链路分区下旧成员可能仍能访问存储或客户端。审批前必须说明隔离动作由谁执行、何种证据证明旧写者已经失效，再考虑在新节点恢复身份。节点重新上线后还要检查旧实例是否被正确清理、数据卷是否保持唯一使用者；新副本 Ready 与预算恢复并不能自动排除曾经发生的双写风险。",
    ),
    "probe-restarts": (
        "HTTP 探针通常由 kubelet 直接访问 Pod 地址而非经过 Service，除非显式配置了 host 等字段；因此从业务入口返回成功不能证明探针路径正确。HTTP 探针对 HTTPS 的处理与完整业务 TLS 客户端验证也不同，不应拿其成功证明证书链可信。exec 的 shell、环境、权限和工具是否存在需要镜像证据，不能假设镜像带 curl；gRPC 健康检查的服务名和数字端口也不能照搬 HTTP 的具名端口写法。",
        "计算启动容忍窗口时同时考虑探测调度、超时和阈值，公式只是预算估计，实际日志与事件时间才是发生证据。一次正常热启动不代表冷缓存、数据恢复或依赖初始化下的最慢启动。探针修订应保留真正进程失效时的检测能力，不能把所有超时都无限增加；新旧模板分别比较启动和重启增量，确认不是通过延迟检测让不健康实例暂时看起来稳定。",
    ),
    "readiness-routing": (
        "多个容器的 Ready 要逐个核对，sidecar 未就绪或额外 readinessGate 未更新均可能使整个 Pod 退出后端。EndpointSlice 的 ready、serving、terminating 字段涉及终止语义，不能只找一个布尔值就忽略连接排空；无权限读切片时，必须把实际后端是否摘除留作缺口。就绪探针的成功阈值与存活、启动探针字段限制不同，修订前以 API 校验和当前版本支持为准，不粘贴不合法的统一参数。",
        "流量恢复需要覆盖入口传播、连接复用和长请求，不仅是 Pod Ready 转为 True 的瞬间。某些客户端会缓存地址或保持旧连接，Service 配置正确也可能暂时仍向退出实例发送请求。审批时明确可接受排空时长和业务是否支持中途取消；若没有真实请求源证据，验收只能描述资源和后端声明，不能从另一台主机的短 GET 成功推导所有用户事务已无损切换。",
    ),
    "ingress-routing": (
        "区分控制器接管、规则合并和外部地址发布三个阶段：IngressClass 或注解匹配成功后，仍可能因同 host/path 冲突被另一对象覆盖。只在授权范围找同域路由元数据，避免导出其他租户完整入口。Prefix 匹配按路径段语义而非任意字符串前缀，ImplementationSpecific 的行为则由控制器决定；路径重写后应用收到的 URI 与客户端原 URI 不同，需将两者对应才能判断应用 404。",
        "上游端口名应对照 Service port 名，而不是直接取容器端口；TLS 到边缘成功不代表控制器到后端的 HTTP/HTTPS 协议一致。若错误只发生某一个入口地址，核对控制器副本版本和配置同步，不通过修改全局规则掩盖局部副本故障。恢复验证保留准确 host、SNI、path、请求方法与后端身份摘要，同时检查既有合法路径未被新规则抢占，避免修好单路径却破坏其他业务。",
    ),
    "edge-tls": (
        "公开证书查询不应包含会话恢复密钥、完整客户端身份或任何私钥材料；在自建 CA 场景，验证使用的是组织批准信任根，不能临时信任服务器自报证书来制造成功。TLS 证书与 HTTP 路由 host 需要分别匹配，有些入口先按 SNI 选证书再按 Host 选后端。主机系统时间异常也会造成过期或未生效错误，必须用时间同步证据区分，而不是立刻请求重新签发全部域名。",
        "续期故障需找到颁发、保存、分发、加载和对外暴露的实际卡点，ACME 订单成功不等于所有入口已换证。挑战失败可能涉及路由、外部 DNS 或网络访问，只有已有授权才能补查，不能读取 DNS API 密钥或删除 TXT 记录试错。若已过期证书是唯一恢复材料，回退不能承诺继续可信服务，应由证书负责人明确应急方案；验收保留公开指纹与各入口采样时间以识别混合版本。",
    ),
    "cluster-domain": (
        "检查 Service 名称时区分普通 ClusterIP、Headless、ExternalName 与无 selector 服务，它们的 DNS 答案来源和就绪影响不同；不能对所有类型统一期待一个固定虚拟 IP。搜索域和 ndots 可能让看似外部名字先尝试多次集群内扩展，造成额外延迟，需实际 resolver 配置证明。CoreDNS 的 kubernetes 插件需要正确同步 API 对象，日志中的权限或 watch 失败应与 NXDOMAIN 分开解释，不默认改插件 RBAC。",
        "缓存中已有记录可在 API 同步异常时暂时维持部分名字，因此同时测试一个既有服务与经批准的新变更记录更有区分度，但创建测试对象仍须审批。对 A、AAAA、SRV 应按业务真实查询类型分别核对，单次 A 成功不能说明所有发现方式恢复。报告记录查询源、resolver、完整名字、类型、答案和 TTL，保留负缓存与传播窗口；不能只提供一张 Pod 全绿列表作为 DNS 服务已经正确恢复的证据。"
        "查询 SRV 时还需记录 Service 中命名端口的名称、协议及目标端口，名称拼写错误可能只影响该发现方式；"
        "Headless 的答案应与实际合格后端对应，不要求它返回 ClusterIP。修复后先等相关正负缓存到期再复测，"
        "同时保留原查询类型，避免用一条不同记录的成功回答掩盖原故障。",
    ),
    "forward-loop": (
        "确认上游地址是否经过本地 stub、节点缓存 DNS 或额外代理，每一跳都要有实际配置来源，不能从 Corefile 一行地址推断完整链路。若节点 resolver 引用回环地址，容器内同一个地址不一定指向宿主服务；hostNetwork、挂载文件和节点缓存模式需分别核对。插件链的 fallthrough 可能使某些域继续向上游而其他域由集群权威处理，故障分布应按域后缀与查询类型统计，不只抽一个公网名字。",
        "对缓存与上游健康检查要区分命中、转发成功和失败响应缓存，缩短 TTL 或清缓存本身会增加上游压力。协议差异、响应截断和防火墙可能让 UDP 小响应正常而 TCP 重试失败，主动查询必须限定目标与次数。修复后等待相关缓存窗口，再从原 Pod 路径确认新答案与上游实际响应；若只在 CoreDNS 自身或管理机查询成功，保留客户端路径未覆盖，不声明整个集群外部解析已恢复。",
    ),
    "sandbox-ipam": (
        "CNI 调用由运行时触发，错误中可能包含多级插件链，需保存第一个真实失败插件与后续包装信息，不能把最外层 sandbox 字样当根因。多个配置文件、插件版本不匹配或节点重装后残留状态都需要明确宿主证据；文件可能包含认证引用，不能完整导出。IP 池可用量与节点 PodCIDR 范围也不一定相同，是否按块分配、借用和回收取决于实际插件，不拿通用网段减法冒充已验证 IPAM 余量。",
        "地址泄漏判断要同时证明分配记录仍存在且没有对应活跃 sandbox、节点或外部使用者，Pod 列表为空并不足以批准回收。网络分区时控制面可能已经重建对象而旧节点仍持地址，错误回收会制造重复 IP。恢复验证除了新实例拿到地址，还要核对路由宣告和必要服务路径；如果只成功创建 sandbox 但没有网络功能测试，应明确阶段性结果，不声称跨节点和策略执行已经一并恢复。",
    ),
    "cross-node-path": (
        "每条路径记录原始源目标与 Service 转换后的真实后端，避免拿不同目标比较得出同节点与跨节点差异。overlay、直接路由、eBPF 数据面和服务代理模式对路由表可见性不同，主机 iptables 或 ip route 没有相关条目不证明不存在转发。MTU 应对照物理接口、封装开销和容器接口的实际值，不能直接统一改成网上常见数值；路径中的隧道、VPN 或云网络限制也需对应负责人提供证据。",
        "有状态连接与新建连接可能走不同 conntrack 或负载均衡状态，所以验收既检查已建会话，也在批准范围确认新连接。对策略变更应列出精确 selector、方向、端口和原允许关系，不能以全量 allow-all 验证推测。发现丢包计数需与相同时间、接口和业务流关联，其他流量造成的错误不能直接归因。若需要抓包，只捕获批准元数据并预设上限，不保存敏感载荷或无界监听。",
    ),
    "attach-mount": (
        "卷生命周期可能包含动态供给、控制器发布、节点暂存和节点发布多个调用，事件中的失败方法名可帮助定位是否已经完成前一阶段。部分驱动不需要 attach，缺少 VolumeAttachment 未必异常；先核对 CSIDriver 对应能力再判断控制器是否漏建对象。对卷路径、后端 handle、PV 与 PVC 的关联采用脱敏摘要，不能因同一个存储类就认定底层卷相同，也不能将路径中的凭据或租户数据放进事故报告。",
        "节点恢复后旧 mount、设备映射和应用进程的真实状态需由授权节点或存储负责人确认，API 对象消失不证明后端已经安全释放。某些驱动需要先暂存再发布，节点插件 Ready 也可能因为宿主依赖未就绪而挂载失败。验收对照原错误阶段逐项证明前进，并核对应用看到的卷身份；没有数据一致性证据时，正确表述是挂载恢复、数据待核，而不是把正常探针返回当作唯一数据副本完整。"
        "volumeMode 为 Block 时核对 volumeDevices 的设备引用，不应要求出现文件系统 mountPath；"
        "文件系统卷还要区分只读挂载标记和访问模式，两者不互相替代。修复方案若改变节点或挂载方式，"
        "审批中列出对应设备身份和应用预期，不能因某个路径存在就认定已经挂上正确数据卷。",
    ),
    "volume-expansion": (
        "扩容前后记录 PVC UID、PV 名与卷 handle 摘要，避免管理员替换新卷后仅因容量符合就误判原数据完成扩展。驱动可能先扩大后端，再等待节点扩文件系统，暂时的请求量、绑定容量和挂载容量不一致应按阶段解释。文件系统卷与原始块卷的验证方法不同，后者不能用 df 结论；应用若使用分区、加密或逻辑卷，还需对应层受支持扩展流程，不能直接在线调用系统工具跳过驱动管理。",
        "失败恢复受 Kubernetes 版本与驱动能力约束，不能一概声称回改请求即可自动重试或无损撤销。提前确认配额、后端限额、文件系统最大容量和维护窗口，空间不足时生成大备份包也会增加风险。扩容后持续检查写增长与 inode，避免只延长耗尽时间却不处理日志失控；若批准恢复模板涉及业务重启，重新评估 StatefulSet 仲裁和中断预算，不把存储审批自动扩展为重启全部成员的许可。",
    ),
    "raft-quorum": (
        "在固定成员清单上逐端点采样，记录不可达与错误类型，不使用自动扩展端点选项盲目访问清单之外地址。Raft 提交索引与应用索引差距可反映处理积压，但短暂差距不等于确定丢数据；采样时点、成员重启和 leader 变更必须同时对照。learner 的追赶与提升有独立限制，不因为它存有数据就将它计入现有法定多数；成员 ID 变化也不能在没有加入记录时视为普通进程重启。",
        "如果只剩一份可读数据，优先保全受支持快照和现场，不把可读 status 当作还有可用多数。恢复到新集群通常需要重新规划成员地址、集群身份与上层缓存失效，不能在线将旧目录互相覆盖。Kubernetes 使用者还需根据恢复工具版本考虑 revision 回退对 watch 缓存的影响，由平台负责人制定受支持恢复流程。未实际演练快照恢复时只记录备份存在和元数据，不承诺恢复后所有 API 对象与业务数据均完整。",
    ),
    "nospace-maintenance": (
        "维护规划要区分 quota-backend-bytes 与宿主可用空间，后端 quota 通常不是磁盘总容量，数据库碎片与历史 revision 也不等于可直接删除的业务对象。NOSPACE 下部分操作可能被保护拒绝，而某些事务路径的结果需依据实际响应和状态确认，不能机械认为报错前后完全没有任何写入。维护前留存告警成员、后端在用量、逻辑 revision 与磁盘余量，支持之后判断到底是释放历史还是仅更换了容量上限。",
        "逐成员整理时先确认其他投票成员可服务且不是同一块故障磁盘，避免维护时间重叠导致多数不可用。压缩选定 revision 会影响落后 watch，业务客户端可能需要重新列取对象，需预估 API 负载；整理后还要验证成员重新追上，不因文件变小就马上进行下一个。解除告警应建立在空间条件已满足而不是强行清状态，持续增长源仍未知时报告临时缓解，明确剩余容量和后续治理责任。",
    ),
    "api-readiness": (
        "健康端点返回需要带上入口和采样时间，负载均衡可能反复命中同一实例，除非已有明确逐副本访问授权，不能假称已覆盖所有后端。readyz 中单项失败与整体 HTTP 状态都应保留，禁用某项检查不等于修复。准入错误还需区分 webhook 网络不可达、证书验证、超时和明确拒绝，后者可能是正确策略；不能为让创建成功直接改 Ignore，或把 dry-run 成功当作真实持久化写入已经验证。",
        "API 聚合、存储和准入是不同依赖链，某一种资源读成功不覆盖自定义 API 或所有写动作。若错误集中在大对象、全量列表或高并发请求，先用已有请求指标或有限日志确认限流与负载，不主动发压测复现。恢复期间要控制自动重试引发的尖峰，保留原失败请求的最小脱敏形态；验收按读取、协调和获准写路径分别给结论，没有验证的链路维持待补证，不以健康页全绿替代端到端业务检查。",
    ),
    "coordination-stall": (
        "核对资源是否被 paused、suspend 或产品特定控制器接管，避免把有意停止协调误判为 controller-manager 故障。Deployment 只增加 generation 但 status 尚未更新可能是正常短暂延迟，需结合多个对象与持续窗口；Pod 明确用了自定义 schedulerName 时，默认调度器不处理是预期。对队列与选主异常，日志权限不足就保留原因未知，不能从主机进程名存在推断该进程正负责目标控制循环。",
        "控制面静态组件常由 kubelet监视本地 manifest，删除镜像 Pod 不会可靠停止宿主进程，编辑备份文件放在监视目录还可能被误当有效清单。审批恢复流程需明确发行版实际管理方式、文件校验与备用访问，不照搬常规 Deployment 命令。验收除选主稳定外还要确认目标资源实际创建、调度和就绪，已有旧实例正常只能说明旧服务尚存，不证明新声明的协调链已恢复。",
    ),
    "heartbeat-runtime": (
        "节点身份核对包括 bootID、machineID 的必要摘要和节点注册时间，节点同名重装后旧 Pod 与新主机可能并非同一现场。心跳条件与 Lease 是不同更新通道，API 端读到的最后更新时间不能直接当主机当前时间。日志显示证书轮换或 bootstrap 失败时，先核对公开证书身份与原注册流程，不读取私钥或复制其他节点 kubeconfig；认证恢复不应该靠重新命名节点逃避原有授权和卷身份。",
        "静态 Pod、普通工作负载和运行时 sandbox 的状态来源不同，kubelet 可暂时无法上报但已有容器仍在服务，因此重启前评估真正受影响范围。反之节点 Ready 不保证所有挂载和进程健康。若修复需要修改 cgroup、CRI endpoint 或节点保留资源，先列出与运行时版本的兼容，缺少备份和第二管理通路时停止。恢复报告按主机服务、节点心跳、容器启动与业务结果分层，避免从一个状态跳到整节点完全康复。",
    ),
    "eviction-thresholds": (
        "驱逐消息中的可用量和阈值是当时读数，回收完成后 df 或 free 变正常并不否认压力曾经触发。还需看是否存在失效统计、镜像垃圾回收失败、日志增长或容器已删除但文件仍被持有。对 inode、内存和 PID 分别采用对应信号，不能把不同资源换算成一个综合百分比。实际驱逐顺序还受请求、使用量、优先级和资源类型影响，QoS 不是唯一排序，也不能据此保证某个关键 Pod 永不被驱逐。",
        "临时调低保护阈值会把局部实例驱逐风险转成整个节点失效，恢复条件需要稳定余量而非仅清掉 Pressure。业务请求校准要有历史峰值和启动需求，降低请求虽然可能减少调度阻塞，却增加超请求竞争与驱逐风险。若清理候选是日志，先确认保留责任与打开文件状态；若是镜像层，交运行时受支持回收流程，不手删文件。验证覆盖原增长周期，并记录是否仍有本地卷或单副本业务未恢复。",
    ),
    "cri-plugin": (
        "CRI API 不可用时可先区分 socket 根本不可达、权限被拒、接口版本不匹配和插件初始化失败，错误文本应与 kubelet 实际 endpoint 一一对应。crictl 自己的默认 endpoint 猜测可能连到错误地址，只能使用既有确认配置，不自动遍历多个 socket。插件列表可显示某个插件报错，但修复还需它的依赖与启动日志；不能因为 ctr 能列容器就证明 CRI 插件与 kubelet 所需版本兼容。",
        "containerd 大版本的配置节和 CRI 拆分可能变化，审批差异必须按本机版本验证，不复制另一版本的 SystemdCgroup 路径。配置测试、重启和拉取镜像分别声明副作用，不能把它们混进状态查询；旧 shim 是否存活也需实际进程与 CRI 元数据，而非承诺重启永不影响已有容器。恢复后同时确认运行时可回应、网络已就绪和 kubelet 已重新建立状态，只有服务 Active 不足以结束事故。"
        "版本证据分别保留客户端版本、runtimeName、runtimeVersion 与 runtimeApiVersion，二进制版本号相近不等于接口协商成功。"
        "若状态查询超时，注明超时预算和所查 socket，不能填成服务已停止。权限拒绝只补核已知 socket 的属主和访问策略，"
        "不自动 chmod、加组或切到另一个 endpoint；恢复后仍用 kubelet 原来的接口复测。",
    ),
    "snapshot-content": (
        "内容摘要、平台 manifest、解包后的 snapshot 和活跃 task 是不同对象，某个镜像引用被删除不意味着所有层立刻可回收。先确认 containerd root、state 与 snapshotter 实际路径，不能假设全部位于一个默认目录。文件系统变只读、overlay 不兼容或元数据错误需要存储与内核证据，网络拉取成功不排除这些问题。针对 no space 的只读检查先确认字节与 inode，避免为诊断生成大型归档或下载新的工具包。",
        "清理必须保留活跃引用和离线恢复所需镜像，未知 blob 是否正在被共享层或租约持有时不作删除建议。通过 Kubernetes 删除不用的业务对象与底层 runtime 清理并非等价流程，前者也需要业务与数据所有者确认。若出现 snapshot not found 等一致性问题，保存受支持的诊断元数据，由运行时负责人给修复策略，不手工改数据库。验收包含下一次受控重建能力，而不只是当前仍在内存运行的旧容器没有立刻报错。",
    ),
    "expiry-inventory": (
        "公开证书清单应标明服务端、客户端、对等与信任根，不用一个到期最晚日期代表整组件安全。SAN 与使用扩展需符合实际连接地址和用途，issuer 名字相同也不能证明同一 CA，应比较公开指纹。若证书采用符号链接轮换，元数据只检查批准的公开目标，不遍历同目录私钥；实际运行进程可能仍缓存上一张证书，因此磁盘、管理器记录和握手三种身份都要关联，未知一层就保留待证。",
        "对没有独立 TLS 握手端点的客户端证书，加载验证应来自原身份向受信服务的授权请求或受控组件日志，而不是假装通过 openssl 访问客户端。证书续签不自动修复绑定角色，过期与权限拒绝分开处理。审批里核对备份材料的安全保管、是否可恢复旧信任关系以及旧证书已过期时回退限制；没有安全恢复路径就不要批量替换，尤其不能将新 CA 切换描述成普通叶子证书无感更新。",
    ),
    "csr-ca-transition": (
        "请求批准前以组织签发策略核验请求者、signer、用途和所属节点，用户名看起来像节点并不自动代表可信。公开 CSR 内容如确需解析也应由签发负责人处理后提供必要摘要，不能默认打印编码请求或嵌入证书包。Approved、Denied 与签发完成是不同状态，证书是否被 kubelet加载还需后续日志和实际请求；不要重复创建大量请求、清理原请求或授予全局自动签发权限来追求列表整齐。",
        "CA 过渡的双信任窗口应同时覆盖服务端链、客户端根和中间证书，期限与撤旧条件由安全负责人批准，避免只更新一侧。外部负载均衡、准入 webhook、聚合 API 与监控客户端也可能信任旧根，原生资源清单无法证明它们全部完成。验收按依赖清单逐项标明实际验证或负责人证明，旧根删除和权限收紧另走审批；不能因为大部分节点恢复就宣布整个信任域迁移已经结束。",
    ),
    "manifest-auth": (
        "多架构镜像的顶层索引与节点选中的平台 manifest 摘要不同是正常层次，核验时保留两者关系而不是直接判为篡改。unauthorized 还应区分认证服务挑战失败、仓库路径权限与凭据过期，具体主体与授权由仓库负责人核验，不通过导出拉取 Secret 自行比对。429 的来源可能是代理、上游或匿名限制，应记录响应来源和批准重试时间，不用大量并发拉取证明仓库不稳定。",
        "镜像存在与节点能拉取是两层：管理机 manifest 查询成功不能覆盖节点 DNS、代理、CA、平台和本地存储。批准修复后固定可追溯摘要，再在受控实例验证，镜像缓存命中时要明确未验证远端重拉能力。供应链验收包含构建来源与批准版本关联，摘要一致不自动表示没有漏洞或恶意行为；没有签名、扫描或构建证明工具接入时准确保留未覆盖项，不把运维拉取检查宣传为完整安全认证。",
    ),
    "proxy-cache-integrity": (
        "代理路径可能重写仓库名称或以不同信任根终止 TLS，记录的是实际配置与公开证书证据，不从镜像引用文字推断网络路径。缓存中旧标签与按摘要请求的内容应分别判断，修复优先固定批准摘要而非清除所有缓存。层校验失败时保存失败摘要和阶段，不下载业务镜像文件用于人工窥探；本地快照解包错误与远端 checksum 错误也不能合并，需分别交运行时或仓库负责人处理。",
        "验证代理切换时注意节点现有连接和 credential provider 缓存，运行时 reload 是否支持应以当前版本为准，不能承诺配置文件改后立即无中断生效。提议保留旧源作回退前要确认其证书与构建内容仍可信，不能因应急而重新允许已撤销源。回退测试与实际拉取都会改变缓存并产生流量，审批需列预算；仅公开 manifest 相同且未进行节点重建时，结果只能说明元数据对应，不保证所有节点供应链已可用。",
    ),
    "pending-hooks": (
        "Helm 的状态、资源健康和客户端进程是三套证据，客户端退出不代表 API 已应用内容被撤销。检查 hook 权重和执行阶段时要区分 pre/post-install、upgrade 与 rollback，某个 post hook 失败可能发生在主要资源已变更之后。清理策略可能删除成功或失败 Job，缺少现场时向流水线负责人取脱敏执行记录，不能用没有 hook Pod 推导从未执行，也不能重新触发只为补齐证据。",
        "pending 解锁需遵循实际 Helm 版本与发布管理流程，直接编辑 release 存储格式可能让后续历史与回退失效。审批前检查同一 release 是否还有 GitOps 或流水线控制者，不能一边人工恢复一边自动 upgrade。对数据库 hook 应由数据负责人确认部分提交、幂等与前后版本兼容，timeout 增大不解决重复执行风险。验收把 release 新状态、hook 业务结果和工作负载真实版本分别记录，任何未知保持未验证。"
        "核对实际发布是否启用 wait 与 wait-for-jobs，普通 Job 的等待和 hook Job 的完成门槛不能混用；"
        "仅凭 chart 中存在任务不能判断客户端一定等待了它。before-hook-creation 可能在下一次执行前删除同名旧 hook，"
        "因此恢复前先保存脱敏任务身份和结果，再由负责人批准新的发布尝试。",
    ),
    "render-drift": (
        "chart 的 appVersion 只是元数据，不保证模板真用该值作为镜像，必须核对实际渲染字段与运行 imageID。模板可根据集群能力、随机函数或 lookup 产生环境相关结果，离线渲染与服务器执行不一致时要保留原因，不宣称本地 diff 完全代表生产。values 的安全版本由发布方提供，不能为重建旧配置读取完整 Helm Secret；声明差异只提取获准字段，嵌入式认证、TLS 私钥和业务参数仍需排除。",
        "CRD 安装、schema 演进与自定义资源存量兼容需要单独门禁，不能假设 Helm 历史会处理所有 CRD 升降级。带 keep 策略的资源即使未被删除也可能成为孤儿，需要明确所有者而不是顺手清掉。若回退会遇到不可变字段、名称变化或数据迁移，先制定前向修复候选，不能强制替换扩大故障。实际验收比较批准字段而非整个 YAML 文本，服务端默认值与其他管理者的合法变化应保留边界。",
    ),
    "revision-sync": (
        "多源或分层 GitOps 中，顶层应用同步成功可能只证明子应用声明写入，不证明子应用实际交付；需沿真实所有者链定位目标 revision。分支名是可变引用，审批尽量绑定已核实提交，记录来源 artifact 摘要以便重现。仓库 clone 权限、渲染能力和目标集群写权限是三道边界，任何一项失败都要保留准确阶段，不能通过给控制器全局管理员权限把所有拒绝一次消掉。",
        "自动 prune 的范围需审阅真实待删除对象，特别是 PVC、命名空间和入口；确认追踪标识、所有者与保留策略，不能只看差异面板的一个删除数量。sync waves、依赖或健康检查可能有意等待前置资源，此时反复 force sync 会破坏顺序。恢复后确认实际 revision 与批准提交关联，再核对控制器声明健康及业务健康；若只能读 live 对象而不能访问 GitOps 状态，结论限定为运行版本，不冒充已验证仓库同步。"
        "读取条件时对照它对应的 observedGeneration 和最后转换时间，旧一代 Ready=True 不证明当前提交已被处理。"
        "分支名或标签若后来移动，应把获批提交与当前解析摘要分别记录；恢复只推进批准的精确版本，"
        "不能顺带接受排队的新提交。若条件仍旧而轮询失败，保留协调状态陈旧的证据，不报告新版本已上线。",
    ),
    "field-ownership": (
        "managedFields 可能被压缩或遗漏历史，它显示当前字段管理关系，不是完整审计日志。对 server-side apply 的冲突，先确认谁持续拥有该路径以及声明源是否应该删去该字段，不能通过 force 接管让另一控制器下个周期再抢回来。replicas 被 HPA 改动通常应与弹性策略协调，广泛忽略差异又可能掩盖不合法缩容，必须把字段级所有权与业务最小容量分别定义。",
        "紧急例外要有开始、结束和声明源追补的实际负责人，现场补丁可先止损但不应变成长期不可重建状态。恢复同步前审阅挂起期间积累的其他提交与 prune，避免撤销暂停时顺带应用未经本次批准的大批变更。验证以至少多个真实协调周期为证据，字段稳定但控制器已经失联不算收敛；同时确认源获取新鲜、审批提交已应用和业务状态正确，不能把遥测沉默当没有继续漂移。",
    ),
    "locks-connections": (
        "性能视图的可见范围受账户权限影响，返回零行可能只是看不到其他会话，不能写成数据库无锁。锁等待表在版本间有差异，MySQL 与 MariaDB 的字段也不应混用，先确认实际产品与版本再选查询。记录阻塞会话 ID、事务开始和锁对象的脱敏引用即可，锁数据字段可能包含业务键值，必须显式排除。元数据锁常与 DDL 和长事务相关，等待行锁的应用错误则需另一条证据链，两者不能用统一 KILL 解决。",
        "连接池修复需明确应用实例数量、每实例池上限与数据库容量，不能只把全局连接上限提高到当前峰值以上。持久空闲事务与普通 sleep 会话的风险不同，业务所有者应确认提交或回滚语义。若终止目标需要审批，执行前重新核对会话起始和事务 ID，防止连接 ID 重用；恢复后不仅检查等待消失，还要验证应用重试、错误补偿与事务结果，没有业务校验不承诺数据未受影响。",
    ),
    "replication-gtid": (
        "复制状态中的错误文本可能包含表名、键值或源连接信息，报告仅保留错误码、阶段和脱敏说明。并行复制下各 worker 的执行进度不完全同步，协调线程仍运行不能证明没有 worker 停止；只读性能元数据按允许通道获取。GTID 集合需要按同一源历史和多源通道解释，不能将一个副本更大的集合当它一定更新、更适合作主，额外事务也可能是错误写入或不同历史。",
        "源端日志是否仍覆盖副本所需位置是恢复关键，缺失时通常需要受支持的新基线而不是跳过错误；备份时间、日志链与恢复记录需共同核实。故障转移前确认旧主停写隔离、客户端路由、复制过滤与延迟副本意图，不能把某个只读标志当作防双写证明。验收区分线程恢复、追赶完成、持久化与业务一致性；无源端实际证据时保留复制新鲜度未知，不假称满足零数据损失目标。",
    ),
    "pg-blocking": (
        "事务年龄与语句年龄不同，查询开始较晚但事务早已持有快照或锁的会话可能是根源；读取必要时间戳即可，不需要 SQL 原文。pg_blocking_pids 可能返回其他数据库或后台进程，权限范围不足时由数据库管理员补元数据，不扩大默认查询。等待图可能随时改变，同一次采样关联的 PID 与 backend_start 应一起保存，后续处理前重新确认，避免把短暂正常竞争或已经退出的阻塞当持续故障。",
        "连接池事务模式、会话状态和应用重试影响取消效果，取消语句未必结束整个事务，idle in transaction 仍可能保留锁；不能承诺 pg_cancel_backend 即解除所有阻塞。对于预备事务或特殊后台锁，需专门责任方确认，不依靠杀客户端猜测。验收还应检查长事务对清理、复制槽和磁盘增长的影响，等待解除但保留快照未回收时只能报告局部缓解；无业务结果证据不能宣称事务已按预期完成。",
    ),
    "wal-slots": (
        "槽名不一定对应当前在线消费者，归属应从备份、CDC、订阅或应用登记核实；inactive 可能是计划停机而非废弃。逻辑槽的 confirmed_flush_lsn 与 restart_lsn 含义不同，前者推进也不保证后者立即释放，长事务和解码需求可能继续保留 WAL。版本中新提供的失效或保留状态字段只在实际存在时使用，不能跨版本拼接查询报错后再假定整个复制系统不支持诊断。",
        "物理复制、逻辑消费和归档是多条恢复链，共享 WAL 文件但各自进度不同，清掉某条链的保留约束可能让对应系统无法续接。空间应急优先保护可恢复性，临时扩容也需要费用与文件系统支持，不能手动删段。验收除了磁盘不再增长，还要由消费者确认处理连续、归档保留完整及备库追赶；如准备重建基线，单独审批负载和恢复点，不把删槽后空间下降解释成无损故障修复。",
    ),
    "memory-eviction": (
        "统计中的 used_memory 与宿主 RSS、内存限制各有口径，容器还可能受到 cgroup 限制，Redis 未到 maxmemory 也可能被系统 OOM。复制/AOF 缓冲、客户端输出缓冲和 fork 写时复制都可能改变峰值，需要已有版本字段和同时间主机证据，不用碎片率单数判断泄漏。淘汰策略若只针对带 TTL 键，可淘汰集合不足时仍可能报错，不能见策略不是 noeviction 就承诺所有写入都不会被拒绝。",
        "修复内存前确定这套实例承担缓存、会话、锁还是持久数据，重建成本和允许丢失完全不同。禁止通过业务键抽样猜测容量组成，也不以全量 SCAN 做默认诊断；确有键级分析应单独批准范围与限速。验收查看命中率分母、回源负载、过期与淘汰增量，不只看内存变小；若清理后下游流量暴增，即使 Redis 错误消失也不能算业务恢复，需保留数据与容量风险。",
    ),
    "replication-durability": (
        "Redis 复制 ID 标识历史，切换后多个 ID 的有效范围需要实际字段解释，不能将来自不同主历史的 offset 直接相减。全量同步期间旧副本是否继续提供陈旧读由实际配置决定，不能因为客户端仍能 PING 就认为读数据新鲜。持久化的最后成功时间、状态与磁盘 fsync 语义需分别核对，AOF 开启也不等于每个已确认写都立刻持久；业务 RPO 必须由真实配置和恢复点支持。",
        "Sentinel 多数授权故障转移与 Redis 数据复制是不同层，Sentinel 节点数不能当作数据副本数；Cluster 的槽覆盖和各主副关系又是另一套检查。不得把一个模式的命令套到另一个模式并据报错认定故障。审批前说明客户端发现与旧主隔离，切换后确认旧主不再接受业务写；验收要有允许范围内的一致性证据与持久化检查，若未执行恢复演练，准确保留恢复能力未验证。",
    ),
    "replica-election": (
        "成员 optime 与投票角色应在同一 term 和采样窗口解释，网络隔离时不同成员可能看到不同 primary，必须列来源而不是挑一个成功响应作为真相。arbiter 只参与投票，不承载数据，增加仲裁不能解决数据副本缺失。oplog 首尾时间可说明当前覆盖窗口，但写入速率变化会迅速改变窗口长度，不能把过去的小时数承诺为未来恢复保证；缺少权限时由数据库负责人提供摘要，不直接读取日志文档。",
        "initial sync、回滚和更改投票配置都有数据与负载风险，成员重新在线并不表示已赶上可服务状态。候选恢复成员需要检查复制新鲜度、是否曾出现独立写历史及客户端路由，旧主必须按受支持机制隔离。验收区分服务器选主、驱动拓扑更新和业务写关注达成；未对所有相关分片或路由器验证时不要将一个副本集健康外推为整个 MongoDB 系统可用，更不能承诺没有任何回滚。",
    ),
    "query-cache": (
        "currentOp 与 serverStatus 有访问和版本限制，返回缺字段或隐藏会话应记录未知，不通过提高权限或打开全量审计补齐。操作 ID 可能在恢复执行前失效，审批 killOp 前需要重新核对身份和当前阶段；长时间运行的索引构建、复制或备份任务也可能合法，不能按耗时排序自动清理。查询计划统计若由负责人提供，要记录使用的是哪个版本与样本形态，不从一条高扫描比推断所有业务都缺同一个索引。",
        "WiredTiger 缓存、进程堆、文件缓存和容器内存限制不同，增大缓存未必降低磁盘延迟，可能挤压其他内存造成整体抖动。读写票据和等待队列字段随版本演进，只有真实支持才用于判断并发瓶颈。验收在同类业务负载下比较等待和响应，并确认复制延迟、选主与磁盘压力没有恶化；只看到一次查询变快或 cache 比率降低不算完整优化，未经实际负载验证的结论应标为建议。",
    ),
    "consumer-lag": (
        "消费组位点可能不存在、被 retention 删除或因事务隔离显得与日志末端不同，空值不能直接填零。将当前提交、日志末端和组成员状态分开记录，明确客户端是处理前提交、处理后提交还是事务提交，才可解释 lag 与业务结果关系。成员反复 rebalance 时，分区所有权变化会使采样瞬时无消费者；保留间隔证据而非从一次空 consumer-id 宣布整个组停止，静态成员与新协议行为也应按版本核对。",
        "扩容有效上限受分区数量与键分布影响，热点分区无法靠无限增加消费者分摊；增加分区本身又可能改变按键路由和顺序，是需审批的拓扑变更。位点恢复前保存可审阅的原位点摘要和目标，确认旧消费者是否停止以及外部事务是否幂等。验收既比较提交推进速度，也核对业务完成与补偿，不能因为改 group 或跳到 latest 后 lag 消失就声称所有历史消息已正确处理。",
    ),
    "isr-controller": (
        "ISR 是当前与 leader 保持同步的副本集合，不与配置 replicas 或在线 broker 数等价；一个 broker 有进程也可能因磁盘或网络不能维持该分区复制。topic 级覆盖的 min ISR 应优先于 broker 默认解释，producer acks 与事务配置需来自实际客户端。控制器多数决定元数据可用，不能用数据分区副本健康替代，也不能从某个 controller 日志正常推导所有分区具备有效 leader。",
        "副本恢复时重分配和日志追赶会增加网络、磁盘及 page cache 压力，需审批节流和顺序，避免把原本健康分区拖入 ISR 收缩。候选 leader 的数据完整性与日志边界不清时停止强制操作，安全优先于颜色恢复。验收观察稳定 ISR 与 leader、原生产错误和消费者进度；未经业务消息一致性确认不承诺零丢失，尤其不能将降低持久性门槛后写入成功描述为数据可靠性已经恢复。",
    ),
    "ready-unacked": (
        "队列统计还可能受 TTL、长度上限、死信策略和管理采样周期影响，ready 下降并不必然对应消费成功。消息被重新投递时 redelivery 计数与业务重复结果需要分开核对，不读取消息体证明内容。一个消费者也可能有多个通道，prefetch 的实际作用域要按客户端与 broker 版本确定，不能把全连接上限、通道上限和每消费者并发简单混为一个数字。未经实际应用确认不自动改为自动确认来降低 unacked。",
        "发生消费者断开时，未确认消息可能重新入队并被另一实例处理，业务外部副作用是否已提交必须由所有者判断。暂停或重启消费者的审批应包含幂等、顺序和下游负载，避免原本缓慢消费变成集中重投。验收除 ready/unacked 还看消费者稳定、死信与过期变化和真实完成结果；只有 broker 层统计时报告投递与确认恢复，不能声称所有业务消息无损、恰好处理一次或历史积压已完整补齐。",
    ),
    "alarms-quorum": (
        "资源 alarm 与集群分区需同时检查，某个节点恢复可达并不表示其持久日志已经可参与目标 quorum。quorum 队列的成员与普通集群节点清单不同，队列可能没有分布到所有在线节点，应按目标成员数计算多数。某些管理命令会等待远端节点，查询也要有超时与范围限制，不因一次卡住就多次并发执行。磁盘阈值还受数据目录挂载点与临时增长影响，根盘余量不能替代实际队列盘。",
        "磁盘告警先找增长源与保留策略，不能通过降低阈值或清队列让发布成功。节点维护前确认每个关键队列仍有多数，多个审批若同时作用于相同成员集合，仍可能合计丢多数，需平台统一安排顺序。恢复验证要区分集群节点、目标队列领导与持久消息处理，禁止用 force_boot 或遗忘节点来试探；未取得有效副本与恢复点时保护现场并升级数据负责人，不承诺现有日志可无损重建。",
    ),
    "upstream-errors": (
        "配置中的 proxy_pass 是否包含 URI 会影响 location 前缀替换，正则 location、变量上游和 rewrite 又有不同限制，必须按实际片段解释，不用统一加斜杠修所有 404。上游 HTTPS 还需核对 proxy_ssl_name/server_name、信任链和验证配置，边缘证书正常不能覆盖这一层。若日志显示多 upstream_status，应将重试次数和最终返回对应起来，客户端看到一个响应不代表只向后端发了一次请求。",
        "请求时间分析需注意客户端慢上传或慢下载可能占据较大 request_time，upstream_response_time 才更贴近上游阶段但仍非应用纯 CPU 时间。超时修复后检查连接和内存是否持续积压，不能把错误由 504 变成更长等待当作改善。验收使用批准的幂等路径并保留 host/SNI、方法和版本，状态成功但后端路由错误仍不算恢复；日志缺少关联字段时明确无法精准归因，不补写虚构毫秒值。",
    ),
    "workers-reload": (
        "worker 句柄预算不仅有客户端 socket，还包括上游、日志、监听与缓存临时文件，估算必须说明假设，不能宣称每个连接固定只占一个 FD。进程软上限可能低于硬上限，systemd 新配置也通常只在进程重新启动后生效，reload 是否会创建继承新限额的 worker 取决于实际启动方式。核对 master 与 worker 分别的 limits，避免只看主进程就认定所有工作进程已有足够上限。",
        "旧 worker 在长连接排空时仍占资源，多次 reload 会叠加多代进程，应记录代际与现存会话而不是逐个 kill。配置校验失败时旧进程继续服务是正常保护，不能因端口仍通便认为变更生效。审批恢复路径要包括单实例入口、长连接可接受中断与旧配置可用性；验收既看新 worker 实际加载，也检查旧进程最终退出和 upstream 连接没有因新上限放大而过载，未测协议单独列待验证。"
        "open_file_cache、代理缓存与日志文件也会占句柄，不能仅按活动连接数推导泄漏。若只在轮转后出现空间或句柄异常，"
        "需由授权元数据确认旧文件是否仍被 worker 持有，不能为观察效果直接发送 reopen 信号。获批恢复后分别检查新请求和"
        "既有长连接，避免把所有旧连接被迫断开后句柄下降说成平滑恢复。",
    ),
    "backend-queues": (
        "健康检查与真实业务可以走不同端口、不同 Host 或 SNI，因此检查 UP 仅对该检查请求成立。rise/fall 连续次数和检查间隔共同影响摘挂时间，不能直接拿 lastchg 当最初故障时间。队列等待需与 server maxconn、连接复用和后端处理耗时对照，frontend 达到上限与 backend 排队是不同瓶颈；共享池或多进程统计可能改变计数口径，应依据实际版本和 stats 行类型说明。",
        "TCP 模式不能照搬 HTTP 状态计时解释，日志终止标志的每个位置也要按实际格式核对，缺格式定义时保留未知。临时 runtime 权重或 maintenance 状态如果未持久化，reload 可能恢复旧值，审批需明确最终声明源。验收不只看 qcur 回零：停止流量也会让队列消失，应确认原业务请求持续到达、后端正确处理、TLS 保持校验与错误增量下降；没有端到端请求则仅报告代理统计层结果。"
        "queue timeout 与 connect timeout 分别限制排队和建连阶段，增大后者不会增加后端并发名额；"
        "备份 server 是否接流还受角色和实际配置影响，不能见其健康就加入有效容量。恢复候选按单个 backend 的瓶颈提交，"
        "验收比较相近到达速率下的队列、连接和拒绝增量，不用流量骤降后的空队列证明容量已经足够。",
    ),
    "master-worker": (
        "master-worker 与旧多进程模式的 reload 控制方式不同，先从版本和真实服务管理方式判断，不把网上启动参数直接写入生产 unit。stats socket 若由旧 worker 接受，读到的信息可能属于旧代进程，应关联 PID、uptime 和配置版本来源。监听 FD 传递与重用行为受构建和系统支持影响，不能无证据承诺 reload 没有任何连接间隙，尤其在唯一入口或大量长连接场景更需受控验证。",
        "运行时维护状态、权重与 server-state-file 的关系需核对启用方式和加载时序，状态文件存在也不证明新 worker 已应用。配置校验成功只能证明该解析器接受文件，后端解析、证书与业务路径仍要实际检查。审批要给出旧进程长时间无法排空时的停止条件和业务选择，而不是默认强制关会话。恢复后保留新旧代际和状态继承证据，任何未验证流量类型与备用入口能力仍明确未知。",
    ),
    "unit-failure": (
        "退出状态要区分进程主动 exit、被信号终止和 systemd 在执行前失败，数字相同在不同 ExecMainCode 下含义不同。Type=forking 还要确认 PID 跟踪，Type=notify 依赖实际 READY 通知，oneshot 可能本来没有长期进程；不能统一要求 MainPID 非零。查看已知路径元数据时不自动改权限或执行文件测试，解释器缺失、只读挂载与安全策略拒绝应分别保留证据，不通过禁用沙箱让错误暂时消失。",
        "Restart 策略、启动限制窗口和应用退避可能叠加，StartLimitHit 只是最后保护状态，最早一轮失败日志更有根因价值。清除失败状态会改变后续可启动性，也会影响现场判断，因此先记录再审批。验收覆盖原先重启间隔和启动最长时间，检查依赖及业务功能，而不是在服务短暂 active 时立即结束；如果应用主动退出是预期批处理行为，应按任务结果判断，不强行改成持续重启的守护服务。"
        "ExecCondition 条件跳过与 ExecStartPre 失败应分开核对，条件不满足可能是部署者有意禁止本机启动，不能直接删除条件。"
        "权限或命名空间沙箱错误需保留原始退出阶段，审批修正应指向最小路径或身份，不取消整套保护。"
        "验收同时确认 Result 与新一轮 invocation 的日志，旧启动残留的成功信息不能覆盖本次失败。",
    ),
    "dependencies-timers": (
        "依赖传播并不等于就绪传播，Requires 配合 After、BindsTo、PartOf 等关系的停止影响各不相同，读取实际字段后再规划操作范围，不用一个依赖图推断所有联动。socket 激活可能使服务本身不常驻仍正常工作，手动停服务后 socket 也可能再次拉起，不能因此误判重启失控。timer 触发的 service 若已经 active，是否会再次执行应依据该单元生命周期确认，不能将每个计划时刻等同一次独立任务。",
        "OnCalendar 的时区、随机延迟和精度窗口影响实际触发，Persistent 补偿通常不是把每个错过时刻逐个执行。业务日期参数还可能与系统当天日期不同，任何补跑需确认幂等与批次范围。修改 timer 前保存下次触发与原日历，并评估 daemon-reload、start 或 enable --now 是否立刻激活任务；验收至少等待一个批准周期并对照 service 结果，解析器显示正确只算静态计划验证，不假称业务已经完成。"
        "timer 的 Unit 可指向非同名 service，检查实际触发目标与 TriggeredBy 后再关联日志；别名与实例化单元还需保留完整实例名。"
        "AccuracySec 允许的合并窗口不是严格执行误差保证，业务要求准点时需与随机延迟一并评估。"
        "恢复后按实际目标的完成批次验收，不能拿另一个同名前缀任务的成功记录代替。",
    ),
    "fd-limits": (
        "目标 PID 的 fd 目录计数与 lsof 的行数口径不同，后者可能含映射文件和重复线程视图，不能直接比较得出泄漏倍数。system file-nr 统计的是系统文件表对象，也不是所有进程 FD 数简单相加。采集时确认 PID starttime 或 service MainPID 没变化，进程退出导致目录消失应标记本次样本失效，不把空目录计为恢复；权限拒绝也不能当作没有打开文件，更不能提升权限遍历其他服务。",
        "句柄类型判断只用批准聚合，socket 增长要与连接生命周期对照，文件增长要查应用关闭逻辑，删文件但仍持有句柄的空间问题另按存储流程处理。提限审批应估算每连接内存和上游容量，不能无限提高作为长期修复。恢复后保留相同负载下 FD 高水位与回收速率，若错误消失只是上限变高而数量仍线性增长，明确临时缓解并安排代码修复，不能将其描述为泄漏已根治。",
    ),
    "pids-cgroup": (
        "同一用户的多个服务可能共享 RLIMIT_NPROC 计数约束，而 TasksMax 限制的是特定单元 cgroup；容器中的可见 PID 数也可能远小于宿主线程总数。先确定实际约束边界，再比较当前量和上限，不用 ps 的单进程列表证明线程数低。pids.events 是历史计数，需要增量与失败时间吻合才支持本次触顶；进程已退出后 current 降低不否认之前触限，内存分配失败也仍需排除。",
        "线程风暴和僵尸积压有不同恢复方法，僵尸的资源回收依赖父进程 wait，单独发送信号不能解决。应用线程池、连接池和 fork 子任务各有业务语义，终止父进程可能同时中断全部子工作。审批前明确服务身份与重启/提限作用范围，保留原 cgroup 配置而不是手写受编排器管理的运行态文件；验收观察正常峰值、线程回收、内存和父子关系，缺少这些证据时只报告某一限制暂时解除。"
        "cgroup 层级的父级也可能限制任务创建，叶子 pids.max 尚有余量不排除祖先已触顶；只沿确认的服务路径核对必要父级，"
        "不递归遍历其他租户。若父层属于整个容器或共享 slice，提限必须评估其全部成员影响。"
        "恢复验证保留叶子与实际阻断层的计数和事件增量，不用单个线程短暂退出后的低读数宣告问题消失。",
    ),
    "source-offset": (
        "选中源的符号、reach 与 tracking 指标要按实际 chrony 输出解释，多个源互相分歧时不是投票数多就天然可信，还需组织批准来源与故障域。某个偏移很小但误差界很大不能称高精度，同步刚恢复也需要多个样本稳定。timesyncd 或其他守护进程未启用时，timedatectl 的字段可能不足以解释真实同步机制，先确认实际提供者，不启动第二套服务争用系统时钟，也不凭服务 active 断言已锁定来源。",
        "时钟校正采用渐调还是跳调要结合当前偏差、应用容忍和恢复窗口决定，跳回可能重复定时任务，跳前可能立即使令牌和证书过期。源配置修复不代表已有偏差瞬时消失，验收持续读取偏移和测量新鲜度，不能在第一次 synchronized 标记出现就结束。若只能取得一台主机证据，限定为本机，不将其偏移应用到所有数据库、控制面与日志平台，更不能手工改写历史时间来制造一致事故顺序。",
    ),
    "clock-jumps": (
        "同一日志平台可能同时保存事件时间、接收时间和索引时间，队列积压会让接收晚于事件但并非主机偏移。跨主机比较时注明每个测量来源的可信误差，不用一个当前 NTP 偏移直接修正数小时前未知的漂移。容器时区文件、应用运行时设置和数据库会话时区会改变显示，通常不改变内核墙钟，需各自证据。日志只保留到秒时，同秒事件没有可靠先后，应以请求关联和单调顺序补充而非虚构毫秒。",
        "计算时长要先核对是否跨重启、跨夏令时或跨时钟 step，真实等待可从同一启动周期的单调时间推断，但不能跨不同 boot 直接做减法。修正报告时保留原时间、换算规则和不确定区间，新增证据可以修订结论而不覆盖原记录。验收既检查当前同步也核对新一轮业务日志是否按预期产生，若历史顺序仍无法重建就明确未知，不为复盘完整性编造一个精确根因时刻或恢复耗时。",
    ),
    "route-policy": (
        "ip route get 的选路结果受源地址、mark、接口和协议族影响，应用实际 bind 了另一个源时，普通查询可能完全不代表该流。策略表的优先级数值越小通常越先匹配，但规则仍可能继续查后表或命中不可达动作，应按实际输出解释。IPv6 还要考虑地址 scope、临时地址和邻居状态，不能把 IPv4 默认路由复制过去。网络 namespace 不同需原授权进入或由负责人补证，不从宿主选路推导容器路径必然一致。",
        "回程路由未知时只能确认本机出方向，不把 connection timeout 定义为本机防火墙丢弃。配置管理器可能在续租、链路变化或重启时重写临时命令，审批应修正真实持久源并说明与 DHCP/云网络关系。变更前保存当前管理流所用路由和源地址摘要，恢复路径必须能在失联情况下执行，不能依赖已经断开的 SSH 再手动回退。验收新旧关键流量及管理连接，不以一次 route 查询或链路 UP 作全网恢复结论。",
    ),
    "firewall-counters": (
        "规则计数只能证明与规则匹配的包经过该位置，不能单独证明最终放行或端到端送达；NAT 改写后五元组和计数位置不同，要按 hook 顺序追踪。nft 的 family inet、ip、ip6 及 bridge 视图可能并存，容器或虚拟交换路径还可能经过其他机制，不能因主机某链没有计数就排除安全控制。拒绝报文与应用端口未监听都可能表现为快速失败，需要原始错误和有限授权监听元数据对照。",
        "有状态连接已经建立后可能继续走允许规则，因此修复验收要含受控新连接；清 conntrack 为了强迫重测会影响真实会话，必须单独审批且不是默认步骤。临时例外应精确到源、目的、协议端口和期限，恢复原规则时仍核对是否有并发管理者变更。若实际规则来自 Kubernetes、firewalld 或配置管理，直接追加命令可能被覆盖或破坏顺序，应从真实来源修复；只读统计不足时保留证据缺口，不用全局放通代替诊断。",
    ),
    "head-series": (
        "指标抓取也会受采样限制和返回上限影响，状态接口给出的 top 统计不是完整标签笛卡尔积，不能将列出的几个高值直接加成全库总量。prometheus_tsdb_head_series 是当前活跃 head，历史磁盘块与远端存储另有保留周期，重启或块切换会改变观测，比较时要记录进程启动和样本新鲜度。若序列创建激增来自不断变化的目标标签，单纯缩短查询时间不能减少入库开销，应交采集与业务指标所有者治理。",
        "高基数分析避免再制造无界 PromQL，topk 只限制输出不一定限制后端先计算的序列规模，应优先使用已有受限统计和明确 job/metric 选择器。任何标签治理都要检查告警和联邦/remote_write 依赖，不能删掉租户或安全隔离维度换取内存下降。验收在相同目标范围与真实负载下比较新增序列、样本和内存，历史清理需要实际周期；若只扩资源暂缓 OOM，准确标明未消除增长来源，不虚构节省比例。",
    ),
    "relabel-limits": (
        "target relabel 可以决定抓哪些目标，metric relabel 发生在抓取后；两者不能互换，丢弃目标会同时丢其全部指标。sample_limit 与标签长度限制超出时的行为应按当前版本核对并检查具体 scrape 错误，不能假设只截断多余样本。labeldrop 后若多条原序列变成相同标签集，既可能重复冲突也可能丢失聚合含义，正确做法通常是源端有语义地聚合或按 metric drop，而不是随意删除高基数键。",
        "录制规则仅生成派生序列，若原始高基数仍在入库，总内存与存储未必下降；remote_write relabel 只影响远端发送，不自动减少本地 head。审批对每条候选规则列出留下和丢掉的有限正反例、关键告警及回退缺口，已丢历史无法靠恢复配置补回。验收关注 up、抓取失败、duplicate/out-of-order 样本和业务可观测性，配置语法通过而指标沉默不算治理成功，更不能把无数据解释为业务零错误。",
    ),
    "no-data-variables": (
        "数据源 UID 与显示名称不同，重建同名数据源可能得到新 UID，面板仍指向旧对象；组织和 tenant 也是权限与数据边界，不通过换管理员账户证明普通用户链路正常。变量链存在依赖时，父变量刷新失败会让后续查询选择空集合，应该从展开后的实际请求定位。正则与 SQL/LogQL 的转义方式不同，默认 All 的表达也因后端而异，不能把一个数据源成功的写法推广到全部面板或直接使用 raw 绕过安全转义。",
        "No data 映射成零容易让告警和 SLO 看起来恢复，必须保留真实无样本状态；时间覆盖也要检查 dashboard 相对时间、panel override 与数据源延迟。权限变更属于独立安全审批，不因调试方便读取 secureJsonData、会话 Cookie 或 API token。验收用原用户身份与原变量选择复测，并确认最新点确实来自预期 tenant；只有负责人提供一次静态结果时，标注该来源和时间，不假称连续实时监测已经验证。",
    ),
    "aggregation-performance": (
        "图形分辨率、后端聚合窗口和采样间隔是不同参数，扩大 step 可能只是减少展示点，并没有减少某些后端先扫描的范围。PromQL 的 rate 需要足够样本并处理 counter reset，先汇总再 rate 可能掩盖各实例重置；经典直方图聚合还要保留 le，分位数平均通常没有全局分位含义。单位错误也可能来自 query 把每秒速率再乘或除一次，需从原 metric 定义追溯，而不是只修改面板显示单位。",
        "transformations 的 join、reduce 和缺值替换可能改变统计分母，空序列、零流量与查询错误不能统一填零。优化时先修选择器和时间窗，再评估可重用聚合，不默认增加并发或高 maxDataPoints；表达式输出小不代表后端处理轻。验收同一绝对时间、相同权限和真实负载，比较数值与扫描/耗时证据，确保不是因为过滤掉异常实例而变快。没有数据源执行证据只交离线审阅结论，不宣称看板性能已上线改善。",
    ),
    "ingestion-rejects": (
        "采集器发送成功、distributor 接收和日志最终可查是不同阶段，部分成功或重试可能使同一批数据既有重复又有缺口。拒绝 reason 的命名与是否可重试取决于版本和客户端行为，应保存响应码与错误摘要而非笼统写限流。流标签改变会生成新 stream，历史仍按旧标签查询，不能因为新标签下没有旧日志就判断存储丢失。日志时间与摄取时间差需先排除源解析错误和时钟偏移，再讨论放宽时间限制。",
        "积压回放要考虑源文件保留、positions、客户端队列和租户限制，文件已轮转删除后不一定能补；禁止通过重置全部 offset 制造貌似完整的重放。审批中明确回放速度、范围、重复处理和停止阈值，不将单一 tenant 的限额提高影响扩展到所有用户。验收除新日志还核对已知缺段边界与重复量，缺乏原始证据时保留无法证明完整；服务指标恢复并不能自动证明历史日志从未丢弃或审计链完整。",
    ),
    "logql-streams": (
        "selector 选中的流数、扫描字节与输出行数是三个口径，少量结果也可能扫描巨大数据，limit 不能保证查询廉价。正则和 JSON 解析次序可影响成本，但语义依赖原日志格式，不能为了加速把必要条件移动到不等价阶段。错误标签 __error__ 过滤要结合实际解析与指标查询语法，不把解析失败行一律忽略后宣称业务没有错误。structured metadata 支持还与索引 schema、版本和采集器配置相关，未确认不能建议直接迁移。",
        "标签治理从源端选择有限维度，用户 ID 和完整 URL 等高基数值通常保留在日志内容或受支持结构元数据中，但隐私和查询权限仍需审批。改标签后告警、仪表盘与历史查询需要过渡，不可能靠一个 labeldrop 自动把旧索引变成新结构。验收同时观察流数、摄取拒绝、查询扫描和关键日志可检索性，不能只用一个短窗查询更快作为长期改善证据；未获取实际统计则保留性能推断未验证，不编造扫描量下降百分比。",
    ),
    "unassigned-deciders": (
        "allocation explain 应固定一个真实未分配分片，默认自动选择某个分片可能与故障目标无关；返回的最早 unassigned 原因和当前 decider 决策不是同一时刻，应分别记录。节点过滤、awareness、tier 资格和磁盘条件可同时阻断，修一项后仍需复查其余条件。no_valid_shard_copy 不能靠新建空主分片保数据，只有明确接受丢失才可能另走灾难恢复流程，本手册不授权执行 accept_data_loss 或强制分配命令。",
        "副本数量、故障域和节点角色需要与业务恢复目标对照，单节点把 replica 降为零能消除 yellow 但失去冗余，必须准确说明而非称全面修复。已有快照也需核对目标索引覆盖、版本和恢复记录，不假定最新快照包含所有写入。验收按主/副分片身份、节点与真实恢复进度核对，cluster green 只描述分配状态；索引文档完整性和业务搜索/写入结果必须由另有授权的验证支持，未读取业务内容时保持这一边界。",
    ),
    "watermark-shard-size": (
        "水位百分比通常描述已用比例，而字节形式往往描述剩余空间要求，具体组合和 headroom 支持按实际 OpenSearch 版本核实，不混用 Elasticsearch 文档直接改值。迁移需要目的节点也符合水位和过滤条件，全体节点都高时重定位并不能创造容量。目标盘存在 translog、合并临时文件和其他应用占用，disk.indices 不是完整磁盘账；只删索引前必须确认保留策略和快照恢复能力，不能以最大索引作为天然清理对象。",
        "清除 read_only_allow_delete 前检查磁盘已安全低于保护条件并观察增长，部分版本会自动解除，重复写设置可能掩盖持续耗尽。force merge 和 reindex 需要额外空间，满盘应急时可能加剧故障，shrink/split 也有前提与业务中断成本。验收分配、磁盘、索引 block 和原业务路径分别有证据，缺少真实写验证就不承诺写恢复；仅降低副本或保留期释放空间时准确交付可靠性与历史覆盖变化，不能描述为无代价优化。",
    ),
}


def _with_field_notes(preset: dict) -> dict:
    documents = []
    for document in preset["documents"]:
        notes = _FIELD_NOTES[document["key"]]
        content = document["content"].replace(
            "\n\n## 判断\n",
            f"\n5. {notes[0]}\n6. {notes[1]}\n\n## 判断\n",
            1,
        )
        documents.append({**document, "content": content})
    return {**preset, "documents": tuple(documents)}


EXTRA_PRESETS = tuple(
    _with_field_notes(preset)
    for preset in (
        *_WORKLOAD_PRESETS,
        *_NODE_PLATFORM_PRESETS,
        *_DELIVERY_DATA_PRESETS,
        *_HOST_OBSERVABILITY_PRESETS,
    )
)
