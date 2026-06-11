from __future__ import annotations

from typing import Any

from src.agents.base import BaseWorkflowAgent
from src.models import TravelRequest


class WeatherSearchAgent(BaseWorkflowAgent):
    name = "WeatherSearchAgent"
    system_prompt = (
        "你是天气研究 Agent。"
        "你必须优先使用工具。"
        "调用天气工具时，只能使用参数名：city, start_date, end_date。"
        "你必须只输出一个 JSON 对象，不要输出 Markdown、代码块、解释文字或多余前后缀。"
        "字段名、字段层级和字段类型必须完全符合用户给出的模板，不能省略字段。"
    )

    def research(
        self,
        request: TravelRequest,
        *,
        constraint_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        prompt = self._build_prompt(request, constraint_context=constraint_context or {})
        data, diagnostics = self.run_json_with_trace(prompt, max_tool_iterations=3)
        diagnostics.update(
            {
                "agent": self.name,
                "city": request.city,
                "trip_days": request.trip_days,
                "stage": "weather_agent",
            }
        )
        if data:
            diagnostics["json_keys"] = list(data.keys())
            diagnostics["raw_forecast_count"] = len(data.get("forecast") or [])
        return data, diagnostics

    def repair(
        self,
        request: TravelRequest,
        *,
        errors: list[str],
        previous_data: dict[str, Any] | None,
        constraint_context: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        base_prompt = self._build_prompt(request, constraint_context=constraint_context)
        prompt = f"""
你上一次输出的天气研究 JSON 没有通过校验，需要重新生成。

校验错误：
{self._json(errors)}

上一次输出的 JSON：
{self._json(previous_data or {})}

返工要求：
- forecast 必须覆盖旅行的每一天，从 {request.start_date.isoformat()} 到 {request.end_date.isoformat()}。
- high_c 必须大于或等于 low_c。
- suggestion 要结合用户约束，例如怕晒、带老人、少走路、户外偏好等。
- 只输出一个 JSON 对象，不要 Markdown，不要解释。

原始任务和 JSON 模板如下：
{base_prompt}
"""
        data, diagnostics = self.run_json_with_trace(prompt, max_tool_iterations=3)
        diagnostics.update(
            {
                "agent": self.name,
                "city": request.city,
                "trip_days": request.trip_days,
                "stage": "weather_agent_repair",
                "repair_errors": errors[:12],
            }
        )
        if data:
            diagnostics["json_keys"] = list(data.keys())
            diagnostics["raw_forecast_count"] = len(data.get("forecast") or [])
        return data, diagnostics

    def _build_prompt(self, request: TravelRequest, *, constraint_context: dict[str, Any]) -> str:
        return f"""
请研究这次旅行的天气情况。

城市：{request.city}
开始日期：{request.start_date.isoformat()}
结束日期：{request.end_date.isoformat()}
旅行天数：{request.trip_days}

用户统一约束上下文：
{self._json(constraint_context)}

请调用：
travel_get_weather_forecast(
  city="{request.city}",
  start_date="{request.start_date.isoformat()}",
  end_date="{request.end_date.isoformat()}"
)

严格 JSON 输出规则：
- 只能输出一个 JSON 对象。
- 不要输出 Markdown、```json 代码块、解释文字或前后缀。
- 字段名必须完全一致，不能省略字段。
- forecast 必须覆盖旅行的每一天。
- 未知字符串填 ""，未知数字填 0，未知数组填 []。

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

    def _json(self, value: Any) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
