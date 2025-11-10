# StockAI Trader

AI 股票助手，帮助普通投资者在 1 分钟内获得结构化的交易建议。

## 后端快速开始
- 创建并激活虚拟环境，安装依赖：`pip install -e .[storage]`（如不需要 Parquet 支持可省略 `[storage]`）。
- 默认整合 yfinance（美股/港股优先）与 AkShare（A 股/美股备用）。如需启用 AkShare，请额外安装 `[china]`，并使用对应市场代码（A 股如 `sh600519`，美股直接 `AAPL`）。
- 若需要禁用 AkShare 美股备选源，可设置环境变量 `AKSHARE_DISABLE_US=1`。
- 宏观指数拉取默认缓存 30 分钟，若 yfinance 限速会自动回退到 AkShare 指数数据。
- 如配置 `FINNHUB_API_KEY` 或 `TUSHARE_TOKEN`，宏观/指数数据会在 yfinance/AkShare 失败后继续尝试对应接口。
- 若担心单个 Tushare token 限流，可设置 `TUSHARE_TOKEN_POOL=tokenA,tokenB`（逗号分隔，按顺序自动切换），并保留 `TUSHARE_TOKEN` 作为兜底。

### AI 总结（可选）
- 将 `.env.example` 复制为 `.env`，填入所需的 API Key；项目启动时会自动加载 `.env`（依赖 `python-dotenv`）。
- 配置环境变量：
  - `LLM_PROVIDER`：`openai` / `qwen` / `gemini`。
  - `OPENAI_API_KEY` / `QWEN_API_KEY`（或 `DASHSCOPE_API_KEY`）/ `GEMINI_API_KEY` 等。
  - 可选 `LLM_MODEL`、`LLM_TIMEOUT` 等。
- 启用后，批量分析和每日报告会生成额外的 AI 文本总结（失败时自动回退到模板化输出）。
- 若希望默认启用，可设置 `LLM_AUTO_ANALYSIS=1`，前端也提供人工勾选的 “启用 AI 总结” 开关。
- 未显式指定 `LLM_PROVIDER` 时，代码会按照 Qwen → OpenAI → Gemini 的顺序检测 API Key，并采用默认模型 `qwen3-max` / `gpt-5` / `gemini-2.5-pro`。
- 启动服务：`uvicorn api:app --reload`。
- 调用接口示例：
  ```bash
  curl -X POST http://localhost:8000/analyze \
    -H "Content-Type: application/json" \
    -d '{"ticker":"AAPL","timeframe":"1d"}'
  ```

### 自选股与批量分析 API
- `GET /watchlist` / `POST /watchlist`：查询或覆盖自选股列表。
- `POST /watchlist/add` / `/watchlist/remove`：增删单只股票。
- `POST /watchlist/analyze`：批量分析当前自选股，返回每只股票的操作建议与置信度。
- `GET /reports` / `/reports/latest` / `/reports/{date}`：查询每日自动报告及历史记录。
- `GET /macro/overview`：获取指数、板块与市场宽度的实时概览。
- `POST /scanner/opportunities`：扫描做多/做空机会，可指定股票池、周期与方向。

### 每日自动报告调度
- 运行一次手动报告生成：`python scheduler.py` 或 `python scripts/run_daily_report.py`。
- 若需自动化调度，可在部署脚本中调用 `scheduler.start_scheduler()`，默认每日 17:30（Asia/Shanghai）触发。
- 报告会保存至 `reports/` 目录，同时生成 JSON 与文本文件，供前端与外部渠道使用。

## 前端快速开始
- 进入 `frontend/` 并安装依赖：`npm install`。
- 本地开发：`npm run dev`（默认 5173 端口，已代理 `/analyze` 到 8000）。
- 新增功能：
  - 单股分析页面，可查看入场/止损/目标价与风险提示。
  - 自选股管理模块，支持添加/移除股票并触发批量分析。
  - 宏观板块概览，展示全球指数与行业涨跌情况。
  - 机会扫描器，可筛选做多/做空候选。
  - 每日报告面板，可浏览最新与历史报告摘要（含宏观与机会信息）。

## 目录结构概览
- `datahub/`：数据抓取、缓存与指标计算。
- `engine/`：信号打分、规则引擎与报告生成。
- `api.py`：FastAPI 入口，暴露 `/analyze`。
- `frontend/`：Vue3 + Vite 前端。
- `docs/`：产品 PRD 与实施指南。
