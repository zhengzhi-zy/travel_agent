from __future__ import annotations

from src.agents.base import BaseWorkflowAgent
from src.models import TravelRequest, WeatherResearch


class WeatherSearchAgent(BaseWorkflowAgent):
    name = "WeatherSearchAgent"
    system_prompt = (
        "你是天气研究 Agent。"
        "你必须优先使用工具。"
        "调用天气工具时，只能使用参数名：city, start_date, end_date。"
        "返回严格 JSON。"
    )

    def research(self, request: TravelRequest) -> WeatherResearch:
        prompt = f"""
请研究这次旅行的天气情况。

城市：{request.city}
开始日期：{request.start_date.isoformat()}
结束日期：{request.end_date.isoformat()}

请调用：
get_weather_forecast(
  city="{request.city}",
  start_date="{request.start_date.isoformat()}",
  end_date="{request.end_date.isoformat()}"
)

返回 JSON：
{{
  "forecast": [
    {{
      "date": "{request.start_date.isoformat()}",
      "condition": "sunny",
      "high_c": 28,
      "low_c": 21,
      "suggestion": "string"
    }}
  ],
  "overall_summary": "string",
  "risk_days": ["YYYY-MM-DD reason"]
}}
"""
        data = self.run_json(prompt, max_tool_iterations=3)
        if data:
            try:
                summary = str(data.get("overall_summary") or "")
                data["overall_summary"] = (summary + " 由 Agent 基于天气工具结果整理。").strip()
                return WeatherResearch.model_validate(data)
            except Exception:
                pass

        return WeatherResearch(overall_summary="LLM 不可用或返回 JSON 非法，已使用兜底天气研究结果。")
