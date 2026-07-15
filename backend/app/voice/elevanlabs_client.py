"""
Protocol:
  1. Connect once — persistent connection for the whole call
  2. Per agent turn: open a new context_id
  3. Stream text chunks into that context
  4. flush=True when LLM is done sending text
  5. close_context=True when done OR on barge-in interrupt
"""

import asyncio
import base64
import json
import uuid
import websockets
from typing import Callable, Awaitable

from app.config import settings
from app.utils.logger import logger


WS_URL = (
    f"wss://api.elevenlabs.io/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}"
    f"/multi-stream-input"
    f"?model_id=eleven_flash_v2_5"
    f"&output_format=ulaw_8000"
    f"&inactivity_timeout=180"
)

VOICE_SETTINGS = {
    "stability"       : 0.5,
    "similarity_boost": 0.8,
    "speed"           : 1.0,
}


class ElevenLabsTTS:
    """
    Persistent Multi-Context WebSocket TTS connection.

    Each agent turn gets a unique context_id.
    Barge-in = interrupt_context() → generation stops immediately.
    """

    def __init__(
        self,
        on_audio_chunk  : Callable[[bytes], Awaitable[None]],
        on_context_done : Callable[[str], Awaitable[None]] | None = None,
    ):
        self._on_audio_chunk  = on_audio_chunk
        self._on_context_done = on_context_done
        self._ws              = None
        self._recv_task: asyncio.Task | None = None
        self._connected       = False
        self._active_ctx: str | None = None

    async def connect(self):
        headers = {"xi-api-key": settings.ELEVENLABS_API_KEY}
        self._ws = await websockets.connect(
            WS_URL,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=10,
            logger=None,
        )
        self._connected = True
        self._recv_task = asyncio.create_task(
            self._receive_loop(), name="elevenlabs-recv"
        )
        logger.info("ElevenLabs TTS connected (multi-context).")

    async def disconnect(self):
        self._connected = False
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        logger.info("ElevenLabs TTS disconnected.")

    # ── Context lifecycle ──────────────────────────────────────────────────────

    async def new_context(self) -> str:
        """Open a new generation context for one agent turn."""
        ctx_id = str(uuid.uuid4())
        self._active_ctx = ctx_id
        await self._send({
            "context_id"    : ctx_id,
            "text"          : " ",           # required non-empty init text
            "voice_settings": VOICE_SETTINGS,
        })
        logger.debug(f"ElevenLabs: new_context {ctx_id[:8]}")
        return ctx_id

    async def send_text(self, ctx_id: str, text: str, flush: bool = False):
        """Send a text chunk into an active context."""
        if not text.strip():
            return
        msg = {"context_id": ctx_id, "text": text}
        if flush:
            msg["flush"] = True
        await self._send(msg)

    async def flush_context(self, ctx_id: str):
        """Force-generate any buffered text in this context."""
        await self._send({"context_id": ctx_id, "flush": True})

    async def close_context(self, ctx_id: str):
        """Cleanly close context after all text has been sent."""
        await self._send({"context_id": ctx_id, "close_context": True})
        logger.debug(f"ElevenLabs: close_context {ctx_id[:8]}")

    async def interrupt_context(self, ctx_id: str):
        """Immediately stop generation — called on barge-in."""
        if not ctx_id:
            return
        logger.info(f"ElevenLabs: interrupt {ctx_id[:8]}")
        await self._send({"context_id": ctx_id, "close_context": True})
        self._active_ctx = None

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _send(self, msg: dict):
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps(msg))
            except Exception as e:
                logger.error(f"ElevenLabs send error: {e}")

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                ctx_id = msg.get("context_id") or msg.get("contextId", "")

                if msg.get("audio"):
                    audio = base64.b64decode(msg["audio"])
                    await self._on_audio_chunk(audio)

                if msg.get("isFinal") is True or msg.get("is_final") is True:
                    logger.debug(f"ElevenLabs: context done {ctx_id[:8] if ctx_id else '?'}")
                    if self._on_context_done:
                        await self._on_context_done(ctx_id)

        except websockets.ConnectionClosed as e:
            logger.warning(f"ElevenLabs WS closed: {e.code}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"ElevenLabs receive loop error: {e}")