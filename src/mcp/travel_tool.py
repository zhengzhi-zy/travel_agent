from __future__ import annotations

import json
from typing import Any

from hello_agents.tools import Tool, ToolParameter, tool_action
from hello_agents.tools.response import ToolResponse

from src.mcp.travel_backend import TravelDataBackend


class TravelBackendTool(Tool):
    def __init__(self, backend: TravelDataBackend):
        super().__init__(
            name="travel",
            description="Travel planning tools backed by local data and optional live APIs.",
            expandable=True,
        )
        self.backend = backend

    @tool_action("travel_get_city_profile", "Return a short city profile and recommended night area.")
    def get_city_profile(self, city: str) -> str:
        return self._json(self.backend.get_city_profile(city))

    @tool_action("travel_search_attractions", "Search attractions that match travel preferences and budget.")
    def search_attractions(
        self,
        city: str,
        preferences: str = "",
        travelers: int = 1,
        daily_budget: float = 500.0,
        target_count: int = 6,
        budget: str = "",
        pace: str = "",
    ) -> str:
        if budget and not daily_budget:
            try:
                daily_budget = float(str(budget).split("-")[-1])
            except Exception:
                pass
        return self._json(
            self.backend.search_attractions(
                city,
                preferences,
                travelers,
                daily_budget,
                target_count=target_count,
                budget=budget,
                pace=pace,
            )
        )

    @tool_action("travel_search_attraction_pois", "Search raw attraction POI candidates by a concrete keyword.")
    def search_attraction_pois(self, city: str, query: str, limit: int = 6) -> str:
        return self._json(self.backend.search_attraction_pois(city=city, query=query, limit=limit))

    @tool_action("travel_search_hotels", "Search hotel candidates using budget, travelers, stay nights, and style.")
    def search_hotels(
        self,
        city: str,
        budget_min: float = 0,
        budget_max: float = 0,
        travelers: int = 2,
        stay_nights: int = 1,
        hotel_style: str = "comfort",
        limit: int = 3,
        area_hint: str = "",
        search_focus: str = "main",
        total_budget: str = "",
        stay_length: str = "",
        style: str = "",
    ) -> str:
        return self._json(
            self.backend.search_hotels(
                city,
                budget_min,
                budget_max,
                travelers,
                stay_nights,
                hotel_style,
                limit=limit,
                area_hint=area_hint,
                search_focus=search_focus,
                total_budget=total_budget,
                stay_length=stay_length,
                style=style,
            )
        )

    @tool_action("travel_search_restaurants", "Search restaurant candidates around a city area or anchor POI.")
    def search_restaurants(
        self,
        city: str,
        anchor: str = "",
        preferences: str = "",
        budget_hint: float = 0,
        travelers: int = 2,
        radius_m: int = 2000,
    ) -> str:
        return self._json(
            self.backend.search_restaurants(
                city=city,
                anchor=anchor,
                preferences=preferences,
                budget_hint=budget_hint,
                travelers=travelers,
                radius_m=radius_m,
            )
        )

    @tool_action("travel_get_weather_forecast", "Return a weather forecast for the trip date range.")
    def get_weather_forecast(self, city: str, start_date: str, end_date: str) -> str:
        return self._json(self.backend.get_weather_forecast(city, start_date, end_date))

    @tool_action("travel_estimate_local_transport", "Estimate city-level transport distance, duration, and cost.")
    def estimate_local_transport(
        self,
        city: str,
        origin_name: str,
        destination_name: str,
        mode: str = "public_transit",
        transit_preference: str = "recommended",
    ) -> str:
        return self._json(
            self.backend.estimate_local_transport(
                city,
                origin_name,
                destination_name,
                mode,
                transit_preference,
            )
        )

    @tool_action("travel_geocode_city", "Geocode a city using AMap when available.")
    def geocode_city(self, city: str) -> str:
        return self._json(self.backend.geocode_city(city) or {})

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        return ToolResponse.success(text=self._json({"message": "Use expanded travel_* tools."}))

    def get_parameters(self) -> list[ToolParameter]:
        return []

    def _json(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False)
