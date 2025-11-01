# StockAI Trader

AI 股票助手，帮助普通投资者在 1 分钟内获得结构化的交易建议。

## 后端快速开始
- 创建并激活虚拟环境，安装依赖：`pip install -e .[storage]`（如不需要 Parquet 支持可省略 `[storage]`）。
- 启动服务：`uvicorn api:app --reload`。
- 调用接口示例：
  ```bash
  curl -X POST http://localhost:8000/analyze \
    -H "Content-Type: application/json" \
    -d '{"ticker":"AAPL","timeframe":"1d"}'
  ```

## 前端快速开始
- 进入 `frontend/` 并安装依赖：`npm install`。
- 本地开发：`npm run dev`（默认 5173 端口，已代理 `/analyze` 到 8000）。

## 目录结构概览
- `datahub/`：数据抓取、缓存与指标计算。
- `engine/`：信号打分、规则引擎与报告生成。
- `api.py`：FastAPI 入口，暴露 `/analyze`。
- `frontend/`：Vue3 + Vite 前端。
- `docs/`：产品 PRD 与实施指南。
