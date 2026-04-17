import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
import requests


class ModeReq(BaseModel):
    mode: str


class ColorReq(BaseModel):
    preset: str


class DriveReq(BaseModel):
    l: int
    r: int


class TuneReq(BaseModel):
    kp: Optional[float] = None
    ki: Optional[float] = None
    kd: Optional[float] = None
    base_speed: Optional[int] = None
    target_area: Optional[int] = None


class SelectTargetReq(BaseModel):
    index: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None


class ServoReq(BaseModel):
    pan: Optional[int] = None
    tilt: Optional[int] = None


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(vision, motors, servos=None):
    app = FastAPI(title="smart-car brain")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    brain_token = os.environ.get("BRAIN_TOKEN", "").strip()

    def require_token(
        x_brain_token: Optional[str] = Header(default=None),
        authorization: Optional[str] = Header(default=None),
    ):
        if not brain_token:
            return
        supplied = x_brain_token
        if not supplied and authorization and authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        if supplied != brain_token:
            raise HTTPException(401, "invalid or missing brain token")

    ws_clients: list[WebSocket] = []

    async def _broadcast():
        while True:
            if ws_clients:
                snap = dict(vision.status)
                snap["stream_url"] = "/stream"
                data = json.dumps(snap)
                dead = []
                for ws in ws_clients:
                    try:
                        await ws.send_text(data)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    ws_clients.remove(ws)
            await asyncio.sleep(0.05)

    @app.on_event("startup")
    async def _startup():
        asyncio.create_task(_broadcast())

    @app.websocket("/ws")
    async def websocket_status(ws: WebSocket, token: Optional[str] = Query(default=None)):
        if brain_token and token != brain_token:
            await ws.close(code=1008)
            return
        await ws.accept()
        ws_clients.append(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if ws in ws_clients:
                ws_clients.remove(ws)

    def _proxied_stream_url(request: Request) -> str:
        base = str(request.base_url).rstrip("/")
        return f"{base}/stream"

    @app.get("/api/health")
    def health():
        return {"ok": True, "auth": bool(brain_token)}

    @app.get("/status")
    def status(request: Request):
        s = dict(vision.status)
        s["stream_url"] = _proxied_stream_url(request)
        return s

    @app.get("/stream")
    def stream_proxy():
        upstream = vision.cam_url
        try:
            r = requests.get(upstream, stream=True, timeout=(5, None))
        except requests.RequestException as e:
            raise HTTPException(502, f"camera unreachable: {e}")
        if r.status_code != 200:
            r.close()
            raise HTTPException(502, f"camera returned {r.status_code}")
        content_type = r.headers.get(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame"
        )

        def gen():
            try:
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            finally:
                r.close()

        return StreamingResponse(gen(), media_type=content_type)

    @app.post("/mode", dependencies=[Depends(require_token)])
    def set_mode(req: ModeReq):
        try:
            vision.set_mode(req.mode)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "mode": vision.mode}

    @app.post("/color", dependencies=[Depends(require_token)])
    def set_color(req: ColorReq):
        try:
            vision.set_color(req.preset)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "color": vision.color}

    @app.post("/drive", dependencies=[Depends(require_token)])
    def drive(req: DriveReq):
        vision.manual_drive(req.l, req.r)
        return {"ok": True}

    @app.post("/stop", dependencies=[Depends(require_token)])
    def stop():
        motors.stop()
        return {"ok": True}

    @app.post("/select_target", dependencies=[Depends(require_token)])
    def select_target(req: SelectTargetReq):
        vision.select_target(index=req.index, x=req.x, y=req.y)
        return {"ok": True}

    @app.get("/tune")
    def get_tune():
        return {
            "kp": vision.kp, "ki": vision.ki, "kd": vision.kd,
            "base_speed": vision.base_speed,
            "target_area": vision.target_area,
        }

    @app.post("/tune", dependencies=[Depends(require_token)])
    def set_tune(req: TuneReq):
        if req.kp is not None:
            vision.kp = max(0.0, min(2.0, req.kp))
        if req.ki is not None:
            vision.ki = max(0.0, min(0.5, req.ki))
        if req.kd is not None:
            vision.kd = max(0.0, min(1.0, req.kd))
        if req.base_speed is not None:
            vision.base_speed = max(0, min(255, req.base_speed))
        if req.target_area is not None:
            vision.target_area = max(500, min(100000, req.target_area))
        return get_tune()

    @app.get("/intel")
    def get_intel():
        return vision.intel.get_report()

    @app.post("/servo", dependencies=[Depends(require_token)])
    def move_servo(req: ServoReq):
        if servos is None:
            raise HTTPException(503, "no servo board configured")
        pan  = max(0, min(180, req.pan))  if req.pan  is not None else None
        tilt = max(0, min(180, req.tilt)) if req.tilt is not None else None
        cur = servos.status()
        servos.move(pan if pan is not None else cur["pan"],
                    tilt if tilt is not None else cur["tilt"])
        return servos.status()

    @app.post("/servo/center", dependencies=[Depends(require_token)])
    def center_servo():
        if servos is None:
            raise HTTPException(503, "no servo board configured")
        servos.center()
        return servos.status()

    @app.get("/servo/status")
    def servo_status():
        if servos is None:
            return {"pan": 90, "tilt": 90, "connected": False}
        s = servos.status()
        s["connected"] = True
        return s

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
