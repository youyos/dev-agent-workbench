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

- 前端每轮携带最近最多 20 条用户/助手消息，后端再执行 24,000 字符总量限制。
- 历史消息用于千问的意图识别和最终回答；MCP 密钥、环境变量和执行事件不会进入历史。
- OpenAI Provider 默认不接收这些历史，避免把已授权给千问的数据发送到其他服务。
- 当前会话保存在浏览器本地存储中，刷新页面可恢复；点击“新对话”会清空本地会话。
- `run.started` 和 `run.completed` 事件会记录实际使用的历史条数。

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
