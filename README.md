# Travel Assistant Agent

[中文](#中文说明) | [English](#english)

---

## 中文说明

Travel Assistant Agent 是一个面向城市自由行的旅行规划系统。项目基于 FastAPI、Pydantic、`hello-agents` 和 MCP 风格工具调用构建，支持根据目的地、日期、预算、偏好、忌讳、同行人数、旅行节奏、住宿风格和交通方式生成结构化旅行计划。

系统采用候选池验真机制：景点和酒店先由工具检索形成候选池，再由规划流程选择和校验。最终报告包含每日住宿、每日景点、餐饮建议、详细交通路线、预算拆分、天气提醒和风险提示。

### 核心能力

- 多阶段规划流程：景点研究、天气研究、酒店研究、行程骨架、每日行程、餐饮落地、交通注入和预算刷新。
- 景点候选池验真：景点必须来自工具返回的真实候选，避免凭空新增或改写名称。
- 酒店候选池验真：酒店必须来自酒店工具候选，并按照旅行节奏生成住宿轮换策略。
- 旅行节奏规则：紧凑、平衡、慢游分别对应更高、中等、较低的每日景点密度和换酒店频率。
- 餐饮意图落地：每日行程先生成早/中/晚餐饮意图，再由后端按锚点检索真实餐厅；无可靠结果时保留区域餐饮建议，不显示假地址。
- 详细交通路线：根据每日地点链注入交通方式、距离、耗时、费用、路线明细和备选方案。
- 预算刷新：餐饮落地和交通注入后重新汇总酒店、景点、餐饮、交通、预备金和总预算。
- 前端可视化报告：提供表单填写、进度展示、住宿卡片、每日行程、交通详情、预算拆分和错误提示。
- 轻量旅行范围：前端限制 1-7 天行程，适合生成轻量级城市旅行建议。

### 系统架构

```text
Browser UI
  -> FastAPI application
  -> TravelPlannerService
  -> AttractionSearchAgent
  -> WeatherSearchAgent
  -> HotelSearchAgent
  -> ItineraryPlanningAgent
       -> Skeleton stage: daily_stays + daily_attraction_assignments
       -> Day stage: DayPlan + meal_intents
  -> TravelBackendTool / MCP-style tools
  -> TravelDataBackend
  -> restaurant grounding + transport injection + budget refresh
  -> TripPlan JSON
  -> Report rendering
```

### 规划流程

1. 校验旅行请求，生成统一的偏好、忌讳和预算上下文。
2. 景点研究阶段调用景点 POI 工具，形成候选池并输出轻量选择结果。
3. 后端根据 `candidate_id` 或名称从完整候选池补全景点地址、坐标、类别和门票信息。
4. 天气研究阶段生成覆盖全部旅行日期的天气建议和风险提醒。
5. 酒店研究阶段调用酒店工具生成候选池，并输出候选酒店名称和推荐酒店名称。
6. 后端根据酒店名称从完整候选池补全价格、地址、坐标、区域和简介。
7. 行程骨架阶段生成推荐酒店、每日住宿链和每日景点分配。
8. 每日行程阶段按天生成景点顺序、时间安排和餐饮意图。
9. 餐饮落地阶段按酒店、景点或夜间区域检索真实餐厅。
10. 交通注入阶段根据每日地点链生成详细路线，并刷新总预算。

### Agent 分工

| 模块 | 输入 | 输出 | 约束 |
| --- | --- | --- | --- |
| `AttractionSearchAgent` | 旅行请求、偏好、忌讳、景点工具 | 景点轻量选择结果 | 只能选择工具候选 |
| `WeatherSearchAgent` | 城市、日期、约束 | `WeatherResearch` | 天气必须覆盖完整行程 |
| `HotelSearchAgent` | 预算、住宿风格、住宿晚数、轮换策略 | 酒店名称列表和推荐酒店名 | 只能选择工具候选 |
| `ItineraryPlanningAgent` Skeleton | 已验真景点、酒店、天气、轮换策略 | 推荐酒店、每日住宿、每日景点分配 | 名称必须来自白名单 |
| `ItineraryPlanningAgent` Day | 单日酒店、单日景点、天气、约束 | `DayPlan` 和 `meal_intents` | 不新增景点/酒店，不编造餐厅地址 |
| 后端服务 | 候选池、餐饮意图、地点链 | 完整景点/酒店、真实餐饮、交通路线、预算 | 负责验真、补全和一致性校验 |

### 项目结构

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
    │   ├── travel_backend.py
    │   ├── travel_server.py
    │   └── travel_tool.py
    ├── services/
    │   └── planner.py
    └── utils/
        └── json_utils.py
```

### 本地运行

创建并激活虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```powershell
pip install -r requirements.txt
```

创建本地配置文件：

```powershell
copy .env.example .env
```

启动服务：

```powershell
python main.py
```

默认访问地址：

```text
http://127.0.0.1:8010
```

如果 `.env` 中修改了 `PORT`，请使用对应端口访问。

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `Travel Assistant Agent` | 应用名称 |
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `8010` | 服务端口 |
| `AMAP_API_KEY` | 空 | 高德地图 Key，用于 POI、地理编码和路线规划 |
| `QWEATHER_API_KEY` | 空 | 和风天气 Key |
| `LLM_ENABLED` | `false` | 是否启用模型规划流程 |
| `LLM_PROVIDER` | `deepseek` | 模型服务提供方 |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_API_KEY` | 空 | 模型服务 API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible API 地址 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_TIMEOUT_SECONDS` | `60` | 请求超时时间 |

### API

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 返回服务状态、模型状态和可用工具 |
| `POST` | `/api/plan` | 同步生成旅行计划 |
| `POST` | `/api/plan/tasks` | 创建异步规划任务 |
| `GET` | `/api/plan/stream/{task_id}` | 通过 Server-Sent Events 返回进度和最终结果 |

### 数据与安全

- `.env`、`.venv/`、`.idea/`、`data/`、`memory/`、`skills/` 和 `tool-output/` 已加入 `.gitignore`。
- API Key 只应写入本地 `.env`，不要提交到仓库。
- `.env.example` 只保留变量名和空值，用于说明配置格式。

---

## English

Travel Assistant Agent is a city-trip planning system built with FastAPI, Pydantic, `hello-agents`, and MCP-style tool calling. It generates structured travel plans from destination, dates, budget, preferences, taboos, traveler count, travel pace, hotel style, and transport mode.

The system uses candidate-pool grounding. Attractions and hotels are first collected by tools, then selected and verified by the planning workflow. The final report includes daily stays, daily attractions, meal suggestions, detailed transport routes, budget breakdowns, weather notes, and risk alerts.

### Key Features

- Multi-stage workflow for attraction research, weather research, hotel research, itinerary skeletons, day plans, meal grounding, route injection, and budget refresh.
- Attraction grounding: attractions must come from tool candidates.
- Hotel grounding: hotels must come from hotel tool candidates and follow the selected rotation policy.
- Pace rules: intense, balanced, and relaxed modes map to different attraction densities and hotel rotation intervals.
- Meal intent grounding: day plans generate breakfast/lunch/dinner intents; the backend searches real restaurants near hotels, attractions, or night areas.
- Safe fallback for meals: if no reliable restaurant is found, the report keeps a regional meal suggestion without a fake address.
- Detailed transport routes with mode, distance, duration, cost, route segments, and alternatives.
- Budget refresh after meals and transport routes are grounded.
- Browser UI with form input, progress streaming, hotel cards, daily itinerary, route details, budget breakdown, and error feedback.
- Lightweight trip scope: the frontend limits plans to 1-7 days.

### Architecture

```text
Browser UI
  -> FastAPI application
  -> TravelPlannerService
  -> AttractionSearchAgent
  -> WeatherSearchAgent
  -> HotelSearchAgent
  -> ItineraryPlanningAgent
       -> Skeleton stage: daily_stays + daily_attraction_assignments
       -> Day stage: DayPlan + meal_intents
  -> TravelBackendTool / MCP-style tools
  -> TravelDataBackend
  -> restaurant grounding + transport injection + budget refresh
  -> TripPlan JSON
  -> Report rendering
```

### Planning Flow

1. Validate the travel request and build a unified constraint context.
2. Search attraction POIs and produce lightweight attraction selections.
3. Hydrate selected attractions from the full backend candidate pool.
4. Generate weather suggestions and risk notes for the full trip date range.
5. Search hotel candidates and produce selected hotel names plus a recommended hotel name.
6. Hydrate selected hotels from the full backend candidate pool.
7. Generate the itinerary skeleton: recommended hotel, daily stays, and daily attraction assignments.
8. Generate each day plan with attraction order, time ranges, and meal intents.
9. Ground meal intents through restaurant POI search.
10. Inject detailed transport routes and refresh the budget.

### Responsibilities

| Module | Input | Output | Constraint |
| --- | --- | --- | --- |
| `AttractionSearchAgent` | Travel request, preferences, taboos, attraction tools | Lightweight attraction selections | Select only tool candidates |
| `WeatherSearchAgent` | City, dates, constraints | `WeatherResearch` | Forecast covers the whole trip |
| `HotelSearchAgent` | Budget, hotel style, stay nights, rotation policy | Hotel names and recommended hotel name | Select only tool candidates |
| `ItineraryPlanningAgent` Skeleton | Verified attractions, hotels, weather, rotation policy | Recommended hotel, daily stays, daily attraction assignments | Copy names from whitelists |
| `ItineraryPlanningAgent` Day | Fixed day hotels, fixed attractions, weather, constraints | `DayPlan` and `meal_intents` | Do not add attractions/hotels or invent restaurant addresses |
| Backend service | Candidate pools, meal intents, location chains | Hydrated places, grounded meals, routes, budget | Grounding, hydration, and consistency checks |

### Local Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create local configuration:

```powershell
copy .env.example .env
```

Start the server:

```powershell
python main.py
```

Open:

```text
http://127.0.0.1:8010
```

If `PORT` is changed in `.env`, use that port instead.

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `APP_NAME` | `Travel Assistant Agent` | Application name |
| `HOST` | `127.0.0.1` | Server host |
| `PORT` | `8010` | Server port |
| `AMAP_API_KEY` | empty | AMap key for POI, geocoding, and routing |
| `QWEATHER_API_KEY` | empty | QWeather key |
| `LLM_ENABLED` | `false` | Enables the model-backed planning workflow |
| `LLM_PROVIDER` | `deepseek` | Model provider |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `LLM_API_KEY` | empty | Model API key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible API base URL |
| `LLM_TEMPERATURE` | `0.2` | Generation temperature |
| `LLM_TIMEOUT_SECONDS` | `60` | Request timeout |

### API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Service status, model status, and available tools |
| `POST` | `/api/plan` | Create a trip plan synchronously |
| `POST` | `/api/plan/tasks` | Create an asynchronous planning task |
| `GET` | `/api/plan/stream/{task_id}` | Stream progress and final result through Server-Sent Events |

### Data and Security

- `.env`, `.venv/`, `.idea/`, `data/`, `memory/`, `skills/`, and `tool-output/` are ignored by Git.
- API keys should stay in the local `.env` file and must not be committed.
- `.env.example` documents configuration names without secrets.
