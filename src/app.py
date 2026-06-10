from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import BASE_DIR, STATIC_DIR, ensure_data_dirs, get_settings
from src.models import HealthResponse, TravelRequest, TripPlan
from src.services.planner import TravelPlannerService


settings = get_settings()
ensure_data_dirs()
planner = TravelPlannerService()
planner_lock = threading.Lock()
PLAN_TASK_TTL_SECONDS = 30 * 60


@dataclass
class PlanTask:
    request: TravelRequest
    events: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    created_at: float = field(default_factory=time.monotonic)
    status: str = "pending"
    result: TripPlan | None = None
    error: str = ""


plan_tasks: dict[str, PlanTask] = {}
plan_tasks_lock = threading.Lock()

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    response = planner.health()
    if planner.settings.amap_key:
        response.available_tools.append("live_amap")
    if planner.settings.qweather_key:
        response.available_tools.append("live_qweather")
    return response


@app.post("/api/plan", response_model=TripPlan)
def create_trip_plan(request: TravelRequest) -> TripPlan:
    try:
        with planner_lock:
            return planner.build_trip_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/plan/tasks")
def create_plan_task(request: TravelRequest) -> dict[str, str]:
    _cleanup_plan_tasks()
    task_id = uuid.uuid4().hex
    task = PlanTask(request=request)
    with plan_tasks_lock:
        plan_tasks[task_id] = task

    thread = threading.Thread(target=_run_plan_task, args=(task_id,), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.get("/api/plan/stream/{task_id}")
def stream_plan_task(task_id: str) -> StreamingResponse:
    with plan_tasks_lock:
        task = plan_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="规划任务不存在或已过期。")

    return StreamingResponse(_event_stream(task_id, task), media_type="text/event-stream")


def _run_plan_task(task_id: str) -> None:
    with plan_tasks_lock:
        task = plan_tasks[task_id]

    task.status = "running"
    task.events.put(
        {
            "event": "progress",
            "data": {
                "stage": "queued",
                "percent": 3,
                "title": "任务已创建",
                "detail": "后端已经收到请求，正在准备启动旅行规划链路。",
            },
        }
    )

    def publish_progress(payload: dict[str, Any]) -> None:
        task.events.put({"event": "progress", "data": payload})

    try:
        with planner_lock:
            result = planner.build_trip_plan(task.request, progress_callback=publish_progress)
        task.result = result
        task.status = "completed"
        task.events.put(
            {
                "event": "complete",
                "data": {
                    "percent": 100,
                    "title": "旅行计划生成完成",
                    "detail": "报告、预算、路线和风险提醒已经整理好。",
                    "plan": result.model_dump(mode="json"),
                },
            }
        )
    except ValueError as exc:
        task.status = "failed"
        task.error = str(exc)
        task.events.put({"event": "failed", "data": {"detail": str(exc)}})
    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)
        task.events.put({"event": "failed", "data": {"detail": f"暂时无法生成这份行程：{exc}"}})


def _event_stream(task_id: str, task: PlanTask) -> Iterator[str]:
    try:
        yield _format_sse("progress", {"stage": "connected", "percent": 5, "title": "已连接进度通道", "detail": "正在等待后端阶段更新。"})
        while True:
            try:
                message = task.events.get(timeout=15)
            except queue.Empty:
                yield _format_sse("heartbeat", {"status": task.status})
                continue

            event_name = str(message.get("event") or "message")
            data = message.get("data") or {}
            yield _format_sse(event_name, data)

            if event_name in {"complete", "failed"}:
                break
    finally:
        with plan_tasks_lock:
            plan_tasks.pop(task_id, None)


def _format_sse(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _cleanup_plan_tasks() -> None:
    now = time.monotonic()
    with plan_tasks_lock:
        expired = [
            task_id
            for task_id, task in plan_tasks.items()
            if now - task.created_at > PLAN_TASK_TTL_SECONDS
        ]
        for task_id in expired:
            plan_tasks.pop(task_id, None)


app.mount("/", StaticFiles(directory=STATIC_DIR or BASE_DIR / "static", html=True), name="static")
