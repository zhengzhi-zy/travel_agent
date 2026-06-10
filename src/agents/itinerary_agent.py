from __future__ import annotations

from src.agents.base import BaseWorkflowAgent
from src.models import AttractionResearch, HotelResearch, MealResearch, TravelRequest, TripPlan, WeatherResearch


class ItineraryPlanningAgent(BaseWorkflowAgent):
    name = "ItineraryPlanningAgent"
    system_prompt = (
        "You are the main trip planning agent. "
        "Combine attraction research, hotel research, meal research, and weather research into a realistic structured trip plan. "
        "Do not invent unsupported constraints. "
        "For attraction items, location_name must come from the provided attraction research. "
        "For hotel items, location_name must come from the provided hotel research. "
        "For food or meal items, prefer restaurant POI names from the provided meal research. "
        "Do not invent specific restaurant POI names unless they are present in the provided research. "
        "If a day has meal candidates, choose from that day's candidates first. "
        "Only fall back to a stable area name already present in the research when no suitable restaurant candidate exists. "
        "Every daily item location_name must be copied exactly from one of these sources: "
        "selected_attractions.name/location.name, hotel candidates/recommended_hotel.name, "
        "meal day_candidates/general_candidates.name, or an explicitly provided recommended_night_area/nearby_area. "
        "Every daily item location_address must be copied exactly from the matching research location.address when available, otherwise leave it empty. "
        "Do not create new landmark, restaurant, hotel, street, station, or area names. "
        "Do not invent addresses. "
        "Do not output vague location names such as city center, old town, cultural district, shopping street, or scenic area unless that exact name appears in the research. "
        "Do not repeat the same attraction across different days unless the user explicitly asks to revisit it. "
        "Return strict JSON only."
    )

    def plan(
        self,
        request: TravelRequest,
        attractions: AttractionResearch,
        weather: WeatherResearch,
        hotels: HotelResearch,
        meals: MealResearch,
    ) -> TripPlan | None:
        prompt = f"""
Build the final trip plan using the research results below.

Travel request:
{request.model_dump_json(indent=2)}

Attraction research:
{attractions.model_dump_json(indent=2)}

Weather research:
{weather.model_dump_json(indent=2)}

Hotel research:
{hotels.model_dump_json(indent=2)}

Meal research:
{meals.model_dump_json(indent=2)}

Hard grounding rules:
- Copy all location_name values exactly from the research above.
- Copy location_address only from matching research location.address. If the address is unavailable, use an empty string.
- Do not invent any new POI, restaurant, hotel, street, station, or area name.
- Do not invent addresses.
- For each day, use only the attractions and meal candidates already provided.
- Do not repeat the same attraction across different days.
- Pace rule: relaxed usually means 1 core attraction per day, balanced means about 2 attractions per day, intense means up to 3 attractions per day.
- If there are not enough unique attractions for all days, leave later days lighter and explain it in notes; do not duplicate earlier attractions.
- If no real meal candidate fits, use an existing hotel nearby_area or recommended_night_area exactly as written.
- Keep transport items out of the JSON; the program will calculate transport routes after your plan.

Return JSON matching this shape:
{{
  "city": "{request.city}",
  "travel_theme": "string",
  "overview": "string",
  "trip_days": {request.trip_days},
  "selected_attractions": [],
  "recommended_hotel": null,
  "daily_plans": [
    {{
      "date": "{request.start_date.isoformat()}",
      "weather": {{
        "date": "{request.start_date.isoformat()}",
        "condition": "sunny",
        "high_c": 28,
        "low_c": 21,
        "suggestion": "string"
      }},
      "route_summary": "string",
      "items": [
        {{
          "time_range": "09:00-11:30",
          "title": "string",
          "item_type": "attraction",
          "location_name": "string",
          "location_address": "string",
          "summary": "string",
          "estimated_cost": 0.0,
          "reason": "string"
        }}
      ]
    }}
  ],
  "budget": {{
    "hotel": 0.0,
    "attractions": 0.0,
    "food": 0.0,
    "transport": 0.0,
    "contingency": 0.0,
    "total": 0.0
  }},
  "packing_tips": ["string"],
  "risk_alerts": ["string"],
  "notes": ["string"]
}}
"""
        data = self.run_json(prompt, max_tool_iterations=4)
        if data:
            try:
                return TripPlan.model_validate(data)
            except Exception:
                return None
        return None
