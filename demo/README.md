# Ecommerce Demo Dataset

这个目录提供一个本地电商演示数据集，用于展示 Context Manager、Direct Analysis、
Open Exploration、Report/Export、Artifact 和 SSE 流程。

## 数据表

- `users`: 用户、注册月份、所属地区和获客渠道。
- `products`: 商品、品类和单价。
- `orders`: 规则分析优先使用的事实表，包含时间、地区、渠道、品类、GMV、销售额、数量和订单量字段。
- `order_items`: 订单明细，保留商品级数量和金额。
- `regions`: 地区维表。
- `channels`: 渠道维表。

## 生成 SQLite

默认生成到 `demo/ecommerce_demo.sqlite`：

```bash
python scripts/create_demo_db.py
```

指定输出路径：

```bash
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
```

`*.sqlite` 文件是本地生成物，不需要提交。

## 演示流程

```bash
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite
```

脚本会使用 memory backend 和 rule strategy 依次执行：

- context profile
- direct analysis
- open exploration
- report outline
- excel_confirm
- ppt_confirm
- dashboard_confirm

输出只包含 job、events、final response 和 artifact references，不会把 artifact 正文写进 events。

