# Demo Dataset and Scenarios

本项目提供一个本地电商 demo 数据集，用来展示 direct analysis、open exploration、
report/export、artifact 和 SSE 流程。默认不调用真实 LLM，不依赖 Redis/Celery/Postgres。

## 生成 Demo DB

默认生成到 `demo/ecommerce_demo.sqlite`：

```bash
python scripts/create_demo_db.py
```

指定输出路径：

```bash
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
```

数据库由 `demo/ecommerce_demo.sql` 生成，可重复运行。`*.sqlite` 是本地生成物，不需要提交。

## 启动 API

普通本地 API 仍可用 memory backend 启动：

```bash
python scripts/run_api.py
```

如果只想一键跑完整 demo 流程，不需要先启动 uvicorn，直接使用 `run_demo_flow.py` 即可。

## 运行 Demo Flow

```bash
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite
```

脚本会使用 in-process FastAPI + memory runner 自动执行：

- context profile
- direct analysis
- open exploration
- report outline
- `excel_confirm`
- `ppt_confirm`
- `dashboard_confirm`

输出包含：

- `job_id`
- events 和可安全读取的 SSE event 类型
- `final_response`
- artifact references

输出不会包含 Excel/PPT 文件正文、完整 dashboard JSON 或 chart HTML。

## 推荐问题

- 近 12 个月销售趋势怎么样？
- 各品类 GMV Top 5 是什么？
- 不同地区订单量如何？
- 帮我看看这个数据库有什么可以分析的。

当前默认 rule strategy 主要根据字段名做英文规则匹配；中文问题更适合在本地 smoke 中显式启用 LLM 节点后验证。

## 下载 Artifact

从 demo flow 输出或事件中复制 `artifact_ref`，再通过 API 读取 metadata 和内容：

```bash
curl http://127.0.0.1:8000/artifacts/{artifact_id}
curl http://127.0.0.1:8000/artifacts/{artifact_id}/content --output artifact.bin
```

如果 artifact ref 形如 `artifact:abc`，API 也支持用最终 ID `abc` 查询。

常见 artifact：

- chart JSON spec
- Excel `.xlsx`
- PPTX
- dashboard JSON spec

## 可选 LLM 节点

默认关闭 LLM：

```bash
python scripts/run_demo_flow.py
```

显式启用时需要提供模型配置，并仍然不允许 LLM 自由调用全部工具：

```bash
python scripts/run_demo_flow.py \
  --llm-node sql_drafter \
  --llm-node insight_writer \
  --model your-model-name \
  --base-url https://your-provider.example.com/v1 \
  --api-key-env YOUR_PROVIDER_API_KEY
```

