# Dev Agent Workbench

一个从零实现的、可嵌入业务项目并在运行时扩展的通用 Agent：

```text
用户消息 + 结构化 @引用
        ↓
Context Resolver
        ↓
Intent Analyzer
        ↓
Capability Router
        ↓
Planner
        ↓
Executor
        ↓
Response Synthesizer
```

后端使用 Python + FastAPI，前端使用 React + Vite。支持动态导入外部 Skill、连接远程 MCP 并发现工具，所有扩展都会立即进入 `@` 菜单和能力路由。模型默认使用通义千问；没有配置密钥时自动回退到 Demo Provider。

## 快速启动

### 后端

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --host 127.0.0.1 --port 8421
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。

## 使用通义千问

复制环境变量并配置：

```bash
cp .env.example .env
export AGENT_PROVIDER=qwen
export DASHSCOPE_API_KEY='sk-...'
export QWEN_MODEL='qwen-plus'
export QWEN_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
```

如果使用百炼业务空间专属域名，将 `QWEN_BASE_URL` 替换为对应地域和 Workspace 的 OpenAI-compatible 地址。

## 动态扩展

点击页面右上角“扩展”：

- **Skills**：上传一个包含且仅包含一个 `SKILL.md` 的 ZIP。服务端会检查路径穿越、符号链接、文件数量和体积，并自动生成缺失的 `skill.json`。成功后无需重启。
- **MCP**：填写 Streamable HTTP 或 SSE 地址。服务端连接、执行 `tools/list`，并将每个工具注册成 Capability；后续可以通过 `@MCP工具` 显式选择。
- **千问**：查看当前 Provider、模型以及是否已配置服务端密钥。

运行轨迹会展示 MCP 工具的能力选择、参数生成、调用结果和最终合成过程。MCP 认证信息只保存在后端 `data/mcp_servers.json`，文件权限设置为 `0600`，不会通过列表接口返回。

## 多轮对话

- 服务端 SQLite 保存会话、消息、运行快照和可重放事件，前端通过 session_id 恢复。
- 新会话允许一次性导入浏览器历史；后续历史以服务端为准，限最近 20 条和 24,000 字符。
- 历史、已加载 Skill 和本轮工具结果用于千问意图理解、参数生成与回答；密钥仍在 MCP 连接层。
- OpenAI Provider 默认不接收这些历史，避免把已授权给千问的数据发送到其他服务。
- 当前会话 ID 保存在浏览器；刷新会恢复服务端消息和最近运行记录。
- “新对话”创建新的上下文，旧会话仍保留在服务端，可通过会话 API 读取。
- `run.started` 和 `run.completed` 事件会记录实际使用的历史条数。

## 通用运行内核

参见 [ARCHITECTURE.md](ARCHITECTURE.md) 了解注册 Resolver、Capability、Policy、Renderer
以及替换存储接口的方法。已支持步骤结果传递、Skill 提前加载、参考文件读取、千问动态
追加步骤、工具参数校验、审批暂停/恢复、停止运行和事件重放。

MCP 默认要求每次调用确认。写操作不会自动重试，重启不会重放中断操作。
当前是单用户单进程框架；业务身份与访问权限由宿主的 PermissionPolicy 提供。

## 未发布作业卡片场景

该业务场景默认关闭，因此合并到通用分支后不会改变原有 Router 行为。

使用内置模拟数据预览完整闭环：

```properties
ENABLE_UNPUBLISHED_HOMEWORK_SCENARIO=true
ENABLE_SCENARIO_FIXTURES=true
```

接入真实 Skill 和 MCP：

```properties
ENABLE_UNPUBLISHED_HOMEWORK_SCENARIO=true
ENABLE_SCENARIO_FIXTURES=false
```

场景要求查询助手作为 `data_provider`、备课助手作为 `output_owner`，最终输出必须通过
`preparation.unpublished_homework_cards.v1` Schema 校验。

## 示例

在输入框键入 `@`，选择“支付故障诊断”Skill 和“checkout.py”文件，然后发送：

```text
帮我定位支付为什么失败，并给出修改建议
```

界面会展示：

1. `context.resolved`：`@` 引用被解析为带来源的上下文快照。
2. `intent.detected`：得到结构化任务目标、对象、约束和期望输出。
3. `route.selected`：显式 Skill 优先，自动路由补充需要的 Tool。
4. `plan.created`：生成可执行步骤。
5. `capability.*`：逐项执行 Skill 或 Tool。
6. `message.delta`：流式返回最终回答。

## 扩展点

- 在 `backend/app/skills/` 添加 Skill 文件并注册。
- 实现新的 `MentionResolver` 以支持 `@课程`、`@订单`、`@代码文件` 等业务对象。
- 实现新的 `CapabilityExecutor` 以接入数据库、HTTP API 或 MCP。
- 前端只提交结构化 `mentions`，密钥和实际数据访问始终留在后端。

## API

- `GET /api/health`
- `GET /api/capabilities`
- `GET /api/mentions?q=&kind=`
- `GET /api/skills`
- `POST /api/skills/import`
- `GET /api/mcp-servers`
- `POST /api/mcp-servers`
- `POST /api/mcp-servers/{id}/refresh`
- `POST /api/runs/stream`，返回 SSE

请求示例：

```json
{
  "message": "帮我定位支付为什么失败",
  "mentions": [
    {
      "kind": "skill",
      "id": "debug-code",
      "label": "支付故障诊断"
    },
    {
      "kind": "file",
      "id": "checkout.py",
      "label": "checkout.py"
    }
  ]
}
```
