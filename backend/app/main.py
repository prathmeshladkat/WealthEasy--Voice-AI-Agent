"""
main.py — FastAPI application entrypoint.

Three responsibilities:
  1. Startup: verify DB + Redis connections, confirm app is healthy
  2. Routes:
       POST /voice/incoming  → Twilio webhook (tells Twilio to open media stream)
       WS   /voice/stream    → Twilio media stream WebSocket (actual audio)
       GET  /health          → quick health check
  3. Dashboard WebSocket broadcasting (real-time events to frontend)

Twilio call flow:
  1. Incoming call hits your Twilio number
  2. Twilio sends POST to /voice/incoming
  3. We respond with TwiML telling Twilio to open a media stream
  4. Twilio opens WebSocket to /voice/stream
  5. CallSession takes over from there
"""

import asyncio
import selectors
import sys

# psycopg requires SelectorEventLoop on Windows
# Must be set before uvicorn starts — uvicorn inherits this policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.DefaultEventLoopPolicy()
    )
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)

import json
from contextlib import asynccontextmanager
from typing import Set

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from app.cache import check_redis_connection
from app.config import settings
from app.database import check_db_connection
from app.utils.logger import logger
from app.voice.twilio_handler import twilio_ws_handler
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware


# ── Dashboard WebSocket connections ───────────────────────────────────────────
# Keeps track of all open dashboard browser connections.
# When a call event happens (barge-in, transcript, tool call etc.)
# we broadcast it to every connected dashboard tab.

_dashboard_connections: Set[WebSocket] = set()


async def broadcast(event: dict):
    """Send a JSON event to all connected dashboard WebSocket clients."""
    if not _dashboard_connections:
        return
    message = json.dumps(event)
    dead    = set()
    for ws in _dashboard_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    _dashboard_connections -= dead


# ── Lifespan ───────────────────────────────────────────────────────────────────
# FastAPI lifespan replaces the old @app.on_event("startup") pattern.
# Everything before `yield` runs on startup, everything after runs on shutdown.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info("WealthEasy backend starting...")

    logger.info("Checking Neon Postgres connection...")
    db_ok = await check_db_connection()
    if not db_ok:
        raise RuntimeError("Cannot connect to Neon Postgres. Check DATABASE_URL.")
    logger.info("Neon Postgres OK.")

    logger.info("Checking Upstash Redis connection...")
    redis_ok = await check_redis_connection()
    if not redis_ok:
        raise RuntimeError("Cannot connect to Upstash Redis. Check REDIS_URL.")
    logger.info("Upstash Redis OK.")

    logger.info("WealthEasy backend ready.")

    yield   # app runs here

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("WealthEasy backend shutting down.")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title    = "WealthEasy Voice Agent",
    version  = "1.0.0",
    lifespan = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.ngrok-free.dev"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Quick health check — useful for ngrok/deployment verification."""
    return {"status": "ok", "service": "WealthEasy Voice Agent"}


@app.get("/token")
async def get_token():
    token = AccessToken(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_API_KEY,
        settings.TWILIO_API_SECRET,
        identity="test-user",
    )
    grant = VoiceGrant(outgoing_application_sid=settings.TWILIO_TWIML_APP_SID)
    token.add_grant(grant)
    return {"token": token.to_jwt()}

@app.get("/dialer")
async def dialer():
    return FileResponse("dialer.html")


@app.post("/voice/incoming", response_class=PlainTextResponse)
async def voice_incoming(request: Request):
    """
    Twilio webhook — called when someone dials your Twilio number.

    We respond with TwiML that tells Twilio to:
      1. Connect to our /voice/stream WebSocket
      2. Send bidirectional audio over that stream

    TwiML is just XML — no SDK needed.
    The stream URL must be a wss:// (WebSocket Secure) URL pointing
    to our /voice/stream endpoint. In dev this is your ngrok URL.
    """
    stream_url = f"wss://{request.headers.get('host', '')}/voice/stream"
    logger.info(f"Incoming call → streaming to {stream_url}")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="encoding" value="audio/x-mulaw"/>
        </Stream>
    </Connect>
</Response>"""

    return PlainTextResponse(content=twiml, media_type="text/xml")


@app.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket):
    """
    Twilio media stream WebSocket.
    Hands off to twilio_ws_handler which creates a CallSession.
    Passes the broadcast function so call events reach the dashboard.
    """
    await twilio_ws_handler(websocket, broadcast_fn=broadcast)


@app.websocket("/dashboard/ws")
async def dashboard_ws(websocket: WebSocket):
    """
    Dashboard WebSocket — browser connects here to receive real-time events.
    Events: call_started, transcript, barge_in, tool_call, state_change,
            verified, intent, call_ended.
    """
    await websocket.accept()
    _dashboard_connections.add(websocket)
    logger.info(f"Dashboard connected. Total: {len(_dashboard_connections)}")

    try:
        # Keep connection alive — browser sends pings, we just wait
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _dashboard_connections.discard(websocket)
        logger.info(f"Dashboard disconnected. Total: {len(_dashboard_connections)}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host    = "0.0.0.0",
        port    = 8000,
        reload  = True,     # auto-restart on file changes during development
    )