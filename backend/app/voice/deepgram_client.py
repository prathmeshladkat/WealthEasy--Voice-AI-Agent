import asyncio
import json
import websockets
from typing import Callable, Awaitable

from app.config import settings
from app.utils.logger import logger


class DeepgramSTT:
    def __init__(
        self,
        on_transcript    : Callable[[str], Awaitable[None]],
        on_speech_started: Callable[[], Awaitable[None]] | None = None,
        encoding         : str = "mulaw",   # v0 default: mulaw (from Twilio)
        sample_rate      : int = 8000,      # v1 LiveKit: linear16 at 8000
    ):
        self._on_transcript     = on_transcript
        self._on_speech_started = on_speech_started
        self._encoding          = encoding      # ← was missing
        self._sample_rate       = sample_rate   # ← was missing
        self._ws                = None
        self._recv_task: asyncio.Task | None = None
        self._connected         = False
        self._audio_chunks_sent = 0   # DEBUG: total send() calls since connect
        self._msg_counter       = 0   # DEBUG: total messages received from Deepgram

        # Reconnection state. Without this, ANY websocket drop (network blip,
        # keepalive ping timeout, Deepgram-side hiccup) leaves the agent
        # permanently unable to hear the caller for the rest of the call —
        # confirmed in production via repeated "Deepgram send error" warnings
        # with no recovery. _should_run distinguishes "connection dropped,
        # please reconnect" from "disconnect() was called on purpose, stop".
        self._should_run        = False
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_attempt = 0

        # Accumulates finalized (is_final=True) transcript pieces for the CURRENT
        # utterance. Needed because UtteranceEnd carries no transcript text itself —
        # it's just a timestamp saying "speech has ended". So we keep the last
        # finalized text around and hand it over the moment either speech_final=True
        # OR UtteranceEnd tells us the utterance is actually complete.
        self._utterance_buffer  = ""
        self._utterance_dispatched = False  # guards against firing twice for one utterance

    async def connect(self):
        self._should_run = True
        await self._do_connect()

    async def _do_connect(self):
        """The actual connection logic — used for both the initial connect()
        and every reconnect attempt, so they can never drift out of sync."""
        url = (
            f"wss://api.deepgram.com/v1/listen"
            f"?model=nova-3"
            f"&encoding={self._encoding}"
            f"&sample_rate={self._sample_rate}"
            f"&channels=1"
            f"&punctuate=true"
            f"&smart_format=true"
            f"&interim_results=true"
            f"&utterance_end_ms=1000"
            f"&vad_events=true"
            f"&endpointing=300"
        )
        headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"}
        self._ws = await websockets.connect(
            url,
            extra_headers=headers,
            ping_interval=10,
            ping_timeout=5,
            logger=None,
        )
        self._connected = True

        # A stale recv_task from a previous (now-dead) connection should
        # already have exited on its own, but cancel defensively just in case.
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()

        self._recv_task = asyncio.create_task(
            self._receive_loop(), name="deepgram-recv"
        )
        # Fresh connection = fresh utterance state. Anything buffered from
        # before the drop is unrecoverable audio anyway, so start clean.
        self._utterance_buffer     = ""
        self._utterance_dispatched = False
        self._reconnect_attempt    = 0
        logger.info("Deepgram STT connected.")

    def _trigger_reconnect(self):
        """
        Idempotent — safe to call from many places at once (send() can fail
        dozens of times per second while offline; we only want ONE reconnect
        loop running at a time, not one per failed send).
        """
        if not self._should_run:
            return  # a deliberate disconnect() is in progress/done, not a drop
        self._connected = False
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(
                self._reconnect_loop(), name="deepgram-reconnect"
            )

    async def _reconnect_loop(self):
        """
        Retries with capped exponential backoff (0.5s, 1s, 2s, 4s, 5s, 5s, ...)
        until either reconnection succeeds or disconnect() is called.
        Audio arriving during this gap is dropped (send() SKIPPED warnings) —
        a brief gap mid-call is far better than the previous behavior of
        being permanently deaf for the rest of the call.
        """
        backoff     = 0.5
        max_backoff = 5.0

        while self._should_run and not self._connected:
            self._reconnect_attempt += 1
            logger.warning(
                f"Deepgram reconnecting (attempt #{self._reconnect_attempt}), "
                f"waiting {backoff:.1f}s..."
            )
            await asyncio.sleep(backoff)

            if not self._should_run:
                return  # disconnect() was called while we were waiting

            try:
                await self._do_connect()
                logger.info(
                    f"Deepgram reconnected successfully after "
                    f"{self._reconnect_attempt} attempt(s)."
                )
                return
            except Exception as e:
                logger.warning(
                    f"Deepgram reconnect attempt #{self._reconnect_attempt} failed: {e}"
                )
                backoff = min(backoff * 2, max_backoff)

    async def send(self, audio_bytes: bytes):
        if self._ws and self._connected and audio_bytes:
            try:
                await self._ws.send(audio_bytes)
                self._audio_chunks_sent += 1
                if self._audio_chunks_sent == 1:
                    # One-time sanity check: confirms audio format/size reaching
                    # Deepgram is what we expect (16-bit PCM = 2 bytes/sample).
                    logger.info(f"First audio chunk sent to Deepgram: {len(audio_bytes)} bytes")
            except Exception as e:
                logger.warning(f"Deepgram send error: {e}")
                self._trigger_reconnect()
        else:
            logger.warning(f"Deepgram send SKIPPED: ws={self._ws is not None} connected={self._connected} bytes={len(audio_bytes) if audio_bytes else 0}")

    async def disconnect(self):
        self._should_run = False  # tells any in-flight reconnect loop to stop retrying
        self._connected  = False

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await asyncio.sleep(0.1)
            except Exception:
                pass

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

        logger.info("Deepgram STT disconnected.")

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                self._msg_counter += 1

                if msg_type == "Results":
                    try:
                        transcript   = msg["channel"]["alternatives"][0]["transcript"].strip()
                        is_final     = msg.get("is_final", False)      # end of this chunk of audio
                        speech_final = msg.get("speech_final", False)  # end of the whole utterance
                    except (KeyError, IndexError):
                        continue

                    # Every fragment (interim or final) logged at debug — visible if you
                    # need to dig into a specific call, silent in normal operation.
                    if transcript:
                        logger.debug(
                            f"transcript='{transcript}' is_final={is_final} speech_final={speech_final}"
                        )

                    # Remember every finalized chunk of THIS utterance. Deepgram can
                    # finalize a long utterance in more than one is_final=True piece
                    # (e.g. if the caller pauses mid-number), so we append rather than
                    # overwrite. Interim (is_final=False) text is not stored — only
                    # confirmed/final pieces count toward what we'd hand to the app.
                    if transcript and is_final:
                        self._utterance_buffer = (
                            f"{self._utterance_buffer} {transcript}".strip()
                        )
                        self._utterance_dispatched = False

                    if not transcript:
                        continue

                    if speech_final:
                        # Normal path: Deepgram told us directly this utterance is done.
                        final_text = self._utterance_buffer or transcript
                        logger.info(f"Deepgram final: '{final_text}'")
                        self._utterance_buffer     = ""
                        self._utterance_dispatched = True
                        await self._on_transcript(final_text)

                elif msg_type == "UtteranceEnd":
                    # Backup path per Deepgram's own docs: this fires when Deepgram is
                    # confident speech has ended, even if no Results message ever set
                    # speech_final=True (this is common, not an edge case — confirmed
                    # by our own logs where a fully-correct transcript was recognized
                    # but only ever reached us via this event, never via speech_final).
                    logger.debug(f"UtteranceEnd received: {msg}")

                    if self._utterance_buffer and not self._utterance_dispatched:
                        final_text = self._utterance_buffer
                        logger.info(f"Deepgram final (via UtteranceEnd): '{final_text}'")
                        self._utterance_buffer     = ""
                        self._utterance_dispatched = True
                        await self._on_transcript(final_text)

                elif msg_type == "SpeechStarted":   # ← fixed typo
                    logger.debug("Deepgram: SpeechStarted")
                    if self._on_speech_started:
                        await self._on_speech_started()

                elif msg_type == "Metadata":
                    logger.debug(f"Deepgram metadata: {msg.get('request_id', '')}")

                elif msg_type == "Error":
                    logger.error(f"Deepgram error: {msg}")

        except websockets.ConnectionClosed as e:
            logger.warning(
                f"Deepgram websocket CLOSED unexpectedly: code={e.code} reason={e.reason}"
            )
            self._trigger_reconnect()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram receive loop error: {e}")