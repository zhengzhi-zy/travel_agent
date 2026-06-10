from __future__ import annotations

from datetime import timedelta
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from hello_agents.tools import MCPTool
from hello_agents.tools.registry import ToolRegistry

from src.agents import AttractionSearchAgent, HotelSearchAgent, ItineraryPlanningAgent, WeatherSearchAgent
from src.config import get_settings
from src.llm import HelloAgentRuntime
from src.mcp.travel_backend import PREFERENCE_LABELS, TravelDataBackend
from src.mcp.travel_server import build_travel_mcp_server
from src.models import (
    Attraction,
    AttractionResearch,
    BudgetBreakdown,
    DayPlan,
    DayPlanItem,
    DayMealResearch,
    HealthResponse,
    HotelOption,
    HotelResearch,
    MealResearch,
    RestaurantOption,
    RouteDetailSegment,
    RoutePlan,
    TravelRequest,
    TripPlan,
    WeatherInfo,
    WeatherResearch,
)
from src.utils.json_utils import extract_json_object

# 生成初始化函数，不允许更改
@dataclass(frozen=True)
class RouteTarget:
    name: str
    address: str = ""
    lat: float = 0.0
    lng: float = 0.0


class QuotaToolWrapper:
    '''包装一个工具，限制它一轮最多调用多少次'''
    def __init__(
        self,
        tool: Any,
        *,  # 关键字传参，不能随便按位置传。
        max_calls: int,
        duplicate_key_params: tuple[str, ...],  # 用哪些参数判断是否重复
    ) -> None:
        self._tool = tool
        self.name = tool.name
        self.description = (
            f"{tool.description} 调用限制：本轮最多 {max_calls} 次；重复查询会返回缓存/拒绝提示。"
        )
        self._max_calls = max_calls
        self._duplicate_key_params = duplicate_key_params
        self._calls = 0  # 记录本轮已经调用了多少次
        self._seen_keys: set[tuple[str, ...]] = set()  # 已经查过的key
        self._candidate_pool: list[dict[str, Any]] = []  # 候选池

    def reset_quota(self) -> None:
        '''重置函数：每次新生成一份旅游计划前，把上一轮状态情掉'''
        self._calls = 0
        self._seen_keys.clear()
        self._candidate_pool.clear()

    def candidate_pool(self) -> list[dict[str, Any]]:
        '''把当前候选池拿出去'''
        # 这里返回的是候选池的复制切片，外部拿到候选池之后，就不会更改内部候选池的信息
        return self._candidate_pool[:]

    # agent调用工具，最终会进入这里的方法
    def run(self, parameters: dict[str, Any]) -> str:
        normalized = self._normalize_parameters(parameters)  # 标准化参数
        # 根据指定参数生成查重key
        key = tuple(str(normalized.get(name, "")).strip().lower() for name in self._duplicate_key_params)
        # 判断这次查询是否重复
        if key and key in self._seen_keys:
            return (
                '{"quota_error": true, "reason": "duplicate_query", '
                '"message": "这个高德景点查询已经调用过，请使用已有候选或换一个不同主题的关键词。"}'
            )
        # 判断调用次数是否超过限制
        if self._calls >= self._max_calls:
            return (
                '{"quota_error": true, "reason": "tool_call_limit_exceeded", '
                '"message": "本轮景点 POI 查询次数已达上限，请从已有候选中筛选，不要继续调用。"}'
            )
        self._calls += 1
        # 把这次记录保存
        if key:
            self._seen_keys.add(key)
        # 进入 原始工具
        result = self._tool.run(parameters)
        # 工具返回结果后，把里面的candidates记录到候选池里，方便后续的验真
        self._record_candidates(result)
        return result

    def get_parameters(self) -> Any:
        return self._tool.get_parameters()

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        return self._tool.validate_parameters(parameters)

    def to_dict(self) -> dict[str, Any]:
        data = self._tool.to_dict()
        data["description"] = self.description  # 把描述信息替换成包装器自己的描述
        return data

    def _normalize_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if "input" in parameters and isinstance(parameters["input"], dict):
            return parameters["input"]
        return parameters

    def _record_candidates(self, result: str) -> None:
        '''从工具返回结果里提取 candidates，并保存到 _candidate_pool。'''
        data = extract_json_object(result)
        if not data:
            return
        seen = {
            str(item.get("candidate_id") or item.get("name") or "").strip()
            for item in self._candidate_pool
            if isinstance(item, dict)
        }
        # 用于名字去重
        seen_names = {
            str(item.get("name") or "").strip()
            for item in self._candidate_pool
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        for item in data.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("candidate_id") or item.get("name") or "").strip()
            name = str(item.get("name") or "").strip()
            # 去重判断
            if not key or key in seen or (name and name in seen_names):
                continue
            # 记录新的key
            seen.add(key)
            if name:
                seen_names.add(name)
            self._candidate_pool.append(item)


class TravelPlannerService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.runtime = HelloAgentRuntime(self.settings.llm)
        self.backend = TravelDataBackend(
            amap_key=self.settings.amap_key,
            qweather_key=self.settings.qweather_key,
        )
        self.tool_registry = ToolRegistry()
        self.attraction_tool_registry = ToolRegistry()
        self._attraction_quota_tools: list[QuotaToolWrapper] = []
        self.mcp_tool = MCPTool(name="travel", server=build_travel_mcp_server(self.backend), auto_expand=True)
        self._register_expanded_tools()

        self.attraction_agent = AttractionSearchAgent(self.runtime, self.attraction_tool_registry)
        self.weather_agent = WeatherSearchAgent(self.runtime, self.tool_registry)
        self.hotel_agent = HotelSearchAgent(self.runtime, self.tool_registry)
        self.itinerary_agent = ItineraryPlanningAgent(self.runtime, self.tool_registry)
        self._request_transit_preference = "recommended"

    def health(self) -> HealthResponse:
        return HealthResponse(
            status="ok",
            llm_enabled=self.runtime.available,
            provider=self.runtime.provider_label,
            hello_agents_load_error=self.runtime.load_error,
            available_tools=self.tool_registry.list_tools(),
        )

    def build_trip_plan(
        self,
        request: TravelRequest,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> TripPlan:
        self._emit_progress(
            progress_callback,
            stage="validate",
            percent=8,
            title="校验旅行需求",
            detail="正在检查城市、日期、预算、人数和出行方式。",
        )
        normalized_city = self._normalize_city_input(request.city)
        if normalized_city is None:
            raise ValueError("城市名称编码异常，请重新输入清晰的中文或英文城市名，例如：广州 / Beijing。")

        request = request.model_copy(update={"city": normalized_city})
        request = self._normalize_preference_inputs(request)
        if not self.backend.is_supported_city(request.city):
            raise ValueError(
                f"暂不支持城市“{request.city}”的自动规划：它既不在内置城市列表中，也无法通过地图服务识别。"
            )

        self._request_transit_preference = request.transit_preference
        attraction_agent_diagnostics: dict[str, Any] = {}

        self._emit_progress(
            progress_callback,
            stage="attraction_profile",
            percent=15,
            title="准备景点候选",
            detail="正在读取城市画像和可用景点基础数据。",
        )
        attraction_research = self._attraction_profile_research(request)
        attraction_source = self._source_from_attraction_research(attraction_research)
        if self.runtime.available:
            self._emit_progress(
                progress_callback,
                stage="attraction_agent",
                percent=24,
                title="景点 Agent 筛选",
                detail="AttractionSearchAgent 正在理解偏好和忌讳，并调用高德 POI 工具。",
            )
            self._reset_attraction_tool_quotas()
            agent_attractions = self.attraction_agent.research(request)
            candidate_pool = self._attraction_candidate_pool()
            attraction_agent_diagnostics = dict(agent_attractions.agent_diagnostics or {})
            attraction_agent_diagnostics["candidate_pool_size"] = len(candidate_pool)
            grounded_attractions = self._ground_agent_attraction_research(
                agent_attractions,
                attraction_research,
                candidate_pool,
            )
            if grounded_attractions is not None:
                attraction_research = grounded_attractions
                attraction_agent_diagnostics = dict(attraction_research.agent_diagnostics or attraction_agent_diagnostics)
                attraction_source = self._source_from_attraction_research(attraction_research)
            else:
                attraction_agent_diagnostics.setdefault("failure_reason", "agent_grounding_failed")
                attraction_agent_diagnostics.setdefault(
                    "grounding_summary",
                    "景点 Agent 没有留下可用的、可在 MCP 候选池中验真的景点。",
                )
        if not attraction_research.selected_attractions:
            attraction_research = self._fallback_attraction_research(request, attraction_agent_diagnostics)
            attraction_source = self._source_from_attraction_research(attraction_research)

        self._emit_progress(
            progress_callback,
            stage="weather",
            percent=36,
            title="天气 Agent 研究",
            detail="正在整理天气、温度和出行风险提醒。",
        )
        weather_research = self._fallback_weather_research(request)
        weather_source = self._source_from_weather_research(weather_research)
        if self.runtime.available:
            agent_weather = self.weather_agent.research(request)
            if agent_weather.forecast:
                weather_research = agent_weather
                weather_source = self._source_from_weather_research(weather_research)

        self._emit_progress(
            progress_callback,
            stage="hotel",
            percent=48,
            title="酒店 Agent 筛选",
            detail="正在按预算、人数、住宿风格和路线位置筛选酒店候选。",
        )
        fallback_hotel_research = self._fallback_hotel_research(request)
        hotel_research = fallback_hotel_research
        hotel_source = self._source_from_hotel_research(hotel_research)
        if self.runtime.available:
            agent_hotels = self.hotel_agent.research(request)
            grounded_hotels = self._ground_hotel_research(agent_hotels, fallback_hotel_research)
            if grounded_hotels is not None:
                hotel_research = grounded_hotels
                hotel_source = self._source_from_hotel_research(hotel_research)

        self._emit_progress(
            progress_callback,
            stage="meal",
            percent=58,
            title="餐饮候选检索",
            detail="正在按每日景点、酒店和夜生活区域检索真实餐饮候选。",
        )
        restaurant_catalog = self._build_restaurant_catalog(
            request=request,
            attractions=attraction_research,
            hotels=hotel_research,
        )
        meal_research = self._build_meal_research(
            request=request,
            attractions=attraction_research,
            hotels=hotel_research,
            restaurant_catalog=restaurant_catalog,
        )

        self._emit_progress(
            progress_callback,
            stage="itinerary",
            percent=70,
            title="行程 Agent 编排",
            detail="正在把景点、酒店、餐饮和天气组合成每日行程。",
        )
        llm_plan = self.itinerary_agent.plan(
            request,
            attraction_research,
            weather_research,
            hotel_research,
            meal_research,
        )
        if llm_plan is not None:
            llm_plan = self._ground_trip_plan(
                llm_plan,
                attraction_research,
                hotel_research,
                restaurant_catalog,
            )
        if llm_plan is not None:
            llm_plan.planning_source = "llm_generated"
            llm_plan.attraction_data_source = attraction_source
            llm_plan.weather_data_source = weather_source
            llm_plan.hotel_data_source = hotel_source
            llm_plan.attraction_search_plan = attraction_research.search_plan
            llm_plan.preference_interpretation = attraction_research.preference_interpretation
            llm_plan.agent_diagnostics = attraction_research.agent_diagnostics
            self._emit_progress(
                progress_callback,
                stage="route",
                percent=84,
                title="高德路线规划",
                detail="正在为每日地点链计算详细交通路线和备选方案。",
            )
            self._inject_transport_details(
                llm_plan,
                request,
                attraction_research,
                hotel_research,
                restaurant_catalog,
                hotel_research.recommended_hotel or (hotel_research.candidates[0] if hotel_research.candidates else None),
                attraction_research.recommended_night_area,
            )
            self._emit_progress(
                progress_callback,
                stage="finalize",
                percent=96,
                title="整理可视化报告",
                detail="正在汇总预算、风险、搜索计划和详细路径。",
            )
            return llm_plan

        self._emit_progress(
            progress_callback,
            stage="program_plan",
            percent=78,
            title="程序组装行程",
            detail="LLM 行程不可用时，正在用已校验的候选数据组装稳定计划。",
        )
        plan = self._build_programmatic_plan(
            request=request,
            attractions=attraction_research,
            weather=weather_research,
            hotels=hotel_research,
            restaurant_catalog=restaurant_catalog,
            attraction_source=attraction_source,
            weather_source=weather_source,
            hotel_source=hotel_source,
        )
        self._emit_progress(
            progress_callback,
            stage="finalize",
            percent=96,
            title="整理可视化报告",
            detail="正在汇总预算、风险、搜索计划和详细路径。",
        )
        return plan

    def _emit_progress(
        self,
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        stage: str,
        percent: int,
        title: str,
        detail: str,
    ) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(
                {
                    "stage": stage,
                    "percent": percent,
                    "title": title,
                    "detail": detail,
                }
            )
        except Exception:
            return

    def _register_expanded_tools(self) -> None:
        for tool in self.mcp_tool.get_expanded_tools():
            self.tool_registry.register_tool(tool)
            if tool.name == "travel_search_attraction_pois":
                quota_tool = QuotaToolWrapper(
                    tool,
                    max_calls=8,
                    duplicate_key_params=("city", "query"),
                )
                self._attraction_quota_tools.append(quota_tool)
                self.attraction_tool_registry.register_tool(quota_tool)
            elif tool.name == "travel_get_city_profile":
                self.attraction_tool_registry.register_tool(tool)

    def _reset_attraction_tool_quotas(self) -> None:
        for tool in self._attraction_quota_tools:
            tool.reset_quota()

    def _attraction_candidate_pool(self) -> list[dict[str, Any]]:
        pool: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tool in self._attraction_quota_tools:
            for item in tool.candidate_pool():
                key = str(item.get("candidate_id") or item.get("name") or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    pool.append(item)
        return pool

    def _attraction_profile_research(self, request: TravelRequest) -> AttractionResearch:
        profile = self.backend.get_city_profile(request.city)
        return AttractionResearch(
            city_overview=profile["profile"],
            selected_attractions=[],
            selection_reasoning=[
                "LLM 可用时，景点搜索由 AttractionSearchAgent 调用 MCP 工具完成；程序这里只准备城市概况。",
            ],
            recommended_night_area=profile["night_area"],
            preference_interpretation={
                "extra_preferences": request.extra_preferences,
                "taboos": request.taboos,
            },
        )

    def _normalize_preference_inputs(self, request: TravelRequest) -> TravelRequest:
        positive_parts = self._split_user_intent_text(request.extra_preferences)
        taboo_positive_parts: list[str] = []
        true_taboo_parts: list[str] = []
        ambiguous_parts: list[str] = []

        for part in self._split_user_intent_text(request.taboos):
            polarity = self._intent_polarity(part)
            if polarity == "positive":
                taboo_positive_parts.append(part)
            elif polarity == "negative":
                true_taboo_parts.append(part)
            else:
                ambiguous_parts.append(part)

        merged_positive = self._join_unique_text_parts(positive_parts + taboo_positive_parts)
        merged_taboos = self._join_unique_text_parts(true_taboo_parts + ambiguous_parts)
        if merged_positive != request.extra_preferences or merged_taboos != request.taboos:
            return request.model_copy(
                update={
                    "extra_preferences": merged_positive,
                    "taboos": merged_taboos,
                }
            )
        return request

    def _split_user_intent_text(self, text: str) -> list[str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []
        for sep in ["，", "、", ";", "；", "\n", "|"]:
            cleaned = cleaned.replace(sep, ",")
        return [part.strip() for part in cleaned.split(",") if part.strip()]

    def _intent_polarity(self, text: str) -> str:
        lowered = text.strip().lower()
        negative_markers = [
            "不想",
            "不要",
            "不去",
            "不吃",
            "不喜欢",
            "讨厌",
            "忌讳",
            "避开",
            "避免",
            "不能",
            "拒绝",
            "少点",
            "少去",
            "no ",
            "avoid",
            "hate",
            "dislike",
        ]
        positive_markers = [
            "喜欢",
            "想去",
            "想玩",
            "希望",
            "偏好",
            "爱",
            "要去",
            "想看",
            "想体验",
            "prefer",
            "like",
            "want",
        ]
        if any(marker in lowered for marker in negative_markers):
            return "negative"
        if any(marker in lowered for marker in positive_markers):
            return "positive"
        return "ambiguous"

    def _join_unique_text_parts(self, parts: list[str]) -> str:
        seen: set[str] = set()
        result: list[str] = []
        for part in parts:
            cleaned = part.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return "，".join(result)

    def _fallback_attraction_research(
        self,
        request: TravelRequest,
        agent_diagnostics: dict[str, Any] | None = None,
    ) -> AttractionResearch:
        diagnostics = dict(agent_diagnostics or {})
        diagnostics["fallback_used"] = True
        diagnostics.setdefault("failure_reason", "attraction_agent_unavailable_or_unverified")
        profile = self.backend.get_city_profile(request.city)
        attraction_data = self.backend.search_attractions(
            request.city,
            ",".join(request.preferences),
            request.travelers,
            request.budget_max / max(request.trip_days, 1),
            target_count=self._target_attraction_count(request),
        )
        selected = [Attraction.model_validate(item) for item in attraction_data["attractions"]]
        labels = [PREFERENCE_LABELS.get(pref, pref) for pref in request.preferences]
        source = "高德实时 POI" if attraction_data.get("data_mode") == "live" else "本地兜底样例"
        diagnostics["fallback_data_mode"] = attraction_data.get("data_mode", "")
        diagnostics["fallback_selected_count"] = len(selected)
        return AttractionResearch(
            city_overview=profile["profile"],
            selected_attractions=selected,
            selection_reasoning=[
                self._format_attraction_agent_diagnostic(diagnostics),
                f"数据来源：{source}。",
                f"已根据偏好匹配 {self._human_labels(labels) or '城市通用观光'}。",
                f"景点成本控制在总预算 {request.budget_min}-{request.budget_max} 范围内。",
            ],
            recommended_night_area=profile["night_area"],
            search_plan=[
                {
                    "query": self._human_labels(labels) or "城市通用观光",
                    "reason": "LLM 景点 Agent 未产出可验真结果时使用的备用景点检索。",
                }
            ],
            preference_interpretation={
                "positive": [self._human_labels(labels)] if labels else [],
                "extra_positive": self._split_user_intent_text(request.extra_preferences),
                "negative": self._split_user_intent_text(request.taboos),
                "mode": "fallback",
                "agent_failure_reason": diagnostics.get("failure_reason", ""),
            },
            agent_diagnostics=diagnostics,
        )

    def _fallback_weather_research(self, request: TravelRequest) -> WeatherResearch:
        weather_data = self.backend.get_weather_forecast(
            request.city,
            request.start_date.isoformat(),
            request.end_date.isoformat(),
        )
        forecast = [WeatherInfo.model_validate(item) for item in weather_data["forecast"]]
        risk_days = [
            f"{item.date.isoformat()} {item.condition}"
            for item in forecast
            if item.condition in {"light_rain", "hot"}
        ]
        source = "和风实时天气" if weather_data.get("data_mode") == "live" else "本地兜底样例"
        return WeatherResearch(
            forecast=forecast,
            overall_summary=f"{request.city} 当前出行时段天气存在波动，已预留室内备选安排。数据来源：{source}。",
            risk_days=risk_days,
        )

    def _fallback_hotel_research(self, request: TravelRequest) -> HotelResearch:
        hotel_data = self.backend.search_hotels(
            request.city,
            request.budget_min,
            request.budget_max,
            request.travelers,
            request.stay_nights,
            request.hotel_style,
        )
        candidates = [HotelOption.model_validate(item) for item in hotel_data["candidates"]]
        recommended = candidates[0] if candidates else None
        source = "高德实时酒店 POI" if hotel_data.get("data_mode") == "live" else "本地兜底样例"
        return HotelResearch(
            candidates=candidates,
            recommended_hotel=recommended,
            selection_reasoning=[
                f"数据来源：{source}。",
                f"每晚预算上限控制在 {hotel_data['per_night_cap']:.0f} 元左右。",
                f"住宿偏好为 {self._hotel_style_label(request.hotel_style)}。",
            ],
        )

    def _build_programmatic_plan(
        self,
        request: TravelRequest,
        attractions: AttractionResearch,
        weather: WeatherResearch,
        hotels: HotelResearch,
        restaurant_catalog: dict[str, list[RestaurantOption]],
        *,
        attraction_source: str,
        weather_source: str,
        hotel_source: str,
    ) -> TripPlan:
        selected = attractions.selected_attractions[: self._target_attraction_count(request)]
        hotel = hotels.recommended_hotel or (hotels.candidates[0] if hotels.candidates else None)
        route_target_catalog = self._build_route_target_catalog(attractions, hotels, restaurant_catalog)
        attractions_per_day = self._attractions_per_day(request)
        daily_plans: list[DayPlan] = []
        attraction_cost = 0.0
        food_cost = 0.0
        transport_cost = 0.0

        for index in range(request.trip_days):
            current_date = request.start_date + timedelta(days=index)
            weather_info = weather.forecast[min(index, len(weather.forecast) - 1)]
            start = index * attractions_per_day
            day_attractions = selected[start : start + attractions_per_day]
            meal_candidates = self._choose_day_restaurants(
                day_attractions,
                hotel,
                attractions.recommended_night_area,
                restaurant_catalog,
            )
            breakfast_spot = meal_candidates[0] if meal_candidates else None
            dinner_spot = meal_candidates[-1] if meal_candidates else None

            items: list[DayPlanItem] = []
            route_segments: list[RoutePlan] = []

            if hotel:
                breakfast_cost = (breakfast_spot.avg_cost_per_person if breakfast_spot else 20.0) * request.travelers
                food_cost += breakfast_cost
                items.append(
                    DayPlanItem(
                        time_range="08:30-09:00",
                        title="酒店出发与早餐",
                        item_type="meal",
                        location_name=breakfast_spot.name if breakfast_spot else hotel.name,
                        location_address=(
                            breakfast_spot.location.address
                            if breakfast_spot
                            else hotel.location.address
                        ),
                        summary=(
                            f"先在{breakfast_spot.nearby_anchor or hotel.nearby_area}附近安排早餐，再出发去首个景点。"
                            if breakfast_spot
                            else f"从{hotel.nearby_area}出发，先完成早餐与出门准备。"
                        ),
                        estimated_cost=round(breakfast_cost, 2),
                        reason=(
                            "早餐优先落到酒店或首段景点周边的真实餐饮候选，减少绕路。"
                            if breakfast_spot
                            else "以当前酒店为起点，更方便衔接当天首站。"
                        ),
                    )
                )

            for slot, attraction in enumerate(day_attractions):
                start_hour = 9 + slot * 4
                end_hour = start_hour + int(round(attraction.recommended_hours))
                if slot == 0 and hotel:
                    route_segments.append(
                        self._build_route_plan(
                            request.city,
                            hotel.name,
                            attraction.location.name,
                            request.transport_mode,
                            origin=self._route_target_for(hotel.name, route_target_catalog),
                            destination=self._route_target_for(attraction.location.name, route_target_catalog),
                        )
                    )
                items.append(
                    DayPlanItem(
                        time_range=f"{start_hour:02d}:30-{end_hour:02d}:00",
                        title=attraction.name,
                        item_type="attraction",
                        location_name=attraction.location.name,
                        location_address=attraction.location.address,
                        summary=attraction.summary,
                        estimated_cost=attraction.ticket_price * request.travelers,
                        reason="根据偏好匹配度和当天路线平衡度选入。",
                    )
                )
                attraction_cost += attraction.ticket_price * request.travelers
                if slot + 1 < len(day_attractions):
                    next_attraction = day_attractions[slot + 1]
                    route_segments.append(
                        self._build_route_plan(
                            request.city,
                            attraction.location.name,
                            next_attraction.location.name,
                            request.transport_mode,
                            origin=self._route_target_for(attraction.location.name, route_target_catalog),
                            destination=self._route_target_for(next_attraction.location.name, route_target_catalog),
                        )
                    )

            dinner_cost = (dinner_spot.avg_cost_per_person if dinner_spot else 90.0) * request.travelers
            food_cost += dinner_cost
            items.append(
                DayPlanItem(
                    time_range="18:30-20:00",
                    title="晚餐与夜间散步",
                    item_type="food",
                    location_name=dinner_spot.name if dinner_spot else attractions.recommended_night_area or "city center",
                    location_address=dinner_spot.location.address if dinner_spot else "",
                    summary=(
                        f"在{dinner_spot.nearby_anchor or dinner_spot.location.address or dinner_spot.name}附近安排晚餐，并预留少量夜间散步时间。"
                        if dinner_spot
                        else "将晚间留给本地美食与轻量 city walk，便于灵活调整。"
                    ),
                    estimated_cost=round(dinner_cost, 2),
                    reason=(
                        "晚餐优先选在当天景点或夜生活区域周边的真实餐饮候选，方便收尾返程。"
                        if dinner_spot
                        else "符合美食与夜游节奏，也方便收尾返程。"
                    ),
                )
            )

            if day_attractions:
                dinner_name = dinner_spot.name if dinner_spot else attractions.recommended_night_area or "city center"
                route_segments.append(
                    self._build_route_plan(
                        request.city,
                        day_attractions[-1].location.name,
                        dinner_name,
                        request.transport_mode,
                        origin=self._route_target_for(day_attractions[-1].location.name, route_target_catalog),
                        destination=self._route_target_for(dinner_name, route_target_catalog),
                    )
                )
            if hotel:
                dinner_name = dinner_spot.name if dinner_spot else attractions.recommended_night_area or "city center"
                route_segments.append(
                    self._build_route_plan(
                        request.city,
                        dinner_name,
                        hotel.name,
                        request.transport_mode,
                        origin=self._route_target_for(dinner_name, route_target_catalog),
                        destination=self._route_target_for(hotel.name, route_target_catalog),
                    )
                )

            transport_items = self._route_items_for_day(route_segments)
            items.extend(transport_items)
            day_transport_cost = sum(segment.estimated_cost for segment in route_segments)
            day_transport_time = sum(segment.duration_min for segment in route_segments)
            transport_cost += day_transport_cost

            route_summary = "、".join(item.title for item in items if item.item_type == "attraction")
            daily_plans.append(
                DayPlan(
                    date=current_date,
                    weather=weather_info,
                    route_summary=(
                        f"{route_summary or '当天安排灵活探索'} | "
                        f"{self._transport_mode_label(request.transport_mode)}合计约{day_transport_time}分钟"
                    ),
                    items=items,
                    total_transport_cost=round(day_transport_cost, 2),
                    total_transport_time_min=day_transport_time,
                )
            )

        hotel_cost = (hotel.nightly_price * request.stay_nights) if hotel else request.stay_nights * 360
        contingency = round((hotel_cost + attraction_cost + food_cost + transport_cost) * 0.08, 2)
        total = round(hotel_cost + attraction_cost + food_cost + transport_cost + contingency, 2)
        budget = BudgetBreakdown(
            hotel=round(hotel_cost, 2),
            attractions=round(attraction_cost, 2),
            food=round(food_cost, 2),
            transport=round(transport_cost, 2),
            contingency=contingency,
            total=total,
        )

        labels = [PREFERENCE_LABELS.get(pref, pref) for pref in request.preferences]
        risk_alerts = list(weather.risk_days)
        shortage_note = self._attraction_shortage_note(request, selected)
        if shortage_note:
            risk_alerts.append(shortage_note)
        if total > request.budget_max:
            risk_alerts.append("当前方案超出预算上限，建议降低酒店档位或减少收费景点。")
        if request.taboos:
            risk_alerts.append(f"仍需人工复核负向约束：{request.taboos}")

        return TripPlan(
            city=request.city,
            travel_theme=self._human_labels(labels) or "平衡型城市探索",
            overview=f"这是一份 {request.trip_days} 天的{self._pace_label(request.pace)}行程，围绕{self._human_labels(labels) or '城市精华'}展开。",
            trip_days=request.trip_days,
            planning_source="program_fallback",
            attraction_data_source=attraction_source,
            weather_data_source=weather_source,
            hotel_data_source=hotel_source,
            attraction_search_plan=attractions.search_plan,
            preference_interpretation=attractions.preference_interpretation,
            agent_diagnostics=attractions.agent_diagnostics,
            selected_attractions=selected,
            recommended_hotel=hotel,
            daily_plans=daily_plans,
            budget=budget,
            packing_tips=self._packing_tips(weather),
            risk_alerts=risk_alerts,
            notes=[
                note
                for note in [
                    "优先使用实时地图与天气数据；缺失时自动回退到本地样例。",
                    "酒店价格目前仍以 POI 候选和估算为主，不等于 OTA 实时报价。",
                    "餐饮点会优先从当天景点、夜生活区域或酒店周边做真实 POI 检索。",
                    f"每日交通建议按“{self._transport_mode_label(request.transport_mode)}”生成。",
                    self._transport_note(request),
                    shortage_note,
                ]
                if note
            ],
        )

    def _inject_transport_details(
        self,
        plan: TripPlan,
        request: TravelRequest,
        attractions: AttractionResearch,
        hotels: HotelResearch,
        restaurant_catalog: dict[str, list[RestaurantOption]],
        hotel: HotelOption | None,
        night_area: str,
    ) -> None:
        route_target_catalog = self._build_route_target_catalog(attractions, hotels, restaurant_catalog)
        for day in plan.daily_plans:
            non_transport_items = [item for item in day.items if item.item_type != "transport"]
            route_targets = self._collect_day_route_targets(non_transport_items, hotel, night_area, route_target_catalog)
            route_segments = self._build_day_route_segments(request, route_targets)

            day.items = non_transport_items + self._route_items_for_day(route_segments)
            day.total_transport_cost = round(sum(segment.estimated_cost for segment in route_segments), 2)
            day.total_transport_time_min = sum(segment.duration_min for segment in route_segments)
            day.route_summary = self._refresh_day_route_summary(day, request)

    def _collect_day_route_targets(
        self,
        items: list[DayPlanItem],
        hotel: HotelOption | None,
        night_area: str,
        route_target_catalog: dict[str, RouteTarget],
    ) -> list[RouteTarget]:
        ordered_targets: list[RouteTarget] = []

        def push_target(name: str, address: str = "") -> None:
            normalized = name.strip()
            if not normalized:
                return
            if ordered_targets and ordered_targets[-1].name == normalized:
                return
            ordered_targets.append(route_target_catalog.get(normalized, RouteTarget(normalized, address=address)))

        if hotel:
            push_target(hotel.name, hotel.location.address)

        for item in items:
            if item.item_type in {"attraction", "food", "meal"}:
                push_target(item.location_name, item.location_address)

        if hotel:
            push_target(hotel.name, hotel.location.address)
        elif night_area:
            push_target(night_area)

        return ordered_targets

    def _build_day_route_segments(
        self,
        request: TravelRequest,
        route_targets: list[RouteTarget],
    ) -> list[RoutePlan]:
        route_segments: list[RoutePlan] = []
        for idx in range(len(route_targets) - 1):
            origin = route_targets[idx]
            destination = route_targets[idx + 1]
            if origin.name == destination.name:
                continue
            route_segments.append(
                self._build_route_plan(
                    request.city,
                    origin.name,
                    destination.name,
                    request.transport_mode,
                    origin=origin,
                    destination=destination,
                )
            )
        return route_segments

    def _build_route_target_catalog(
        self,
        attractions: AttractionResearch,
        hotels: HotelResearch,
        restaurant_catalog: dict[str, list[RestaurantOption]],
    ) -> dict[str, RouteTarget]:
        catalog: dict[str, RouteTarget] = {}

        def add(name: str, location: Any) -> None:
            cleaned = self._sanitize_place_name(name)
            if not cleaned:
                return
            try:
                lat = float(getattr(location, "lat", 0.0) or 0.0)
                lng = float(getattr(location, "lng", 0.0) or 0.0)
            except Exception:
                return
            if lat == 0.0 and lng == 0.0:
                return
            address = str(getattr(location, "address", "") or "").strip()
            catalog[cleaned] = RouteTarget(cleaned, address, lat, lng)

        for attraction in attractions.selected_attractions:
            add(attraction.name, attraction.location)
            add(attraction.location.name, attraction.location)
        for hotel_option in hotels.candidates:
            add(hotel_option.name, hotel_option.location)
            add(hotel_option.location.name, hotel_option.location)
        if hotels.recommended_hotel is not None:
            add(hotels.recommended_hotel.name, hotels.recommended_hotel.location)
            add(hotels.recommended_hotel.location.name, hotels.recommended_hotel.location)
        for options in restaurant_catalog.values():
            for restaurant in options:
                add(restaurant.name, restaurant.location)
                add(restaurant.location.name, restaurant.location)
        return catalog

    def _route_target_for(self, name: str, catalog: dict[str, RouteTarget]) -> RouteTarget:
        cleaned = self._sanitize_place_name(name)
        return catalog.get(cleaned) or catalog.get(name) or RouteTarget(name)

    def _refresh_day_route_summary(self, day: DayPlan, request: TravelRequest) -> str:
        attraction_titles = [item.title for item in day.items if item.item_type == "attraction"]
        route_summary = "、".join(attraction_titles) or "当天安排灵活探索"
        if day.total_transport_time_min > 0:
            return (
                f"{route_summary} | "
                f"{self._transport_mode_label(request.transport_mode)}合计约{day.total_transport_time_min}分钟"
            )
        return route_summary

    def _ground_attraction_research(
        self,
        candidate: AttractionResearch,
        fallback: AttractionResearch,
    ) -> AttractionResearch | None:
        if not candidate.selected_attractions:
            return None

        catalog = {item.name: item for item in fallback.selected_attractions}
        grounded: list[Attraction] = []
        for item in candidate.selected_attractions:
            resolved_name = self._resolve_place_name(item.name, catalog)
            if not resolved_name:
                continue
            canonical = catalog[resolved_name]
            if canonical.name not in {existing.name for existing in grounded}:
                grounded.append(canonical)

        if not grounded:
            return None

        recommended_night_area = (
            self._resolve_place_name(candidate.recommended_night_area, [fallback.recommended_night_area])
            or fallback.recommended_night_area
        )
        return AttractionResearch(
            city_overview=candidate.city_overview or fallback.city_overview,
            selected_attractions=grounded,
            selection_reasoning=candidate.selection_reasoning or fallback.selection_reasoning,
            recommended_night_area=recommended_night_area,
            search_plan=candidate.search_plan or fallback.search_plan,
            preference_interpretation=candidate.preference_interpretation or fallback.preference_interpretation,
        )

    def _ground_agent_attraction_research(
        self,
        candidate: AttractionResearch,
        fallback: AttractionResearch,
        candidate_pool: list[dict[str, Any]],
    ) -> AttractionResearch | None:
        diagnostics = dict(candidate.agent_diagnostics or {})
        diagnostics["candidate_pool_size"] = len(candidate_pool)
        diagnostics["candidate_selected_count"] = len(candidate.selected_attractions)
        if not candidate.selected_attractions:
            diagnostics["failure_reason"] = diagnostics.get("failure_reason") or "agent_selected_no_attractions"
            candidate.agent_diagnostics = diagnostics
            return None
        if not candidate_pool:
            diagnostics["failure_reason"] = "mcp_candidate_pool_empty"
            candidate.agent_diagnostics = diagnostics
            return None

        by_id = {
            self._safe_pool_key(item.get("candidate_id")): item
            for item in candidate_pool
            if self._safe_pool_key(item.get("candidate_id"))
        }
        by_name = {
            self._sanitize_place_name(str(item.get("name", ""))): item
            for item in candidate_pool
            if self._sanitize_place_name(str(item.get("name", "")))
        }
        grounded: list[Attraction] = []
        removed: list[str] = []
        existing_names: set[str] = set()

        for item in candidate.selected_attractions:
            raw = item.model_dump()
            source = (
                by_id.get(self._safe_pool_key(raw.get("candidate_id")))
                or by_name.get(self._sanitize_place_name(item.name))
            )
            if source is None:
                removed.append(item.name)
                continue

            name = str(source.get("name", item.name)).strip()
            if not name or name in existing_names:
                continue
            existing_names.add(name)
            try:
                grounded.append(
                    Attraction.model_validate(
                        {
                            "name": name,
                            "category": str(source.get("category") or item.category or source.get("source_query") or "景点"),
                            "tags": item.tags or [str(source.get("source_query") or "景点")],
                            "summary": item.summary or str(source.get("type") or "真实 POI 景点候选"),
                            "recommended_hours": item.recommended_hours,
                            "ticket_price": item.ticket_price,
                            "best_time": item.best_time,
                            "location": {
                                "name": name,
                                "address": str(source.get("address") or item.location.address or ""),
                                "lat": float(source.get("lat", 0.0) or 0.0),
                                "lng": float(source.get("lng", 0.0) or 0.0),
                            },
                        }
                    )
                )
            except Exception:
                removed.append(item.name)

        if not grounded:
            diagnostics["failure_reason"] = "no_agent_attractions_matched_candidate_pool"
            diagnostics["grounding_removed"] = removed[:12]
            diagnostics["candidate_pool_preview"] = [
                {
                    "candidate_id": item.get("candidate_id", ""),
                    "name": item.get("name", ""),
                    "source_query": item.get("source_query", ""),
                }
                for item in candidate_pool[:12]
            ]
            candidate.agent_diagnostics = diagnostics
            return None

        reasoning = list(candidate.selection_reasoning or fallback.selection_reasoning)
        reasoning.append("已进行候选池验真：入选景点必须来自本轮 MCP 搜索返回的 POI 候选。")
        if removed:
            reasoning.append("已移除未在 MCP 候选池中找到的景点：" + "、".join(removed[:5]) + "。")
        diagnostics["failure_reason"] = ""
        diagnostics["grounding_ok"] = True
        diagnostics["grounded_selected_count"] = len(grounded)
        diagnostics["grounding_removed"] = removed[:12]

        recommended_night_area = (
            self._resolve_place_name(candidate.recommended_night_area, [fallback.recommended_night_area])
            or candidate.recommended_night_area
            or fallback.recommended_night_area
        )
        return AttractionResearch(
            city_overview=candidate.city_overview or fallback.city_overview,
            selected_attractions=grounded,
            selection_reasoning=reasoning,
            recommended_night_area=recommended_night_area,
            search_plan=candidate.search_plan or fallback.search_plan,
            preference_interpretation=candidate.preference_interpretation or fallback.preference_interpretation,
            agent_diagnostics=diagnostics,
        )

    def _safe_pool_key(self, value: Any) -> str:
        return str(value or "").strip()

    def _ground_hotel_research(
        self,
        candidate: HotelResearch,
        fallback: HotelResearch,
    ) -> HotelResearch | None:
        if not candidate.candidates and candidate.recommended_hotel is None:
            return None

        catalog = {item.name: item for item in fallback.candidates}
        grounded_candidates: list[HotelOption] = []
        for item in candidate.candidates:
            resolved_name = self._resolve_place_name(item.name, catalog)
            if not resolved_name:
                continue
            canonical = catalog[resolved_name]
            if canonical.name not in {existing.name for existing in grounded_candidates}:
                grounded_candidates.append(canonical)

        if not grounded_candidates and fallback.recommended_hotel is not None:
            grounded_candidates = [fallback.recommended_hotel]
        if not grounded_candidates:
            return None

        recommended = grounded_candidates[0]
        if candidate.recommended_hotel is not None:
            resolved_hotel = self._resolve_place_name(candidate.recommended_hotel.name, catalog)
            if resolved_hotel:
                recommended = catalog[resolved_hotel]

        return HotelResearch(
            candidates=grounded_candidates,
            recommended_hotel=recommended,
            selection_reasoning=candidate.selection_reasoning or fallback.selection_reasoning,
        )

    def _ground_trip_plan(
        self,
        plan: TripPlan,
        attractions: AttractionResearch,
        hotels: HotelResearch,
        restaurant_catalog: dict[str, list[RestaurantOption]],
    ) -> TripPlan | None:
        attraction_catalog = {item.name: item for item in attractions.selected_attractions}
        hotel_catalog = {item.name: item for item in hotels.candidates}
        restaurant_candidates = self._flatten_restaurant_catalog(restaurant_catalog)
        region_candidates = self._collect_region_candidates(attractions, hotels)
        hotel = hotels.recommended_hotel or (hotels.candidates[0] if hotels.candidates else None)
        attraction_count = 0
        unresolved_attractions = 0
        used_attraction_names: set[str] = set()
        removed_duplicate_attractions: list[str] = []

        for day_index, day in enumerate(plan.daily_plans):
            day_attractions_in_plan = [
                attraction_catalog[item.location_name]
                for item in day.items
                if item.item_type == "attraction" and item.location_name in attraction_catalog
            ]
            day_restaurants = {
                item.name: item
                for item in self._choose_day_restaurants(
                    day_attractions_in_plan,
                    hotel,
                    attractions.recommended_night_area,
                    restaurant_catalog,
                )
            }
            grounded_items: list[DayPlanItem] = []
            for item in day.items:
                if item.item_type == "attraction":
                    attraction_count += 1
                    resolved_name = self._resolve_place_name(item.location_name or item.title, attraction_catalog)
                    if not resolved_name:
                        unresolved_attractions += 1
                        continue
                    if resolved_name in used_attraction_names:
                        removed_duplicate_attractions.append(resolved_name)
                        continue
                    used_attraction_names.add(resolved_name)
                    attraction = attraction_catalog[resolved_name]
                    item.location_name = resolved_name
                    item.title = resolved_name
                    item.location_address = attraction.location.address
                    grounded_items.append(item)
                    continue

                if item.item_type in {"food", "meal"}:
                    resolved_location = self._resolve_route_anchor(
                        item.location_name or item.title,
                        attraction_catalog=attraction_catalog,
                        hotel_catalog=hotel_catalog,
                        restaurant_catalog=day_restaurants or restaurant_candidates,
                        region_candidates=region_candidates,
                    )
                    if resolved_location:
                        item.location_name = resolved_location
                    item.location_address = self._resolve_location_address(
                        item.location_name or item.title,
                        attraction_catalog=attraction_catalog,
                        hotel_catalog=hotel_catalog,
                        restaurant_catalog=day_restaurants or restaurant_candidates,
                    )
                grounded_items.append(item)
            day.items = grounded_items

        if attraction_count and unresolved_attractions:
            return None

        if hotels.recommended_hotel is not None:
            if plan.recommended_hotel is not None:
                resolved_hotel = self._resolve_place_name(plan.recommended_hotel.name, hotel_catalog)
                if not resolved_hotel:
                    return None
            plan.recommended_hotel = hotels.recommended_hotel

        if attractions.selected_attractions:
            plan.selected_attractions = attractions.selected_attractions[:]
        if removed_duplicate_attractions:
            unique_removed = []
            for name in removed_duplicate_attractions:
                if name not in unique_removed:
                    unique_removed.append(name)
            plan.notes.append(
                "已移除跨天重复景点：" + "、".join(unique_removed[:8]) + "。"
            )

        return plan

    def _collect_region_candidates(
        self,
        attractions: AttractionResearch,
        hotels: HotelResearch,
    ) -> list[str]:
        candidates: list[str] = []

        def add(value: str) -> None:
            cleaned = self._sanitize_place_name(value)
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)

        add(attractions.recommended_night_area)
        if hotels.recommended_hotel is not None:
            add(hotels.recommended_hotel.nearby_area)
        for hotel in hotels.candidates:
            add(hotel.nearby_area)
        return candidates

    def _build_restaurant_catalog(
        self,
        request: TravelRequest,
        attractions: AttractionResearch,
        hotels: HotelResearch,
    ) -> dict[str, list[RestaurantOption]]:
        anchors: list[str] = []
        for attraction in attractions.selected_attractions[: max(request.trip_days * 2, 4)]:
            self._append_unique_anchor(anchors, attraction.location.name)
        if attractions.recommended_night_area:
            self._append_unique_anchor(anchors, attractions.recommended_night_area)
        if hotels.recommended_hotel is not None:
            self._append_unique_anchor(anchors, hotels.recommended_hotel.name)
            self._append_unique_anchor(anchors, hotels.recommended_hotel.nearby_area)

        catalog: dict[str, list[RestaurantOption]] = {}
        budget_hint = max(request.budget_max / max(request.trip_days, 1), 120)
        for anchor in anchors:
            try:
                payload = self.backend.search_restaurants(
                    city=request.city,
                    anchor=anchor,
                    preferences=",".join(request.preferences),
                    budget_hint=budget_hint,
                    travelers=request.travelers,
                    radius_m=1800,
                )
            except Exception:
                continue
            options: list[RestaurantOption] = []
            for item in (payload.get("restaurants") or []):
                try:
                    options.append(RestaurantOption.model_validate(item))
                except Exception:
                    continue
            if options:
                catalog[anchor] = options
        return catalog

    def _build_meal_research(
        self,
        request: TravelRequest,
        attractions: AttractionResearch,
        hotels: HotelResearch,
        restaurant_catalog: dict[str, list[RestaurantOption]],
    ) -> MealResearch:
        hotel = hotels.recommended_hotel or (hotels.candidates[0] if hotels.candidates else None)
        selected = attractions.selected_attractions[: self._target_attraction_count(request)]
        attractions_per_day = self._attractions_per_day(request)
        day_candidates: list[DayMealResearch] = []
        general_candidates = list(self._flatten_restaurant_catalog(restaurant_catalog).values())[:10]

        for index in range(request.trip_days):
            current_date = request.start_date + timedelta(days=index)
            start = index * attractions_per_day
            day_attractions = selected[start : start + attractions_per_day]
            anchors = self._collect_day_meal_anchors(day_attractions, hotel, attractions.recommended_night_area)
            candidates = self._choose_day_restaurants(
                day_attractions,
                hotel,
                attractions.recommended_night_area,
                restaurant_catalog,
            )
            day_candidates.append(
                DayMealResearch(
                    day_index=index + 1,
                    date=current_date,
                    anchors=anchors,
                    candidates=candidates,
                    dining_strategy=(
                        "优先选择当天景点周边的真实餐饮 POI，晚餐尽量靠近夜生活区域或回酒店顺路位置。"
                    ),
                )
            )

        notes = [
            "早餐和晚餐优先使用真实餐饮候选，避免只写模糊片区名。",
            "如果当天候选不足，可以回退到 recommended_night_area 或酒店 nearby_area 作为稳定锚点。",
        ]
        return MealResearch(
            city=request.city,
            city_summary="餐饮候选按当天景点、夜生活区域和酒店周边进行真实 POI 检索与整理。",
            day_candidates=day_candidates,
            general_candidates=general_candidates,
            planning_notes=notes,
        )

    def _attractions_per_day(self, request: TravelRequest) -> int:
        return {
            "relaxed": 1,
            "balanced": 2,
            "intense": 3,
        }.get(request.pace, 2)

    def _target_attraction_count(self, request: TravelRequest) -> int:
        return max(request.trip_days * self._attractions_per_day(request), 3)

    def _attraction_shortage_note(self, request: TravelRequest, selected: list[Attraction]) -> str:
        target = self._target_attraction_count(request)
        if len(selected) >= target:
            return ""
        return (
            f"真实可用景点候选不足：按当前节奏预计需要约 {target} 个不重复景点，"
            f"本次只获得 {len(selected)} 个；后续日期会减少景点密度，不自动重复已安排景点。"
        )

    def _collect_day_meal_anchors(
        self,
        day_attractions: list[Attraction],
        hotel: HotelOption | None,
        night_area: str,
    ) -> list[str]:
        anchors: list[str] = []
        if hotel is not None:
            self._append_unique_anchor(anchors, hotel.name)
            self._append_unique_anchor(anchors, hotel.nearby_area)
        for attraction in day_attractions:
            self._append_unique_anchor(anchors, attraction.location.name)
        self._append_unique_anchor(anchors, night_area)
        return anchors

    def _append_unique_anchor(self, anchors: list[str], value: str) -> None:
        cleaned = self._sanitize_place_name(value)
        if cleaned and cleaned not in anchors:
            anchors.append(cleaned)

    def _choose_day_restaurants(
        self,
        day_attractions: list[Attraction],
        hotel: HotelOption | None,
        night_area: str,
        restaurant_catalog: dict[str, list[RestaurantOption]],
    ) -> list[RestaurantOption]:
        selected: list[RestaurantOption] = []
        seen: set[str] = set()
        anchors: list[str] = []
        if hotel is not None:
            self._append_unique_anchor(anchors, hotel.name)
            self._append_unique_anchor(anchors, hotel.nearby_area)
        for attraction in day_attractions:
            self._append_unique_anchor(anchors, attraction.location.name)
        self._append_unique_anchor(anchors, night_area)

        for anchor in anchors:
            for option in restaurant_catalog.get(anchor, []):
                if option.name in seen:
                    continue
                selected.append(option)
                seen.add(option.name)
                if len(selected) >= 4:
                    return selected
        return selected

    def _flatten_restaurant_catalog(
        self,
        restaurant_catalog: dict[str, list[RestaurantOption]],
    ) -> dict[str, RestaurantOption]:
        flattened: dict[str, RestaurantOption] = {}
        for options in restaurant_catalog.values():
            for option in options:
                flattened.setdefault(option.name, option)
        return flattened

    def _resolve_route_anchor(
        self,
        raw_name: str,
        *,
        attraction_catalog: dict[str, Attraction],
        hotel_catalog: dict[str, HotelOption],
        restaurant_catalog: dict[str, RestaurantOption],
        region_candidates: list[str],
    ) -> str | None:
        direct = self._resolve_place_name(raw_name, attraction_catalog)
        if direct:
            return direct

        direct = self._resolve_place_name(raw_name, hotel_catalog)
        if direct:
            return direct

        direct = self._resolve_place_name(raw_name, restaurant_catalog)
        if direct:
            return direct

        return self._resolve_place_name(raw_name, region_candidates)

    def _resolve_location_address(
        self,
        raw_name: str,
        *,
        attraction_catalog: dict[str, Attraction],
        hotel_catalog: dict[str, HotelOption],
        restaurant_catalog: dict[str, RestaurantOption],
    ) -> str:
        resolved_attraction = self._resolve_place_name(raw_name, attraction_catalog)
        if resolved_attraction:
            return attraction_catalog[resolved_attraction].location.address

        resolved_hotel = self._resolve_place_name(raw_name, hotel_catalog)
        if resolved_hotel:
            return hotel_catalog[resolved_hotel].location.address

        resolved_restaurant = self._resolve_place_name(raw_name, restaurant_catalog)
        if resolved_restaurant:
            return restaurant_catalog[resolved_restaurant].location.address

        return ""

    def _resolve_place_name(
        self,
        raw_name: str,
        candidates: Iterable[str] | dict[str, object],
    ) -> str | None:
        text = self._sanitize_place_name(raw_name)
        if not text:
            return None

        options = list(candidates.keys()) if isinstance(candidates, dict) else list(candidates)
        if not options:
            return None
        if text in options:
            return text

        scored: list[tuple[int, str]] = []
        for option in options:
            normalized_option = self._sanitize_place_name(option)
            if not normalized_option:
                continue
            if normalized_option == text:
                return option
            if normalized_option.endswith(text) or text.endswith(normalized_option):
                scored.append((3, option))
            elif text in normalized_option or normalized_option in text:
                scored.append((2, option))
            elif self._core_place_token(normalized_option) == self._core_place_token(text):
                scored.append((1, option))

        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], len(item[1])))
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]

    def _sanitize_place_name(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        for marker in ("??", "锛?", "?锛?", "锟?"):
            cleaned = cleaned.replace(marker, "")
        cleaned = cleaned.replace(" / ", " ").replace("/", " ")
        cleaned = cleaned.strip(" -,.，。;；:：|[]【】()（）")
        return " ".join(cleaned.split()).strip()

    def _core_place_token(self, value: str) -> str:
        text = self._sanitize_place_name(value)
        if not text:
            return ""
        for sep in (" ", "路", "-", "·", "("):
            if sep in text:
                text = text.split(sep, 1)[0]
        return text[-6:]

    def _normalize_city_input(self, city: str) -> str | None:
        raw = (city or "").strip()
        if not raw:
            return None
        if "锟?" in raw:
            return None
        if "?" in raw and not any(ch.isalpha() or ("\u4e00" <= ch <= "\u9fff") for ch in raw):
            return None

        cleaned = self._sanitize_place_name(raw)
        if not cleaned:
            return None
        return cleaned

    def _build_route_plan(
        self,
        city: str,
        origin_name: str,
        destination_name: str,
        mode: str,
        *,
        origin: RouteTarget | None = None,
        destination: RouteTarget | None = None,
    ) -> RoutePlan:
        effective_mode = "public_transit" if mode == "mixed" else mode
        transport = self.backend.estimate_local_transport(
            city,
            origin_name,
            destination_name,
            effective_mode,
            self._effective_transit_preference(effective_mode),
            origin_location=origin.__dict__ if origin else None,
            destination_location=destination.__dict__ if destination else None,
        )
        if self._is_route_outlier(transport):
            existing_reason = str(transport.get("fallback_reason", "") or "")
            outlier_reason = self._route_outlier_reason(transport)
            transport["fallback_reason"] = ", ".join(
                part for part in [existing_reason, outlier_reason] if part
            )
            if str(transport.get("data_mode")) == "live":
                transport["data_mode"] = "live_outlier"
            else:
                transport["data_mode"] = str(transport.get("data_mode") or "fallback")

        detail_segments = [
            RouteDetailSegment.model_validate(item)
            for item in (transport.get("route_segments") or [])
        ]
        return RoutePlan(
            city=city,
            mode=effective_mode,  # type: ignore[arg-type]
            origin=origin_name,
            destination=destination_name,
            origin_address=origin.address if origin else "",
            destination_address=destination.address if destination else "",
            distance_km=float(transport.get("distance_km", 0.0) or 0.0),
            duration_min=int(transport.get("duration_min", 0) or 0),
            estimated_cost=float(transport.get("estimated_cost", transport.get("estimated_taxi_cost", 0.0)) or 0.0),
            transfers=int(transport.get("transfers", 0) or 0),
            walk_distance_m=int(transport.get("walk_distance_m", 0) or 0),
            tolls=float(transport.get("tolls", 0.0) or 0.0),
            data_mode=str(transport.get("data_mode", "fallback")),
            fallback_reason=str(transport.get("fallback_reason", "")),
            summary=str(transport.get("summary", "")),
            strategy_label=str(transport.get("strategy_label", "")),
            traffic_status=str(transport.get("traffic_status", "")),
            route_alternatives=list(transport.get("route_alternatives") or []),
            route_segments=detail_segments,
        )

    def _is_route_outlier(self, transport: dict[str, Any]) -> bool:
        distance_km = float(transport.get("distance_km", 0.0) or 0.0)
        duration_min = int(transport.get("duration_min", 0) or 0)
        return distance_km >= 80 or duration_min >= 240

    def _route_outlier_reason(self, transport: dict[str, Any]) -> str:
        distance_km = float(transport.get("distance_km", 0.0) or 0.0)
        duration_min = int(transport.get("duration_min", 0) or 0)
        reasons: list[str] = []
        if distance_km >= 80:
            reasons.append(f"route_distance_outlier:{distance_km:.1f}km")
        if duration_min >= 240:
            reasons.append(f"route_duration_outlier:{duration_min}min")
        return ",".join(reasons)

    def _route_items_for_day(self, segments: list[RoutePlan]) -> list[DayPlanItem]:
        items: list[DayPlanItem] = []
        for index, segment in enumerate(segments, start=1):
            detail = (
                f"{self._transport_mode_label(segment.mode)}约{segment.duration_min}分钟，"
                f"{segment.distance_km:.1f}公里，约 {segment.estimated_cost:.0f} 元"
            )
            if segment.mode == "public_transit":
                detail += f"，换乘 {segment.transfers} 次，步行 {segment.walk_distance_m} 米"
            if segment.mode == "self_drive" and segment.tolls > 0:
                detail += f"，过路费约 {segment.tolls:.0f} 元"
            if segment.traffic_status:
                detail += f"，{segment.traffic_status}"

            items.append(
                DayPlanItem(
                    time_range=f"交通 {index}",
                    title=f"{segment.origin} -> {segment.destination}",
                    item_type="transport",
                    location_name=segment.destination,
                    location_address=segment.destination_address,
                    summary=detail,
                    estimated_cost=segment.estimated_cost,
                    reason=segment.summary or "路线由交通工具链估算生成。",
                    transport_mode=self._transport_mode_label(segment.mode),
                    from_location=segment.origin,
                    to_location=segment.destination,
                    duration_min=segment.duration_min,
                    distance_km=segment.distance_km,
                    transfers=segment.transfers,
                    route_segments=segment.route_segments,
                    route_strategy=segment.strategy_label,
                    route_data_mode=segment.data_mode,
                    route_fallback_reason=segment.fallback_reason,
                    route_alternatives=segment.route_alternatives,
                    expandable=bool(segment.route_segments),
                )
            )
        return items

    def _transport_mode_label(self, mode: str) -> str:
        return {
            "public_transit": "公共交通",
            "self_drive": "自驾",
            "taxi": "打车",
            "mixed": "混合出行",
            "walk": "步行",
        }.get(mode, mode)

    def _effective_transit_preference(self, mode: str) -> str:
        if mode != "public_transit":
            return "recommended"
        return self._request_transit_preference

    def _transport_note(self, request: TravelRequest) -> str:
        if request.transport_mode != "public_transit":
            return "当前版本仅对公共交通提供细分偏好映射。"
        label = {
            "recommended": "推荐",
            "less_walking": "步行少",
            "subway_priority": "地铁优先",
            "bus_priority": "公交优先",
        }.get(request.transit_preference, request.transit_preference)
        return f"公共交通偏好：{label}。"

    def _format_attraction_agent_diagnostic(self, diagnostics: dict[str, Any]) -> str:
        reason = str(diagnostics.get("failure_reason") or "unknown").strip()
        readable = {
            "llm_output_json_parse_failed": "景点 Agent 没有返回可解析 JSON",
            "attraction_research_schema_validation_failed": "景点 Agent 返回的 JSON 不符合景点研究结构",
            "selected_attractions_not_list": "景点 Agent 返回的 selected_attractions 不是列表",
            "agent_selected_no_attractions": "景点 Agent 没有选出景点",
            "mcp_candidate_pool_empty": "景点 Agent 本轮没有留下 MCP 候选池",
            "no_agent_attractions_matched_candidate_pool": "景点 Agent 选择的景点没有匹配到本轮 MCP 候选池",
            "agent_grounding_failed": "景点 Agent 输出未通过候选池验真",
            "attraction_agent_postprocess_exception": "景点 Agent 后处理发生异常",
            "attraction_agent_unavailable_or_unverified": "景点 Agent 不可用或结果未通过验真",
        }.get(reason, reason or "未知原因")
        parts = [f"景点 Agent 诊断：{readable}。"]
        if diagnostics.get("raw_output_length") is not None:
            parts.append(f"原始输出长度 {diagnostics.get('raw_output_length')}。")
        if diagnostics.get("raw_selected_count") is not None:
            parts.append(f"模型原始选择 {diagnostics.get('raw_selected_count')} 个景点。")
        if diagnostics.get("verified_selected_count") is not None:
            parts.append(f"字段验真后剩余 {diagnostics.get('verified_selected_count')} 个。")
        if diagnostics.get("candidate_pool_size") is not None:
            parts.append(f"MCP 候选池 {diagnostics.get('candidate_pool_size')} 个。")
        if diagnostics.get("grounded_selected_count") is not None:
            parts.append(f"候选池匹配成功 {diagnostics.get('grounded_selected_count')} 个。")
        return "".join(parts)

    def _pace_label(self, pace: str) -> str:
        return {"relaxed": "慢游", "balanced": "平衡", "intense": "紧凑"}.get(pace, pace)

    def _hotel_style_label(self, hotel_style: str) -> str:
        return {"budget": "经济", "comfort": "舒适", "premium": "高档"}.get(hotel_style, hotel_style)

    def _human_labels(self, labels: list[str]) -> str:
        return "、".join(label for label in labels if label)

    def _packing_tips(self, weather: WeatherResearch) -> list[str]:
        tips = ["舒适步行鞋", "充电宝", "身份证件与订单截图"]
        conditions = {item.condition for item in weather.forecast}
        if "light_rain" in conditions:
            tips.append("折叠伞")
        if "hot" in conditions:
            tips.append("防晒用品和水杯")
        return tips

    def _source_from_attraction_research(self, research: AttractionResearch) -> str:
        joined = " ".join(research.selection_reasoning).lower()
        if "live amap" in joined or "高德实时" in joined:
            return "live_amap"
        if research.selected_attractions:
            return "agent_generated"
        return "fallback"

    def _source_from_weather_research(self, research: WeatherResearch) -> str:
        summary = research.overall_summary.lower()
        if "qweather" in summary or "和风实时" in summary:
            return "live_qweather"
        if research.forecast:
            return "agent_generated"
        return "fallback"

    def _source_from_hotel_research(self, research: HotelResearch) -> str:
        if research.recommended_hotel and research.recommended_hotel.price_source != "estimated":
            return research.recommended_hotel.price_source
        if research.recommended_hotel and research.recommended_hotel.price_source == "estimated_from_poi":
            return "live_poi_estimated_price"
        if research.candidates:
            return "agent_generated"
        return "fallback"
