from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.agents.base import BaseWorkflowAgent
from src.models import AttractionResearch, TravelRequest


class AttractionSearchAgent(BaseWorkflowAgent):
    name = "AttractionSearchAgent"
    system_prompt = (
        "你是旅行景点研究 Agent。你负责理解用户偏好和忌讳，自主决定要搜索哪些真实景点 POI，"
        "然后从 MCP 工具返回的候选中筛选景点。"
        "你必须使用工具获得候选，不要凭记忆编造景点、地址或坐标。"
        "你可以调用 get_city_profile(city) 和 search_attraction_pois(city, query, limit)。"
        "调用 search_attraction_pois 时，query 必须是一个具体中文搜索词，例如：滨水公园、博物馆、美食街、亲子乐园。"
        "不要把所有偏好一次性塞进 query。"
        "最多调用 search_attraction_pois 8 次；优先覆盖不同偏好主题，而不是反复搜索同一类词。"
        "最终 selected_attractions 只能来自工具返回的 candidates，必须复制 candidate_id、name、address、lat、lng。"
        "selected_attractions 里不要重复同一个景点；长天数旅行要尽量选择足够多的不重复景点。"
        "如果候选和用户忌讳冲突，必须拒绝并在 selection_reasoning 说明。"
        "返回严格 JSON。"
    )

    def research(self, request: TravelRequest) -> AttractionResearch:
        attractions_per_day = {"relaxed": 1, "balanced": 2, "intense": 3}.get(request.pace, 2)
        target_count = max(request.trip_days * attractions_per_day, 3)
        prompt = f"""
请为这次旅行做景点研究。

城市：{request.city}
旅行天数：{request.trip_days}
预算范围：{request.budget_min}-{request.budget_max}
同行人数：{request.travelers}
偏好：{", ".join(request.preferences) or "none"}
补充正向偏好：{request.extra_preferences or "none"}
真正忌讳/负向约束：{request.taboos or "none"}
节奏：{request.pace}
每日景点密度参考：{attractions_per_day} 个/天
目标不重复景点数：尽量接近 {target_count} 个

你可以调用：
1. get_city_profile(city="{request.city}")
2. search_attraction_pois(city="{request.city}", query="一个具体搜索词", limit=8)

工作要求：
- 先根据偏好、忌讳、人数、节奏设计搜索词。
- 偏好全选时，也要尽量覆盖多主题，不要只搜前一种偏好。
- 如果补充正向偏好里出现“爬山、徒步、山景、玩水、古镇”等具体兴趣，必须转成对应搜索词。
- 忌讳要分作用范围：例如“不吃辣”主要影响餐饮；“不想爬山”会影响景点。
- 对每个候选进行 Agent 打分，分数和理由由你判断。
- 只能选择工具返回过的候选；不要创造新景点。
- selected_attractions 不要重复同名景点。
- 如果旅行天数很多，优先扩大搜索主题覆盖，尽量给足不重复景点；候选不足时可以少选，并在 selection_reasoning 说明不足原因。
- 如果真实候选不足，可以少选，但不要幻想补齐。

返回 JSON：
{{
  "city_overview": "short summary",
  "search_plan": [
    {{
      "query": "string",
      "reason": "why this query matches the user"
    }}
  ],
  "preference_interpretation": {{
    "positive": ["string"],
    "negative": ["string"],
    "ambiguous": ["string"]
  }},
  "selected_attractions": [
    {{
      "candidate_id": "must copy from tool candidate",
      "source_query": "must copy from tool candidate",
      "score": 90,
      "matched_preferences": ["string"],
      "taboo_check": "string",
      "name": "string",
      "category": "string",
      "tags": ["string"],
      "summary": "string",
      "recommended_hours": 2.0,
      "ticket_price": 0.0,
      "best_time": "morning",
      "location": {{
        "name": "string",
        "address": "string",
        "lat": 0.0,
        "lng": 0.0
      }}
    }}
  ],
  "selection_reasoning": ["string"],
  "rejected_candidates": [
    {{
      "candidate_id": "string",
      "name": "string",
      "reason": "why rejected"
    }}
  ],
  "recommended_night_area": "string"
}}
"""
        data, diagnostics = self.runtime.run_json_with_trace(
            name=self.name,
            system_prompt=self.system_prompt,
            user_prompt=prompt,
            tool_registry=self.tool_registry,
            max_tool_iterations=8,
        )
        diagnostics.update(
            {
                "agent": self.name,
                "city": request.city,
                "trip_days": request.trip_days,
                "target_attraction_count": target_count,
                "stage": "attraction_agent",
            }
        )
        if data:
            diagnostics["json_keys"] = list(data.keys())
            diagnostics["raw_selected_count"] = len(data.get("selected_attractions") or [])
            try:
                data = self._drop_unverifiable_items(data, diagnostics)
                diagnostics["verified_selected_count"] = len(data.get("selected_attractions") or [])
                if data.get("selection_reasoning"):
                    data["selection_reasoning"] = list(data["selection_reasoning"]) + ["由 Agent 基于 MCP 结果整理。"]
                data["agent_diagnostics"] = diagnostics
                return AttractionResearch.model_validate(data)
            except ValidationError as exc:
                diagnostics["failure_reason"] = "attraction_research_schema_validation_failed"
                diagnostics["validation_errors"] = [
                    {
                        "loc": list(error.get("loc", [])),
                        "msg": error.get("msg", ""),
                        "type": error.get("type", ""),
                    }
                    for error in exc.errors()[:8]
                ]
            except Exception as exc:
                diagnostics["failure_reason"] = "attraction_agent_postprocess_exception"
                diagnostics["exception"] = f"{type(exc).__name__}: {exc}"
        else:
            diagnostics.setdefault("failure_reason", "llm_output_json_parse_failed")

        return AttractionResearch(
            city_overview=f"{request.city} 适合安排{request.pace}节奏的城市旅行。",
            selection_reasoning=[self._diagnostic_summary(diagnostics)],
            agent_diagnostics=diagnostics,
        )

    def _drop_unverifiable_items(self, data: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
        selected = data.get("selected_attractions")
        if not isinstance(selected, list):
            diagnostics["failure_reason"] = "selected_attractions_not_list"
            diagnostics["removed_unverifiable"] = []
            return data

        verified: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for item in selected:
            if not isinstance(item, dict):
                removed.append({"name": "非对象候选", "missing": ["item_object"]})
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            source_query = str(item.get("source_query", "")).strip()
            location = item.get("location") if isinstance(item.get("location"), dict) else {}
            lat = float(location.get("lat", 0) or 0)
            lng = float(location.get("lng", 0) or 0)
            name = str(item.get("name", "")).strip()
            missing = []
            if not candidate_id:
                missing.append("candidate_id")
            if not source_query:
                missing.append("source_query")
            if not name:
                missing.append("name")
            if not lat or not lng:
                missing.append("lat_lng")
            if candidate_id and source_query and name and lat and lng:
                verified.append(item)
            else:
                removed.append({"name": name or "未命名候选", "missing": missing})

        if removed:
            reasoning = list(data.get("selection_reasoning") or [])
            reasoning.append(
                "已移除无法验真的景点："
                + "、".join(item["name"] for item in removed[:5])
                + "。原因：缺少 candidate_id/source_query/坐标，不能证明来自 MCP 候选。"
            )
            data["selection_reasoning"] = reasoning
        diagnostics["removed_unverifiable"] = removed[:12]
        data["selected_attractions"] = verified
        return data

    def _diagnostic_summary(self, diagnostics: dict[str, Any]) -> str:
        reason = diagnostics.get("failure_reason") or "unknown_agent_failure"
        if reason == "llm_output_json_parse_failed":
            length = diagnostics.get("raw_output_length", 0)
            return f"景点 Agent 本轮未返回可解析 JSON，原始输出长度 {length}，已使用备用景点检索。"
        if reason == "attraction_research_schema_validation_failed":
            return "景点 Agent 返回了 JSON，但不符合 AttractionResearch 结构，已使用备用景点检索。"
        if reason == "selected_attractions_not_list":
            return "景点 Agent 返回的 selected_attractions 不是列表，已使用备用景点检索。"
        return f"景点 Agent 结果未通过后处理（{reason}），已使用备用景点检索。"
