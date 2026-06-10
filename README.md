# Travel Assistant Agent

基于 FastAPI、`hello-agents` 与 MCP 工具调用机制构建的智能旅行规划系统。项目面向城市自由行场景，支持用户输入目的地、日期、预算、旅行偏好、忌讳、同行人数、住宿风格与交通方式，并生成一份包含景点筛选、酒店建议、餐饮候选、天气提醒、路线规划与预算拆分的结构化旅行报告。

This repository contains a FastAPI-based intelligent travel planning system powered by `hello-agents` and MCP tools. It turns a structured travel request into a grounded itinerary with attractions, hotels, restaurants, weather, local transport, budget estimates, and risk notes.

## 核心能力

- 旅行需求建模：城市、日期、预算、偏好、忌讳、人数、节奏、住宿风格、交通方式等参数统一由 Pydantic 校验。
- 多 Agent 工作流：景点搜索、天气研究、酒店推荐与行程编排分别由专门 Agent 处理。
- MCP 工具集成：本地 MCP travel server 向 Agent 暴露城市画像、景点检索、酒店候选、餐饮候选和路线估算能力。
- 真实数据增强：可接入高德地图进行城市识别、POI 检索、酒店/餐饮候选、公交/驾车/步行路线估算。
- 天气信息增强：可接入和风天气，为每日行程生成温度、天气和出行建议。
- 可解释行程输出：结果包含数据来源、景点筛选理由、每日交通链路、预算拆分、打包建议和风险提醒。
- 稳定兜底路径：外部 API 或 LLM 不可用时，系统会使用内置城市样例和程序化规划逻辑生成可运行结果。
- 前端报告页：内置静态页面提供表单填写、生成进度、路线总览、住宿建议、景点筛选和每日行程展示。

## 系统架构

```text
Browser UI
  -> FastAPI application
  -> TravelPlannerService
  -> AttractionSearchAgent
  -> WeatherSearchAgent
  -> HotelSearchAgent
  -> ItineraryPlanningAgent
  -> MCP Travel Server
  -> TravelDataBackend
  -> TripPlan JSON
  -> Report Rendering
```

### 规划流程

1. 校验并标准化旅行请求。
2. 准备城市画像、偏好标签和景点候选。
3. 调用景点 Agent 结合 MCP 候选池筛选景点，并进行候选验真。
4. 获取天气数据，生成每日天气建议和风险提示。
5. 按预算、住宿风格、地理位置筛选酒店候选。
6. 基于景点、酒店和夜间活动区域检索餐饮候选。
7. 生成每日行程，并注入本地交通路线、路线明细和备选方案。
8. 汇总预算、打包建议、风险提醒和数据来源。

## 技术栈

- Python 3
- FastAPI
- Uvicorn
- Pydantic
- python-dotenv
- hello-agents
- fastmcp
- requests
- Vanilla HTML/CSS/JavaScript

## 项目结构

```text
travel_assistant_agent/
├── main.py
├── requirements.txt
├── README.md
├── .env.example
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── src/
    ├── app.py
    ├── config.py
    ├── models.py
    ├── llm.py
    ├── agents/
    │   ├── attraction_agent.py
    │   ├── weather_agent.py
    │   ├── hotel_agent.py
    │   └── itinerary_agent.py
    ├── mcp/
    │   ├── travel_server.py
    │   └── travel_backend.py
    ├── services/
    │   └── planner.py
    └── utils/
        └── json_utils.py
```

## 本地运行

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 准备配置

```powershell
copy .env.example .env
```

根据需要填写 `.env` 中的地图、天气或 LLM 配置。未填写外部服务密钥时，项目仍可使用内置兜底数据运行。

### 3. 启动服务

```powershell
python main.py
```

默认访问地址：

```text
http://127.0.0.1:8010
```

## 配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `Travel Assistant Agent` | 应用名称 |
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `8010` | 服务端口 |
| `AMAP_API_KEY` | 空 | 高德地图 API Key，用于 POI、地理编码和路线规划 |
| `QWEATHER_API_KEY` | 空 | 和风天气 API Key，用于城市天气预报 |
| `LLM_ENABLED` | `false` | 是否启用 LLM 增强规划 |
| `LLM_PROVIDER` | `deepseek` | LLM 提供商 |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_API_KEY` | 空 | LLM API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible API 地址 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_TIMEOUT_SECONDS` | `60` | 请求超时时间 |

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | 返回服务状态、LLM 状态和可用工具列表 |
| `POST` | `/api/plan` | 同步生成旅行计划 |
| `POST` | `/api/plan/tasks` | 创建异步旅行规划任务 |
| `GET` | `/api/plan/stream/{task_id}` | 通过 Server-Sent Events 返回规划进度和最终结果 |

## 请求模型概览

核心请求模型为 `TravelRequest`，主要字段包括：

| 字段 | 说明 |
| --- | --- |
| `city` | 旅行城市 |
| `start_date` / `end_date` | 行程日期范围 |
| `budget_min` / `budget_max` | 总预算范围 |
| `preferences` | 偏好标签，例如人文、艺术、自然、美食、购物、夜生活、亲子 |
| `extra_preferences` | 用户补充偏好 |
| `taboos` | 忌讳或不希望出现的安排 |
| `travelers` | 同行人数 |
| `pace` | 慢游、平衡或紧凑 |
| `hotel_style` | 经济、舒适或高档 |
| `transport_mode` | 公共交通、自驾、打车、混合出行或步行 |
| `transit_preference` | 公交路线偏好，例如推荐、少步行、地铁优先、公交优先 |

## 输出结果

规划结果使用 `TripPlan` 结构返回，包含：

- 行程主题与整体概览
- 景点数据来源、天气数据来源、酒店数据来源
- 景点筛选结果与偏好解释
- 推荐酒店
- 每日行程安排
- 交通路线、站点/道路明细和备选方案
- 餐饮安排
- 预算拆分
- 打包建议
- 风险提醒
- Agent 诊断信息

## Data Modes

The system is designed to run in different data modes:

- `live_amap`: uses AMap for geocoding, POI search, and route planning.
- `live_qweather`: uses QWeather for daily forecast data.
- `llm_generated`: uses the configured LLM to enhance research or itinerary generation.
- `program_fallback`: uses deterministic planning logic when LLM output is unavailable.
- `fallback`: uses local sample data or estimated values when external services are not configured.

## English Overview

Travel Assistant Agent is an end-to-end travel planning application. It accepts a structured travel request, researches destination candidates through agents and MCP tools, validates generated places against available candidates, and returns a complete itinerary report.

### Key Features

- Structured trip request validation with Pydantic.
- Multi-agent workflow for attractions, weather, hotels, restaurants, and itinerary generation.
- Local MCP travel server for tool-based city, POI, hotel, restaurant, and route capabilities.
- Optional AMap integration for live POI search, geocoding, and transport routing.
- Optional QWeather integration for live forecasts.
- Optional OpenAI-compatible LLM integration.
- Programmatic fallback planner for stable offline demos.
- Built-in browser UI with progress streaming and detailed report rendering.

### Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Open:

```text
http://127.0.0.1:8010
```

### Main Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Service health and tool availability |
| `POST` | `/api/plan` | Generate a trip plan synchronously |
| `POST` | `/api/plan/tasks` | Create an async planning task |
| `GET` | `/api/plan/stream/{task_id}` | Stream task progress and final result |

### Notes

- External API keys are optional. Without them, the app falls back to local sample data and estimates.
- LLM usage is optional. When disabled or unavailable, the service still returns a deterministic plan.
- Hotel, restaurant, and transport costs are planning estimates and should be treated as references.
