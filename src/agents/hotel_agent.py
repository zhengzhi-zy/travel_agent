from __future__ import annotations

from src.agents.base import BaseWorkflowAgent
from src.models import HotelResearch, TravelRequest


class HotelSearchAgent(BaseWorkflowAgent):
    name = "HotelSearchAgent"
    system_prompt = (
        "你是酒店研究 Agent。"
        "你必须优先使用工具，不要猜测工具参数名。"
        "调用酒店工具时，只能使用这些参数名："
        "city, budget_min, budget_max, travelers, stay_nights, hotel_style。"
        "不要使用 total_budget、stay_length、style 之类的别名，除非工具明确要求。"
        "返回严格 JSON。"
    )

    def research(self, request: TravelRequest) -> HotelResearch:
        prompt = f"""
请研究这次旅行的酒店候选。

城市：{request.city}
预算范围：{request.budget_min}-{request.budget_max}
同行人数：{request.travelers}
住宿晚数：{request.stay_nights}
住宿偏好：{request.hotel_style}
节奏：{request.pace}

请调用：
search_hotels(
  city="{request.city}",
  budget_min={request.budget_min},
  budget_max={request.budget_max},
  travelers={request.travelers},
  stay_nights={request.stay_nights},
  hotel_style="{request.hotel_style}"
)

注意：
- 参数名必须完全匹配工具 schema
- 不要传 total_budget
- 不要传 stay_length
- 不要传 style

返回 JSON：
{{
  "candidates": [
    {{
      "name": "string",
      "style": "comfort",
      "star_level": 4,
      "nightly_price": 480,
      "summary": "string",
      "nearby_area": "string",
      "location": {{
        "name": "string",
        "address": "string",
        "lat": 0.0,
        "lng": 0.0
      }}
    }}
  ],
  "recommended_hotel": {{
    "name": "string",
    "style": "comfort",
    "star_level": 4,
    "nightly_price": 480,
    "summary": "string",
    "nearby_area": "string",
    "location": {{
      "name": "string",
      "address": "string",
      "lat": 0.0,
      "lng": 0.0
    }}
  }},
  "selection_reasoning": ["string"]
}}
"""
        data = self.run_json(prompt, max_tool_iterations=3)
        if data:
            try:
                if data.get("selection_reasoning"):
                    data["selection_reasoning"] = list(data["selection_reasoning"]) + ["由 Agent 基于酒店工具结果整理。"]
                return HotelResearch.model_validate(data)
            except Exception:
                pass

        return HotelResearch(selection_reasoning=["LLM 不可用或返回 JSON 非法，已使用兜底酒店研究结果。"])
