# Travel Assistant Agent

智能旅行规划助手，基于 FastAPI、`hello-agents`、本地 MCP 旅行工具服务和多 Agent 工作流构建。用户填写目的地、日期、预算、偏好、忌讳、出行人数和交通方式后，系统会生成包含景点、天气、酒店、路线、预算、打包建议和风险提醒的旅行计划。

English version is available below.

## 功能特点

- 结构化旅行表单：城市、日期范围、预算、偏好、忌讳、人数、节奏、酒店风格和交通方式。
- 多 Agent 规划流程：景点搜索、天气查询、酒店推荐、餐饮候选和行程编排。
- 支持 MCP 旅行工具：通过本地 MCP 服务为 Agent 提供景点、路线、酒店等工具能力。
- 支持高德地图数据：配置 `AMAP_API_KEY` 后，可使用真实 POI 和路线信息。
- 支持和风天气数据：配置 `QWEATHER_API_KEY` 后，可使用真实天气预报。
- 支持 LLM 增强规划：配置 `LLM_ENABLED=true` 和 `LLM_API_KEY` 后，可启用模型辅助的规划结果。
- 离线兜底模式：未配置 API Key 时，仍可基于本地逻辑生成演示行程。
- 前端页面直接可用：FastAPI 启动后访问本地地址即可填写表单并查看结果。

## 技术栈

- Python
- FastAPI
- Uvicorn
- Pydantic
- python-dotenv
- hello-agents
- fastmcp
- 高德地图 API，可选
- 和风天气 API，可选
- DeepSeek 或 OpenAI-compatible LLM，可选

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
    ├── mcp/
    ├── services/
    └── utils/
```

## 快速开始

### 1. 克隆或进入项目目录

```powershell
cd D:\PyCharmMiscProject\travel_assistant_agent
```

### 2. 创建并启用虚拟环境

如果你已经有 `.venv`，可以直接启用：

```powershell
.\.venv\Scripts\activate
```

如果还没有虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. 安装依赖

```powershell
pip install -r requirements.txt
```

### 4. 创建本地环境变量文件

```powershell
copy .env.example .env
```

然后编辑 `.env`，按需填写 API Key。

注意：`.env` 包含本地密钥，不应该上传到 GitHub。项目中的 `.gitignore` 已经忽略 `.env`。

### 5. 启动项目

```powershell
python main.py
```

浏览器打开：

```text
http://127.0.0.1:8010
```

## 环境变量说明

| 变量名 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `APP_NAME` | 否 | `Travel Assistant Agent` | 应用名称 |
| `HOST` | 否 | `127.0.0.1` | 服务监听地址 |
| `PORT` | 否 | `8010` | 服务端口 |
| `AMAP_API_KEY` | 否 | 空 | 高德地图 API Key，用于真实 POI 和路线查询 |
| `QWEATHER_API_KEY` | 否 | 空 | 和风天气 API Key，用于真实天气预报 |
| `LLM_ENABLED` | 否 | `false` | 是否启用 LLM 增强规划 |
| `LLM_PROVIDER` | 否 | `deepseek` | LLM 服务提供商 |
| `LLM_MODEL` | 否 | `deepseek-chat` | 模型名称 |
| `LLM_API_KEY` | 否 | 空 | LLM API Key |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` | OpenAI-compatible API 地址 |
| `LLM_TEMPERATURE` | 否 | `0.2` | 模型温度 |
| `LLM_TIMEOUT_SECONDS` | 否 | `60` | 模型请求超时时间 |

## `.env` 和 `.env.example`

本项目使用 `.env.example` 作为配置模板，使用 `.env` 保存本地真实配置。

- `.env.example` 应该上传到 GitHub，方便别人知道需要哪些配置项。
- `.env` 不应该上传到 GitHub，因为里面可能包含 API Key。
- 新用户可以运行 `copy .env.example .env` 创建自己的本地配置文件。

你可以用下面命令确认 `.env` 是否被 Git 忽略：

```powershell
git check-ignore -v .env
```

如果看到 `.gitignore` 的匹配结果，就说明 `.env` 不会被上传。

## API 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 查看服务健康状态和可用工具 |
| `POST` | `/api/plan` | 同步生成旅行计划 |
| `POST` | `/api/plan/tasks` | 创建异步规划任务 |
| `GET` | `/api/plan/stream/{task_id}` | 通过 SSE 获取规划进度和结果 |

## 上传到 GitHub

第一次上传：

```powershell
git init
git check-ignore -v .env
git status
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/your-username/travel_assistant_agent.git
git push -u origin main
```

后续更新：

```powershell
git add .
git commit -m "Update project"
git push
```

## 注意事项

- 如果没有配置高德地图或和风天气 API Key，项目会使用兜底数据生成演示计划。
- 如果没有启用 LLM，项目仍然可以运行，但规划结果会更偏规则化。
- 酒店价格和餐饮价格可能是估算值，真实预订价格请以平台页面为准。
- 不要提交 `.env`、`.venv/`、`.idea/`、`data/` 等本地文件或目录。

---

# Travel Assistant Agent

An intelligent travel planning assistant built with FastAPI, `hello-agents`, a local MCP travel tool server, and a multi-agent planning workflow. After users submit destination, travel dates, budget, preferences, taboos, traveler count, and transportation style, the app generates a structured trip plan with attractions, weather, hotel suggestions, routes, budget breakdown, packing tips, and risk alerts.

## Features

- Structured travel form for city, dates, budget, preferences, taboos, traveler count, pace, hotel style, and transportation mode.
- Multi-agent workflow for attraction research, weather research, hotel recommendation, dining candidates, and itinerary planning.
- MCP-powered travel tools exposed through a local MCP server.
- Live AMap integration when `AMAP_API_KEY` is configured.
- Live QWeather forecast when `QWEATHER_API_KEY` is configured.
- Optional LLM-enhanced planning when `LLM_ENABLED=true` and `LLM_API_KEY` are configured.
- Offline fallback mode when external API keys are not provided.
- Ready-to-use local frontend served by FastAPI.

## Tech Stack

- Python
- FastAPI
- Uvicorn
- Pydantic
- python-dotenv
- hello-agents
- fastmcp
- AMap API, optional
- QWeather API, optional
- DeepSeek or OpenAI-compatible LLM, optional

## Project Structure

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
    ├── mcp/
    ├── services/
    └── utils/
```

## Quick Start

### 1. Enter the project directory

```powershell
cd D:\PyCharmMiscProject\travel_assistant_agent
```

### 2. Create and activate a virtual environment

If `.venv` already exists:

```powershell
.\.venv\Scripts\activate
```

If you need to create one:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Create the local environment file

```powershell
copy .env.example .env
```

Then edit `.env` and fill in the API keys you want to use.

Note: `.env` may contain private keys and should not be uploaded to GitHub. It is already ignored by `.gitignore`.

### 5. Run the app

```powershell
python main.py
```

Open:

```text
http://127.0.0.1:8010
```

## Environment Variables

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `APP_NAME` | No | `Travel Assistant Agent` | Application name |
| `HOST` | No | `127.0.0.1` | Server host |
| `PORT` | No | `8010` | Server port |
| `AMAP_API_KEY` | No | Empty | AMap API key for live POI and route lookup |
| `QWEATHER_API_KEY` | No | Empty | QWeather API key for live forecasts |
| `LLM_ENABLED` | No | `false` | Enable or disable LLM-enhanced planning |
| `LLM_PROVIDER` | No | `deepseek` | LLM provider |
| `LLM_MODEL` | No | `deepseek-chat` | Model name |
| `LLM_API_KEY` | No | Empty | LLM API key |
| `LLM_BASE_URL` | No | `https://api.deepseek.com/v1` | OpenAI-compatible API base URL |
| `LLM_TEMPERATURE` | No | `0.2` | Model temperature |
| `LLM_TIMEOUT_SECONDS` | No | `60` | Model request timeout |

## `.env` and `.env.example`

This project uses `.env.example` as a public configuration template and `.env` as your private local configuration file.

- `.env.example` should be committed to GitHub so other users know which variables are needed.
- `.env` should not be committed because it may contain API keys.
- New users can run `copy .env.example .env` to create their local config.

Check whether `.env` is ignored by Git:

```powershell
git check-ignore -v .env
```

If Git prints a matching `.gitignore` rule, `.env` will not be uploaded.

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Check service health and available tools |
| `POST` | `/api/plan` | Generate a trip plan synchronously |
| `POST` | `/api/plan/tasks` | Create an asynchronous planning task |
| `GET` | `/api/plan/stream/{task_id}` | Stream planning progress and result with SSE |

## Upload to GitHub

First upload:

```powershell
git init
git check-ignore -v .env
git status
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/your-username/travel_assistant_agent.git
git push -u origin main
```

Future updates:

```powershell
git add .
git commit -m "Update project"
git push
```

## Notes

- Without AMap or QWeather API keys, the app uses fallback data for demo planning.
- Without LLM enabled, the app still works, but the result will be more rule-based.
- Hotel and restaurant prices may be estimates. Always check the final booking platform for real prices.
- Do not commit `.env`, `.venv/`, `.idea/`, `data/`, or other local-only files.
