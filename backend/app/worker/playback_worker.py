"""
worker/playback_worker.py — dequeues PCM audio chunks and sends to Twilio.

The ONLY place that writes audio back to Twilio.
Runs at a fixed 20ms pace to match Twilio's expected stream timing.

Two important signals:
  - None sentinel in queue = ElevenLabs finished this context
  - clear() = barge-in happened, drain everything immediately

on_done callback tells session when audio has ACTUALLY finished
playing — not just when ElevenLabs finished sending it. This is
how session.py knows to set agent state back to IDLE accurately.
"""

import asyncio
import json
import time
from typing import Callable, Awaitable

from app.utils.audio_utils import pcm16_to_twilio_payload
from app.utils.logger import logger
from app.utils.audio_utils import mulaw_to_twilio_payload

PLAYBACK_INTERVAL_MS  = 20    # send one chunk every 20ms — matches Twilio stream timing
PLAYBACK_CHUNK_BYTES  = 160   # 20ms of 8kHz mulaw audio = 160 bytes


class PlaybackWorker:

    def __init__(self, twilio_ws, stream_sid: str):
        self._ws         = twilio_ws
        self._stream_sid = stream_sid
        self._is_playing = False
        self._on_done: Callable[[], Awaitable[None]] | None = None
        self._task: asyncio.Task | None = None

        # asyncio.Queue holds PCM chunks (bytes) or None sentinel
        # None = ElevenLabs context finished, check if queue is drained
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def set_on_done(self, callback: Callable[[], Awaitable[None]]):
        """
        Register callback fired when playback queue fully drains.
        Session uses this to set agent state → IDLE at the right moment.
        """
        self._on_done = callback

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    async def start(self):
        self._task = asyncio.create_task(self._run(), name="playback-worker")
        logger.info("Playback worker started.")

    async def stop(self):
        await self.clear()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Playback worker stopped.")

    async def put(self, pcm_chunk: bytes | None):
        """Push a PCM chunk (or None sentinel) onto the queue."""
        await self.queue.put(pcm_chunk)

    async def clear(self):
        """
        Drain queue immediately and send Twilio clear event.
        Called on barge-in — stops audio mid-playback.

        Two things happen:
          1. Our queue is emptied (no more chunks will be sent)
          2. Twilio is told to clear its own buffer (stops audio already sent)
        """
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._is_playing = False

        try:
            await self._ws.send_text(
                json.dumps({"event": "clear", "streamSid": self._stream_sid})
            )
        except Exception as e:
            logger.warning(f"Playback: failed to send Twilio clear: {e}")

        logger.debug("Playback queue cleared + Twilio clear sent.")

    async def _run(self):
        interval   = PLAYBACK_INTERVAL_MS / 1000.0   # 0.02 seconds
        chunk_size = PLAYBACK_CHUNK_BYTES             # 160 bytes per send

        while True:
            try:
                chunk = await asyncio.wait_for(self.queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Queue was empty for 500ms — if we were playing, we're done
                if self._is_playing:
                    self._is_playing = False
                    if self._on_done:
                        await self._on_done()
                continue
            except asyncio.CancelledError:
                break

            # None sentinel = ElevenLabs finished sending this context
            if chunk is None:
                if self.queue.empty():
                    # Queue fully drained — playback complete
                    self._is_playing = False
                    if self._on_done:
                        await self._on_done()
                continue

            self._is_playing = True

            # Split chunk into 160-byte sub-chunks and send each with 20ms pacing
            for i in range(0, len(chunk), chunk_size):
                sub = chunk[i: i + chunk_size]
                if not sub:
                    continue

                payload = mulaw_to_twilio_payload(sub)
                msg = json.dumps({
                    "event"    : "media",
                    "streamSid": self._stream_sid,
                    "media"    : {"payload": payload},
                })

                start = time.monotonic()
                try:
                    await self._ws.send_text(msg)
                except Exception as e:
                    logger.warning(f"Playback send error: {e}")
                    break

                # Sleep for remainder of 20ms window after accounting for send time
                elapsed   = time.monotonic() - start
                sleep_for = max(0.0, interval - elapsed)
                await asyncio.sleep(sleep_for)