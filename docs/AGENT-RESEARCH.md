# 可靠性来源核对

本轮核对的是官方源码，不把重试理解为反复执行已发出的写操作。

## Cline

核对提交 `40c5d99031fe1128189c5b52e40638d2b7787754` 的 SDK/ClineCore 路径。

- 分类 transient API 错误，避免 SDK 与上层重试预算相乘：[error-classification.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/llms/src/providers/error-classification.ts)、[agent-runtime.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/agents/src/agent-runtime.ts)。
- 空响应独立恢复；已提交正文、工具活动与流前错误分别处理：[retry-empty-response.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/llms/src/providers/middleware/retry-empty-response.ts)。
- 完整 JSON 修复、schema 校验、工具错误回馈模型：[ai-sdk.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/llms/src/providers/ai-sdk.ts)、[definitions.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/core/src/extensions/tools/definitions.ts)。
- 重复调用与连续失败识别：[loop-detection.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/core/src/runtime/safety/loop-detection.ts)。
- 请求投影保持工具调用与结果配对、限制过大结果：[message-builder.ts](https://raw.githubusercontent.com/cline/cline/40c5d99031fe1128189c5b52e40638d2b7787754/sdk/packages/core/src/session/services/message-builder.ts)。

## Roo Code

核对官方仓库 `main` 对应 `b867ec9145750d0ae1ff7f02d35406e9bf2a0b16`；仓库已于 2026-05-15 归档，不能把它描述为一直维护的最新版本。

- 按当前模式筛选可用工具：[build-tools.ts](https://raw.githubusercontent.com/RooCodeInc/Roo-Code/main/src/core/task/build-tools.ts)。
- 解析完整原生工具参数与缺失字段：[NativeToolCallParser.ts](https://raw.githubusercontent.com/RooCodeInc/Roo-Code/main/src/core/assistant-message/NativeToolCallParser.ts)。
- 将验证和执行错误作为结果交回模型：[presentAssistantMessage.ts](https://raw.githubusercontent.com/RooCodeInc/Roo-Code/main/src/core/assistant-message/presentAssistantMessage.ts)。
- 退避、空响应恢复和上下文：[Task.ts](https://raw.githubusercontent.com/RooCodeInc/Roo-Code/main/src/core/task/Task.ts)。EarthAI 只引入有界、分类的重试，不照搬无限循环。
- 无进展重复调用检测：[ToolRepetitionDetector.ts](https://raw.githubusercontent.com/RooCodeInc/Roo-Code/main/src/core/tools/ToolRepetitionDetector.ts)。

## 本项目取舍

原生工具仍优先。模型只说文字、网关无法处理原生 tool-result，或者响应持续不兼容时，采用显式 JSON 控制协议：只接受完整顶层对象，仍用相同参数校验、所有者限制与审批边界。普通自然语言、Markdown 命令块绝不隐式执行。工具结果投影到消息里标为不可信数据；这些数据不能覆盖控制协议与安全要求。

模型 HTTP 重试不重跑工具。相同失败参数有次数限制；同一次任务中成功写操作可复用结果，状态未知的操作不会自动重发。没有宣称分布式 exactly-once。
