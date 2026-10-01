# 通用 Agent 内核与扩展接入

运行入口为 `AgentPipeline`。它依次处理上下文、意图、路由、Skill 加载、工具执行和输出。
业务 Policy 和 Renderer 由宿主注册，内核不导入 Educoder 业务模块。

## 内核组成

| 模块 | 职责 |
| --- | --- |
| `models.AgentRunContext` | 可序列化的请求、历史、Skill、计划、工具结果和审批状态 |
| `catalog.ContextResolver` | 按 kind 注册 `@` 引用解析器 |
| `catalog.CapabilityRegistry` | 注册 Skill、内部工具和 MCP 适配器 |
| `runtime_extensions.PolicyRegistry` | 顺序匹配宿主的严格业务规则 |
| `runtime_extensions.PermissionPolicy` | 调用前授权检查与审批判定 |
| `runtime_extensions.OutputRegistry` | contract 到 Renderer 的映射 |
| `runtime_store.RuntimeStore` | 会话、消息、快照和事件存储接口 |
| `pipeline.AgentPipeline` | 执行循环、校验、超时、取消、审批恢复和终态 |

## 宿主组装

```python
from pathlib import Path
from app.catalog import ContextResolver, build_default_registry
from app.pipeline import AgentPipeline
from app.runtime_extensions import OutputRegistry, PermissionPolicy, PolicyRegistry
from app.runtime_store import SQLiteRuntimeStore

registry, mentions = build_default_registry()
resolver = ContextResolver(mentions)
policies = PolicyRegistry()
outputs = OutputRegistry()
permissions = PermissionPolicy()

agent = AgentPipeline(
    registry=registry,
    resolver=resolver,
    provider=qwen_provider,  # 宿主提供模型适配器
    policies=policies,
    outputs=outputs,
    permissions=permissions,
    store=SQLiteRuntimeStore(Path("data/runtime.db")),
    max_steps=12,
    operation_timeout=120,
)
```

## 新需求放在哪里

- 新业务对象：`resolver.register("order", async_resolver)`，返回 `ResolvedContextItem`。
- 新动作：`registry.register(descriptor, async_handler)`。handler 接收参数、本轮上下文、
  已加载 Skill ID 和 `previous_results`，返回字典。
- 新业务规则：`policies.register(policy)`。`resolve(state, candidates)` 返回
  `PolicyResolution`；没有命中时返回 `matched=False`，由通用模型路由。
- 新结果形状：`outputs.register("report.v1", renderer)`。renderer 是异步生成器，
  `render(state)` 返回 `(event_type, payload)`；宿主在其中做业务 Schema 校验。
  最后必须返回 `message.completed`。文本、卡片、HTML 和文件通过各自协议扩展；
  前端也需要为新增输出类型注册展示组件。
- 项目权限：`permissions.register(check)`。check 接收本轮状态、能力和参数，返回
  `PermissionDecision`；宿主可以核对用户身份、对象归属和允许范围。
  身份由宿主认证后通过 `agent.run(request, identity=trusted_identity)` 传入，
  不接受客户端直接声明的身份权限。identity 不会进入模型上下文。
- 新模型：实现 `ModelProvider`。`next_action` 返回 `call`、`ask` 或 `finish`。
  未实现动态规划的 Provider 默认在当前计划执行后结束。
- 更换存储：实现 `RuntimeStore`。默认内存存储适用于嵌入，示例服务使用 SQLite。

## Skill 与工具结果

选中的 Skill 在工具执行前加载，指令会进入参数生成、继续执行决策和回答合成上下文。
`skill.json` 支持 `required_capabilities: ["capability-id"]`，宿主按真实 Capability ID
绑定依赖；依赖缺失会停止运行。`skill-read-reference` 只允许读取本轮已加载 Skill
目录里的有限大小文本文件。导入包中的脚本不会自动执行。

每一步工具结果写入 `state.results`，后续参数生成可以读取实际返回的 ID、页码等。
千问在初始计划完成后可追加工具步骤、追问或结束；总步骤受 `AGENT_MAX_STEPS` 限制。
失败工具不会由运行时自动重放。

## 工具调用与审批

所有调用先通过 JSON Schema 参数校验和权限检查。写入/发布/删除权限以及
`requires_approval=True` 的能力会暂停，保存实际参数、能力指纹和当前位置。

批准或拒绝时恢复同一次运行，已经完成的步骤不再执行。每个新工具调用分别判定审批，
一次批准不代表后续操作均获授权。待审批操作超过 24 小时或能力配置发生变化，需要
取消并重新发起任务。MCP 默认每次确认；配置 `approval_policy="writes"` 后，只有
明确声明只读的工具可以免确认。未知工具保持确认。宿主仍可覆盖权限判断。

MCP `isError=true`、handler `success=false`、异常和超时都会形成失败结果。
后续决策和 Renderer 可以据此停止、追问或选择其他可用能力。

## 会话、恢复与 API

- `POST /api/sessions`：新建会话。
- `GET /api/sessions`：列出会话。
- `GET /api/sessions/{id}`：消息和运行列表。
- `POST /api/runs/stream`：支持 `session_id`，执行 SSE。
- `GET /api/runs/{id}`：运行状态、计划、输出和待审批项。
- `GET /api/runs/{id}/events?after=N`：按序号重放事件。
- `POST /api/runs/{id}/cancel`：请求取消。
- `POST /api/runs/{id}/approval`：`{"approval_id":"...","approved":true}`，返回恢复运行 SSE。

同一会话只允许一个执行中或待审批运行。后续请求以服务端历史为准；客户端 `history`
只用于新会话首次导入。模型历史依旧限最近 20 条和 24,000 字符，统一在上下文层控制。
千问和本地 Demo 可接收历史；其他 Provider 必须显式声明 `supports_history`。

服务启动会把执行中断的运行标记为失败，而不是自动重放可能已发生副作用的操作。
审批暂停状态可从 SQLite 恢复；`needs_input` 通过同会话的下一条消息继续理解任务，
不是恢复旧工具调用。停止请求不能撤销已经在远端完成的动作。

## 运行边界

当前服务面向单用户、单进程部署。SQLite 提供持久化，运行锁和动态注册表仍在进程内。
团队/多进程部署需要宿主提供身份认证、会话访问控制、分布式运行锁与配置同步；
这些并未由本轮实现。工具 Schema 和 MCP 只读声明不是业务授权的替代品。

HTML 和文件输出提供注册接口，本轮没有新增 HTML 清理器或文件生成器。
长期摘要、跨会话记忆、工具连接池也不属于本轮完成范围。
