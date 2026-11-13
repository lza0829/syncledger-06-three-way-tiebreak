# 03-syncledger（双核对账）

Syncledger — 跨库/跨系统对齐对账：双端抽取 → 对齐键对账 → 差异处置 → 批次互证。

与 Feedstitch（多源 Feed 归并）、Batchgate（作业依赖编排）主链路不同。夹具全本地，不连活库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5300 |
| API | http://localhost:10300 |

## 主链

配置对账对与对齐键 → 触发双端抽取并对齐 → 落差异行与批次计数 → 页面互证

## 种子对账对

- **inventory_hq_vs_store**：总部库存 ↔ 门店库存（`sku_id`+`store_id`，比对 `qty`）
- **payment_vs_ledger**：支付网关 ↔ 账务流水（`txn_id`，比对 `amount`/`currency`）
- **sku_catalog_a_vs_b**：目录 A ↔ 目录 B（`sku_code`，比对 `name`/`category`）
- **retail_price_web_vs_pos**：网店价 ↔ 收银价（`sku_code`，比对 `price`/`currency`），挂第三参照夹具 `retail_price_master.json`

底座默认只**记差异、不自动盖写**；差异处置/契约/审计页留表与入口，深逻辑留给后题。侧栏不叫「工单」，避免撞禁名单「工单客服」。

## 第三参照裁决

对账对可挂一份**本地第三参照夹具**，冲突策略在两种之间**互斥**选一：

- `reference_wins`：以参照为准，把参照值盖向配置的指定侧（左端或右端）
- `annotate_only`：参照只标注，仍不盖写

规则：

1. 左右一致 → **不读参照**，仍记 matched。
2. 左右冲突、参照有该键且参照值等于左或右之一 → 按策略盖写/标注，记入「参照命中」并保留参照值。
3. 左右冲突、参照值与左右**皆不同** → 「参照分歧」分桶，**任何策略下都不盖写**。
4. 左右冲突、参照缺该对齐键（或缺被比对字段）→ 「待参照」分桶，**不计为已裁决**。
5. 仅左有/仅右有 → 参照「非冲突」，不参与裁决。
6. 参照缺键或参照分歧时，**不会**静默拿左端或右端冒充裁决结果。
7. 每个批次落参照策略快照；命中/待参照/分歧三个计数在 `GET /api/batches/{id}/reference-summary` 里由差异列表重算并做一致性校验（`consistent`、`checks`）。
8. 夹具为本地只读，盖写只记录在批次裁决记录（`decision_json` 的 before/after），不写回夹具文件。

相关接口：`GET /api/reference/fixtures`、`PUT /api/pairs/{id}/reference`、`GET /api/batches/{id}/reference-summary`。页面入口：`/reference`。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 测试

```bash
cd backend && python -m pytest tests -q
```

（本地亦可 `python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt httpx==0.28.1 && .venv/bin/python -m pytest backend/tests -q`。）

## 0-1 切口（未实现，见出题规划）

`master_slave_pick` / `side_only_policy` / `window_buffer` / `diff_disposition_flow` / `batch_idempotency` / …
