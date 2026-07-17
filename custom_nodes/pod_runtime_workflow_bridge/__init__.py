from __future__ import annotations

import time
from typing import Any

from aiohttp import web
from server import PromptServer

WEB_DIRECTORY = "./web"
_CURRENT: dict[str, Any] | None = None


@PromptServer.instance.routes.post("/pod_runtime/workflow_bridge/current")
async def publish_current_workflow(request: web.Request) -> web.Response:
    global _CURRENT
    try:
        payload = await request.json()
    except Exception as error:
        return web.json_response({"error": f"invalid JSON: {error}"}, status=400)

    workflow = payload.get("workflow") if isinstance(payload, dict) else None
    if not isinstance(workflow, dict):
        return web.json_response({"error": "payload.workflow must be an object"}, status=400)

    _CURRENT = {
        "workflow": workflow,
        "client_id": str(payload.get("client_id", "")),
        "title": str(payload.get("title", "")),
        "browser_url": str(payload.get("browser_url", "")),
        "published_at": str(payload.get("published_at", "")),
        "received_unix": time.time(),
    }
    return web.json_response({"ok": True})


@PromptServer.instance.routes.get("/pod_runtime/workflow_bridge/current")
async def get_current_workflow(_request: web.Request) -> web.Response:
    if _CURRENT is None:
        return web.json_response(
            {
                "error": "No browser has published an active workflow yet. Open ComfyUI, focus the desired tab, and retry."
            },
            status=404,
        )

    response = dict(_CURRENT)
    response["age_seconds"] = max(0.0, time.time() - float(response["received_unix"]))
    return web.json_response(response)


NODE_CLASS_MAPPINGS: dict[str, type] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}
