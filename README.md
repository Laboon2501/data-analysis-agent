# LangGraph Data Analysis Agent

> 基于 LangGraph 重写的数据分析 Agent 技术预览版。<br>
> 支持 SQL / SQLite 数据源、CSV / Excel / Parquet 文件数据源、字段问答、明确问题分析、开放探索、图表 artifact、Report / Excel / PPT / Dashboard 导出、SSE 事件流、Web 工作台、会话历史、可选 LLM / MCP / Celery 路径。

当前代码版本：`0.2.0a0`<br>
发布标签写法：`v0.2.0-alpha / technical preview`<br>
Python 要求：`>=3.11,<3.14`

## 目录

- [项目定位](#项目定位)
- [快速开始](#快速开始)
- [Web 工作台](#web-工作台)
- [API 端点](#api-端点)
- [环境变量](#环境变量)
- [数据源](#数据源)
- [LLM 配置](#llm-配置)
- [典型流程](#典型流程)
- [评估与测试](#评估与测试)
- [MCP](#mcp)
- [Celery / Redis / Postgres](#celery--redis--postgres)
- [项目结构](#项目结构)
- [安全边界](#安全边界)
- [已知限制](#已知限制)

## 项目定位

这个项目是结构化数据分析 Agent。核心目标是让用户对数据库或文件数据源进行自然语言分析：

```text
近 12 个月销售趋势怎么样？
各品类 GMV Top 5 是什么？
这个表有哪些字段？
帮我看看这个数据有什么可以分析的
帮我生成报告 / PPT / Excel / Dashboard
```

系统采用显式 LangGraph 工作流。

核心构件：

```text
FastAPI API
+ WorkerBackend / JobRunner
+ LangGraph workflows
+ Typed AgentState
+ DatabaseProfile
+ SQLGuard
+ ToolRegistry
+ ArtifactStore
+ SessionStore
+ EventStore
+ optional LLM strategy
+ optional MCP adapter
+ optional Celery backend
```

## 当前能力

### 数据源管理

支持：

- SQLite / SQLAlchemy 数据源
- CSV 文件数据源
- Excel `.xlsx` 文件数据源
- Parquet 文件数据源，依赖可用时启用
- 本地文件路径注册，默认关闭
- Web UI 上传文件、选择数据源、触发 profile
- 数据源 metadata 脱敏

文件数据源会转换为可查询的只读 SQLite 表，复用现有 Context Manager、SQLGuard、分析和导出链路。

### Context Manager

Context Manager 会生成 `DatabaseProfile`：

- 表名、字段名、字段类型
- 样例值摘要
- 表角色和字段语义
- 候选指标和候选维度
- 时间字段、指标字段、维度字段
- schema hash
- profile status/cache

后续 schema QA、直接分析、开放探索和 SQL 生成都应读取 `DatabaseProfile`，不能让 LLM 凭空猜字段。

### Schema QA / 字段问答

以下问题走 `schema_qa` / data inspection，不进入 report/export，也不要求已有分析结果：

```text
这个表有哪些字段？
帮我看看这个表格都有哪些字段
把字段告诉我
有哪些列？
字段是什么意思？
这个文件包含什么字段？
哪些字段可以作为指标？
哪些字段适合做维度？
```

输出包括字段列表、类型、样例摘要、候选指标、候选维度和可分析方向。

### 明确问题分析

典型问题：

```text
近 12 个月销售趋势怎么样？
各品类 GMV Top 5 是什么？
不同地区订单量如何？
平均单价最高的商品是什么？
```

主流程：

```text
route
→ ensure_database_profile
→ retrieve_similar_cases
→ interpret_question
→ make_analysis_plan
→ draft_sql
→ validate_sql
→ risk_check_sql
→ execute_sql
→ check_result
→ repair_sql_if_needed
→ decide_chart
→ generate_chart_artifact
→ generate_insight
→ build_analysis_package
→ final_response
```

### 开放探索

典型问题：

```text
帮我看看这个数据库有什么可以分析的
帮我探索性地分析一下这张表的数据
这张表有什么可以分析的吗？
```

开放探索会基于 `DatabaseProfile` 自动生成多个分析方向，执行 Top N 个简单分析并生成发现摘要。

### 导出

支持 artifact 类型：

- Markdown report
- Excel `.xlsx`
- PPT `.pptx`
- Dashboard JSON spec
- Chart JSON artifact

导出必须先有 analysis/report context，再走确认命令：

```text
report_confirm
excel_confirm
ppt_confirm
dashboard_confirm
```

确认后复用已有 `AnalysisPackage` / `ReportOutline`，不重新分析数据，不重新规划 outline。

## 数据源

### SQL / SQLite

通过 API 注册：

```text
POST /datasources
```

通过环境变量配置：

```text
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite
DATA_ANALYSIS_AGENT_DATASOURCE_ID=ecommerce-demo-sqlite
```

### 文件上传

```text
POST /datasources/upload
```

支持扩展名：

```text
.csv
.xlsx
.parquet
```

Parquet 依赖不可用时会返回结构化错误。

### 本地路径注册

```text
POST /datasources/from-path
```

默认关闭，必须显式启用：

```text
DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true
```

安全限制：

- 禁止路径穿越
- 禁止读取 `.env` 等敏感文件
- 不向前端暴露完整敏感路径
- 不把文件正文写入 events/history/session context summary

## LLM 配置

默认后端不主动发真实 LLM 请求；Web UI 的会话配置入口固定提交
`real_llm`。网页端不再暴露测试模型模式，也不再暴露 LLM router
开关。

Web UI `enabled_nodes` 支持：

```text
planner
sql_drafter
insight_writer
```

网页端节点 alias 映射：

```text
planner -> interpret_question, make_analysis_plan
sql_drafter -> draft_sql
insight_writer -> generate_insight
```

安全约束：

- 普通聊天 no-tools
- LLM router 只输出 intent，不输出 SQL
- SQL drafter 输出仍必须经过 SQLGuard 和字段校验
- LLM 不能自由调用 MCP/tools
- API key 不返回前端，不写入 events/history/session/artifact

## 典型流程

### 使用 demo 数据库

```text
1. python scripts/run_dev.py
2. Web UI 选择 demo datasource
3. Profile datasource
4. 输入：近 12 个月销售趋势怎么样？
5. 查看回答、SQL、chart artifact
6. 生成 Report / Excel / PPT / Dashboard
```

### 字段问答

```text
这个表有哪些字段？
帮我看看这个表格都有哪些字段
哪些字段可以作为指标？
```

这些问题应进入 `schema_qa`，不应返回“当前会话没有可用的分析结果”。

### 开放探索

```text
帮我看看这个数据库有什么可以分析的
这张表有什么可以分析的吗？
帮我探索性地分析一下这张表的数据
```

这些问题应进入 `open_exploration`。

### 导出

```text
生成报告
导出 Excel
做成 PPT
生成 Dashboard
```

导出确认命令：

```text
report_confirm
excel_confirm
ppt_confirm
dashboard_confirm
```

## Artifact

Artifact API：

```text
GET /artifacts/{artifact_id}
GET /artifacts/{artifact_id}/content
```

支持：

| 类型 | 内容 |
| --- | --- |
| chart | 轻量 JSON chart spec |
| report | Markdown report |
| excel | `.xlsx` |
| ppt | `.pptx` |
| dashboard | Dashboard JSON spec |

events/history/session context summary 只保存 `artifact:<id>` 引用，不保存 artifact 正文。


## MCP

本地 demo MCP server：

```bash
copy scripts\mcp.example.json scripts\mcp.local.json
```

启用 `demo_mcp` 后：

```bash
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id demo_mcp --list-tools
```

调用工具：

```bash
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id demo_mcp --call-tool mcp__demo_mcp__list_demo_tables
```

```bash
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id demo_mcp --call-tool mcp__demo_mcp__describe_demo_table --tool-args "{\"table\":\"orders\"}"
```

MCP 安全边界：

- 默认不启用
- stdio command 有 allowlist
- 不使用任意 shell command
- 工具名格式：`mcp__{server_id}__{raw_tool_name}`
- MCP tools 仍受 ToolRegistry allowed_nodes 限制
- LLM 不会自由调用 MCP tools


## 安全边界

### SQL

- 只允许 SELECT / WITH SELECT
- 禁止 INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE / CREATE / GRANT / REVOKE
- SQL 执行前必须经过 SQLGuard
- 表名和字段名必须存在
- `validate_sql` 失败不能进入 `execute_sql`
- LLM 生成 SQL 不会直接执行

### 工具

- ToolRegistry 按节点限制工具
- 不写巨大 if/elif dispatcher
- 不让 LLM 自由调用全部工具
- 普通聊天不能直接导出 PPT / Excel / Report / Dashboard

### History / Context

- `SessionStore` 保存用户可见历史
- `AgentContextSummary` 只保存结构化摘要
- 不保存上传文件正文
- 不保存 artifact 正文
- 不保存 API key
- 不把完整 chat history 当主要工作流状态

### Artifact

- events/history 只保存 artifact ref
- artifact 正文通过 Artifact API 获取
- 大 payload 不进入 SSE history

## 已知限制

- Web UI 仍是 vanilla technical preview workstation
- 没有登录、权限和多用户隔离
- 默认不提供生产级部署配置
- Celery / Redis / Postgres 路径需要本地手动集成验证
- Dashboard renderer 是轻量实现，不是完整 BI 产品
- Parquet 依赖可选
- 真实 LLM eval 不进入默认 CI
- 真实第三方 MCP server 需要手动验证
- 复杂业务口径仍可能需要 human confirmation
- 当前仓库没有 `LICENSE` 文件

## License

当前仓库未检测到 `LICENSE` 文件。发布前建议明确 license，并同步 `docs/third_party_notices.md` 中的上游来源说明。

## Release / CI Compatibility Notes

Compatibility label: v0.2.0-alpha technical preview.

This Chinese README is the GitHub homepage, and it keeps the English release
anchors used by CI documentation checks: Architecture Overview, Directory Structure,
Quick Start, Demo Database, FastAPI Memory Backend, Eval And Tests,
Optional Smoke Tests, and Safety Boundaries. Core safety terms: SQLGuard,
artifact, fast-path.

Install and verify locally:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m evals.runner
python -m ruff check .
python -m ruff format --check .
python scripts/create_demo_db.py
python scripts/run_demo_flow.py
python scripts/run_api.py
python scripts/run_llm_smoke.py
python scripts/run_llm_eval.py
python scripts/run_mcp_smoke.py
python scripts/run_integration_smoke.py
python examples/client/minimal_client.py
python examples/client/demo_flow_client.py
docker compose up --build api
docker compose -f docker-compose.celery.yml up --build
```

Deployment notes: docs/deployment.md.
