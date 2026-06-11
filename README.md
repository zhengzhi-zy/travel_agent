# Travel Assistant Agent

[中文](#中文说明) | [English](#english)

---

## 中文说明

Travel Assistant Agent 是一个面向城市自由行的智能旅行规划系统。项目基于 FastAPI、`hello-agents` 和 MCP 工具调用机制构建，支持用户输入目的地、日期、预算、偏好、忌讳、同行人数、旅行节奏、住宿风格与交通方式，并生成结构化旅行报告。

当前版本强调 **Agent 自主规划 + 候选池验真 + 后端落地真实路线/餐饮**：景点和酒店必须来自工具候选池，最终行程 Agent 先规划每日骨架，再按天生成行程与餐饮意图，后端随后调用地图能力补全真实餐饮 POI、详细交通路线和预算汇总。

### 核心能力

- 结构化旅行需求：使用 Pydantic 校验城市、日期、预算、人数、节奏、住宿风格、交通方式和用户约束。
- 多 Agent 工作流：景点、天气、酒店和最终行程分别由专门 Agent 处理。
- 候选池验真：景点和酒店必须来自 MCP 工具返回的真实候选，不允许最终行程随意新增或改写名称。
- 两阶段最终行程 Agent：Skeleton 阶段负责每日住宿和景点分配，Day 阶段负责单日行程、时间安排和餐饮意图。
- 餐饮意图落地：大模型生成早/中/晚餐饮意图，后端再按锚点调用高德 POI 搜索真实餐厅；找不到可靠餐厅时显示区域餐饮建议，不显示假地址。
- 酒店轮换策略：紧凑、平衡、慢游分别对应每 1/2/3 晚换一次酒店，并校验每日住宿链连续性。
- 景点数量补救：景点不足时最多补救两轮；仍不足则使用已验真的真实景点池降低每日密度继续生成，不编造景点。
- 详细交通路线：后端根据每日地点链注入交通路线、耗时、距离、费用、路线明细和备选方案。
- 预算刷新：交通注入和餐饮落地后重新汇总酒店、景点、餐饮、交通、预备金和总预算。
- 前端报告页：提供表单填写、异步进度、住宿卡片、路线总览、景点列表、每日行程、预算拆分和错误提示。
- 轻量旅行限制：前端限制 1-7 天行程，避免过长时间跨度导致候选数量和生成质量失控。

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
  -> Report Rendering
```

### 规划流程

1. 校验并标准化旅行请求，构造统一偏好和忌讳上下文。
2. 景点 Agent 调用景点 POI 工具扩展候选池，输出并验真 `selected_attractions`。
3. 天气 Agent 生成旅行日期内的天气建议和风险提醒。
4. 酒店 Agent 调用酒店工具生成候选池，并按节奏计算目标酒店数量。
5. Skeleton 阶段选择推荐酒店、每日住宿链 `daily_stays` 和每日景点分配 `daily_attraction_assignments`。
6. Day 阶段按天生成 `DayPlan`，只安排当天固定景点和早/中/晚餐饮意图。
7. 后端根据餐饮意图调用餐饮 POI 工具，找到真实餐厅则落地名称、地址和价格；找不到则保留区域餐饮建议。
8. 后端根据每日地点链注入详细交通路线和备选方案。
9. 后端刷新预算、数据来源、诊断信息、打包建议和风险提醒。
10. 前端渲染最终旅行计划报告。

### Agent 分工

| Agent | 输入 | 输出 | 关键约束 |
| --- | --- | --- | --- |
| `AttractionSearchAgent` | 旅行请求、偏好/忌讳、景点工具 | `AttractionResearch` | 景点必须来自工具候选池；不足时有限补搜 |
| `WeatherSearchAgent` | 城市、日期、约束 | `WeatherResearch` | 日期必须覆盖整个行程 |
| `HotelSearchAgent` | 预算、住宿风格、酒店轮换策略 | `HotelResearch` | 酒店必须来自工具候选池 |
| `ItineraryPlanningAgent` Skeleton | 已验真景点、酒店、天气、轮换策略 | 推荐酒店名、`daily_stays`、每日景点分配 | 只选白名单名称；住宿链必须连续 |
| `ItineraryPlanningAgent` Day | 单日固定酒店、固定景点、天气、约束 | `DayPlan`、`meal_intents` | 不新增景点/酒店；不编造餐厅地址；餐饮只输出意图 |
| 后端程序 | TripPlan 草案、餐饮意图、地点链 | 真实餐厅、交通路线、预算刷新 | 负责地图落地和一致性校验 |

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

#### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

#### 2. 准备配置

```powershell
copy .env.example .env
```

按需填写 `.env` 中的高德、天气和 LLM 配置。

#### 3. 启动服务

```powershell
python main.py
```

默认访问地址：

```text
http://127.0.0.1:8010
```

### 配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `Travel Assistant Agent` | 应用名称 |
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `8010` | 服务端口 |
| `AMAP_API_KEY` | 空 | 高德地图 API Key，用于 POI、地理编码和路线规划 |
| `QWEATHER_API_KEY` | 空 | 和风天气 API Key，用于城市天气预报 |
| `LLM_ENABLED` | `false` | 是否启用 LLM Agent 工作流 |
| `LLM_PROVIDER` | `deepseek` | LLM 提供商 |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_API_KEY` | 空 | LLM API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible API 地址 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_TIMEOUT_SECONDS` | `60` | 请求超时时间 |

### API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | 返回服务状态、LLM 状态和可用工具列表 |
| `POST` | `/api/plan` | 同步生成旅行计划 |
| `POST` | `/api/plan/tasks` | 创建异步旅行规划任务 |
| `GET` | `/api/plan/stream/{task_id}` | 通过 Server-Sent Events 返回规划进度和最终结果 |

### 请求模型概览

核心请求模型为 `TravelRequest`：

| 字段 | 说明 |
| --- | --- |
| `city` | 旅行城市 |
| `start_date` / `end_date` | 行程日期范围；前端建议 1-7 天 |
| `budget_min` / `budget_max` | 总预算范围 |
| `preferences` | 偏好标签，例如人文、艺术、自然、美食、购物、夜生活、亲子 |
| `extra_preferences` | 用户补充偏好 |
| `taboos` | 忌讳或不希望出现的安排 |
| `travelers` | 同行人数 |
| `pace` | 慢游、平衡或紧凑 |
| `hotel_style` | 经济、舒适或高档 |
| `transport_mode` | 公共交通、自驾、打车、混合出行或步行 |
| `transit_preference` | 公交路线偏好，例如推荐、少步行、地铁优先、公交优先 |

### 输出结果

规划结果使用 `TripPlan` 结构返回，包含：

- 行程主题与整体概览
- 景点、天气、酒店数据来源
- 已验真的景点池和酒店候选
- 推荐酒店与每日住宿 `daily_stays`
- 每日行程 `daily_plans`
- 餐饮意图落地后的真实餐厅或区域餐饮建议
- 交通路线、站点/道路明细和备选方案
- 酒店、景点、餐饮、交通、预备金和总预算
- 打包建议、风险提醒和 Agent 诊断信息

### 数据模式

- `live_amap`: 使用高德进行城市识别、POI 检索、逆地理编码和路线规划。
- `live_qweather`: 使用和风天气生成每日天气预报。
- `llm_generated`: 使用配置的 LLM 生成 Agent 研究和行程内容。
- `fallback`: 外部服务不可用或返回不稳定时使用本地样例、估算值或区域建议补足展示。

---

## English

Travel Assistant Agent is a city-trip planning application built with FastAPI, `hello-agents`, and MCP-style tool calling. It accepts a structured travel request and returns a grounded itinerary report with verified attractions, hotel stays, meal suggestions, weather notes, transport routes, and budget breakdowns.

The current version focuses on **agent planning with candidate verification**. Attraction and hotel names must come from tool-generated candidate pools. The final itinerary agent is split into a skeleton stage and a day-planning stage. The backend then grounds meal intents with restaurant POI search, injects transport routes, and refreshes the final budget.

### Key Features

- Structured trip request validation with Pydantic.
- Multi-agent workflow for attractions, weather, hotels, and itinerary planning.
- Candidate-pool grounding for attractions and hotels.
- Two-stage itinerary planning: skeleton planning first, day planning second.
- Meal-intent workflow: the model generates breakfast/lunch/dinner intents, while the backend searches real restaurants near hotels, attractions, or night areas.
- Hotel rotation policy: intense, balanced, and relaxed paces map to 1/2/3-night hotel rotation intervals.
- Attraction shortage recovery: limited repair rounds; if verified candidates are still insufficient, the system continues with the verified pool and lowers daily density.
- Route injection: backend computes detailed local transport routes, costs, durations, and alternatives.
- Budget refresh after meal grounding and route injection.
- Built-in browser UI with progress streaming and structured report rendering.
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
  -> Report Rendering
```

### Planning Flow

1. Validate and normalize the travel request.
2. Let the attraction agent search POIs, build a candidate pool, and output verified attractions.
3. Let the weather agent produce date-level weather suggestions and risk notes.
4. Let the hotel agent search verified hotel candidates based on budget, style, and rotation policy.
5. Let the skeleton stage choose the recommended hotel, daily hotel stays, and daily attraction assignments.
6. Let the day stage generate each day plan with fixed attractions and meal intents.
7. Ground meal intents through restaurant POI search; if no reliable restaurant is found, keep a regional meal suggestion without a fake address.
8. Inject transport routes for each daily location chain.
9. Refresh budget, data sources, diagnostics, packing tips, and risk notes.
10. Render the final report in the browser UI.

### Agent Responsibilities

| Agent | Input | Output | Constraints |
| --- | --- | --- | --- |
| `AttractionSearchAgent` | Travel request, constraints, attraction tools | `AttractionResearch` | Attractions must come from tool candidates |
| `WeatherSearchAgent` | City, dates, constraints | `WeatherResearch` | Forecast must cover the trip dates |
| `HotelSearchAgent` | Budget, hotel style, rotation policy | `HotelResearch` | Hotels must come from tool candidates |
| `ItineraryPlanningAgent` Skeleton | Verified attractions, hotels, weather, rotation policy | Recommended hotel name, `daily_stays`, daily attraction assignments | Copy names from whitelists; keep hotel stay chain continuous |
| `ItineraryPlanningAgent` Day | Fixed day hotels, fixed attractions, weather, constraints | `DayPlan`, `meal_intents` | Do not add attractions/hotels; do not invent restaurant addresses |
| Backend service | Draft plan, meal intents, location chain | Grounded meals, transport routes, refreshed budget | Handles map grounding and consistency checks |

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

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `APP_NAME` | `Travel Assistant Agent` | Application name |
| `HOST` | `127.0.0.1` | Server host |
| `PORT` | `8010` | Server port |
| `AMAP_API_KEY` | empty | AMap API key for POI, geocoding, and routing |
| `QWEATHER_API_KEY` | empty | QWeather API key |
| `LLM_ENABLED` | `false` | Whether to enable the LLM agent workflow |
| `LLM_PROVIDER` | `deepseek` | LLM provider |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `LLM_API_KEY` | empty | LLM API key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible API base URL |
| `LLM_TEMPERATURE` | `0.2` | Generation temperature |
| `LLM_TIMEOUT_SECONDS` | `60` | Request timeout |

### API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Service health, LLM status, and available tools |
| `POST` | `/api/plan` | Generate a trip plan synchronously |
| `POST` | `/api/plan/tasks` | Create an async planning task |
| `GET` | `/api/plan/stream/{task_id}` | Stream task progress and final result with Server-Sent Events |

### Output

The service returns a `TripPlan` containing:

- Trip theme and overview
- Data sources for attractions, weather, and hotels
- Verified attraction pool and hotel candidates
- Recommended hotel and daily stays
- Daily itinerary plans
- Grounded restaurant POIs or regional meal suggestions
- Transport routes, route details, and alternatives
- Budget breakdown
- Packing tips, risk alerts, and agent diagnostics
