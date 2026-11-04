"""Authenticated loopback UI. Presentation cards require an explicit idempotent Run POST."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import secrets
import threading
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.demo_ui.state import TERMINAL

STATIC=Path(__file__).with_name("static")


class Login(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    token: str=Field(min_length=32,max_length=128,pattern=r"^[A-Za-z0-9_-]+$")


class RunRequest(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    card: str=Field(pattern=r"^D0[1-5]$")
    request_id: str=Field(pattern=r"^[0-9a-f]{32}$")


def create_app(controller, token, *, port=8091):
    if len(token)<32:raise ValueError("strong_ui_run_token_required")
    sessions={};failures=[];streams=threading.BoundedSemaphore(16)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(controller.close)
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    hosts={f"127.0.0.1:{port}",f"localhost:{port}"}

    @app.middleware("http")
    async def boundary(request,call_next):
        actual_hosts=[v.decode() for k,v in request.scope["headers"] if k==b"host"]
        if len(actual_hosts)!=1 or actual_hosts[0] not in hosts:
            return JSONResponse(dict(error="localhost_host_required"),status_code=401)
        host=actual_hosts[0]; origin=request.headers.get("origin")
        if (origin is not None and origin!="http://"+host) or (request.method=="POST" and origin is None):
            return JSONResponse(dict(error="same_origin_required"),status_code=403)
        if request.method not in {"GET","POST"}:
            return JSONResponse(dict(error="unsupported_method"),status_code=405)
        if request.method=="POST":
            if request.headers.get("transfer-encoding") or request.headers.get("content-type","").split(";")[0]!="application/json":
                return JSONResponse(dict(error="bounded_json_required"),status_code=400)
            length=request.headers.get("content-length","")
            if not length.isdigit() or not 0<int(length)<=4096:
                return JSONResponse(dict(error="request_too_large"),status_code=413)
            if len(await request.body())>4096:
                return JSONResponse(dict(error="request_too_large"),status_code=413)
        response=await call_next(request)
        response.headers.update({"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY",
            "Referrer-Policy":"no-referrer","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    def authorize(request, *, write=False):
        session=sessions.get(request.cookies.get("live_demo_session",""))
        if session is None or session["expires"]<time.monotonic():raise HTTPException(401,"ui_session_required")
        if write and not hmac.compare_digest(request.headers.get("x-demo-csrf","").encode(),session["csrf"].encode()):
            raise HTTPException(403,"csrf_required")
        return session

    @app.get("/")
    def index():return FileResponse(STATIC/"index.html")

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in {"app.js","style.css"}:raise HTTPException(404)
        return FileResponse(STATIC/name)

    @app.post("/api/live/session")
    def login(body: Login):
        now=time.monotonic();failures[:]=[value for value in failures if now-value<60]
        if len(failures)>=8:raise HTTPException(429,"too_many_failed_logins")
        if not hmac.compare_digest(body.token,token):
            failures.append(now);raise HTTPException(401,"invalid_ui_token")
        for key in list(sessions):
            if sessions[key]["expires"]<now:del sessions[key]
        if len(sessions)>=32:raise HTTPException(429,"too_many_sessions")
        key=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        sessions[key]=dict(expires=now+8*3600,csrf=csrf)
        response=JSONResponse(dict(csrf=csrf))
        response.set_cookie("live_demo_session",key,httponly=True,samesite="strict",max_age=8*3600)
        return response

    @app.get("/api/live/status")
    def status(request: Request):
        session=authorize(request)
        return dict(controller.status(),csrf=session["csrf"])

    @app.post("/api/live/runs")
    def run(body: RunRequest,request: Request):
        authorize(request,write=True)
        try:job=controller.start(body.card,body.request_id)
        except RuntimeError as exc:raise HTTPException(409,str(exc)) from None
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        return JSONResponse(job.snapshot(),status_code=202)

    def find(request,run_id):
        authorize(request)
        try:return controller.get(run_id)
        except KeyError:raise HTTPException(404,"unknown_run") from None

    @app.get("/api/live/runs/{run_id}")
    def result(request: Request,run_id: str):return find(request,run_id).snapshot()

    @app.get("/api/live/runs/{run_id}/events")
    async def events(request: Request,run_id: str,after: int=0):
        job=find(request,run_id)
        if not 0<=after<=10000:raise HTTPException(400,"invalid_event_sequence")
        try:last=int(request.headers.get("last-event-id","0"))
        except ValueError:raise HTTPException(400,"invalid_event_sequence") from None
        if not 0<=last<=10000:raise HTTPException(400,"invalid_event_sequence")
        after=max(after,last)
        if not streams.acquire(blocking=False):raise HTTPException(429,"event_stream_limit")
        async def stream():
            cursor=after;last_heartbeat=time.monotonic()
            try:
                while not await request.is_disconnected():
                    rows=job.page(cursor)
                    for row in rows:
                        cursor=row["sequence"]
                        yield f"id: {cursor}\nevent: observation\ndata: {json.dumps(row)}\n\n"
                    snapshot=job.snapshot()
                    if snapshot["phase"] in TERMINAL and not rows:
                        yield "event: complete\ndata: {}\n\n";break
                    if time.monotonic()-last_heartbeat>10:
                        yield ": keepalive\n\n";last_heartbeat=time.monotonic()
                    await asyncio.sleep(.2)
            finally:streams.release()
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})
    return app
