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
from app.voice.livekit_utils import generate_livekit_token


# ── Dashboard WebSocket connections ───────────────────────────────────────────
# Keeps track of all open dashboard browser connections.
# When a call event happens (barge-in, transcript, tool call etc.)
# we broadcast it to every connected dashboard tab.





    


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
    allow_origins=[
        "http://localhost:3000",
        "https://wealth-easy-voice-ai-agent.vercel.app",  # no trailing slash — browsers never send one in the Origin header, so a mismatched trailing slash silently blocks every request
    ],
    # allow_origins only does exact string matches — it has no wildcard support,
    # so "https://*.ngrok-free.dev" as a list entry would never actually match a
    # real ngrok URL. allow_origin_regex is the correct place for pattern matching.
    allow_origin_regex=r"https://.*\.ngrok-free\.dev",
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

@app.get("/livekit/token")
async def livekit_token():
    return generate_livekit_token()


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
    await twilio_ws_handler(websocket) 


@app.websocket("/dashboard/ws")
async def dashboard_ws(websocket: WebSocket):
    import asyncio
    import redis.asyncio as redis
    from app.config import settings

    await websocket.accept()
    logger.info("Dashboard WebSocket connected")

    # Create a separate Redis connection for pub/sub
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("wealtheasy:dashboard")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    await websocket.send_text(message["data"])
                except Exception:
                    break
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe("wealtheasy:dashboard")
        await r.aclose()
        logger.info("Dashboard WebSocket disconnected")
# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host    = "0.0.0.0",
        port    = 8000,
        reload  = True,     # auto-restart on file changes during development
    )