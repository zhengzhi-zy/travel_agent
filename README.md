# Travel Assistant Agent

A chapter-13 style intelligent travel assistant built with `hello_agents`, FastAPI, a local MCP travel server, and a structured multi-agent planning workflow.

## Features

- Structured travel form with date range, city, budget, preferences, taboos, and traveler count
- Multi-agent pipeline for attraction search, weather research, hotel recommendation, and itinerary planning
- MCP-based travel tools exposed to agents through `hello_agents.tools.MCPTool`
- Live AMap POI and route lookup when `AMAP_API_KEY` is configured
- Live QWeather forecast when `QWEATHER_API_KEY` is configured
- Hotel candidate search from POI results plus estimated nightly pricing and OTA search links
- Fallback planning path when no API keys or LLM key are configured
- Travel result includes daily schedule, hotel recommendation, budget breakdown, packing tips, and risk alerts

## Architecture

```text
Frontend Form
  -> FastAPI /api/plan
  -> AttractionSearchAgent
  -> WeatherSearchAgent
  -> HotelSearchAgent
  -> ItineraryPlanningAgent
  -> MCP Travel Tools
  -> TripPlan JSON
  -> Frontend Rendering
```

## Run

```powershell
cd "D:\PyCharmMiscProject\travel_assistant_agent"
D:\python02\python.exe -m pip install -r requirements.txt
copy .env.example .env
D:\python02\python.exe main.py
```

Open:

```text
http://127.0.0.1:8010
```

## Optional Live API Setup

Add keys in `.env`:

```env
AMAP_API_KEY=your-amap-key
QWEATHER_API_KEY=your-qweather-key
```

## Notes

- Without live keys, the app falls back to local sample travel data.
- With live keys, city lookup, attraction search, route estimation, and weather forecast prefer real external APIs.
- Hotel price is still an estimate derived from POI candidates and budget constraints. The booking link points to an OTA search page rather than a direct booking API response.
