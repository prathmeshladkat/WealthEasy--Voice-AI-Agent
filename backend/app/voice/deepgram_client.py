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

        # Accumulates finalized (is_final=True) transcript pieces for the CURRENT
        # utterance. Needed because UtteranceEnd carries no transcript text itself —
        # it's just a timestamp saying "speech has ended". So we keep the last
        # finalized text around and hand it over the moment either speech_final=True
        # OR UtteranceEnd tells us the utterance is actually complete.
        self._utterance_buffer  = ""
        self._utterance_dispatched = False  # guards against firing twice for one utterance

    async def connect(self):
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
        self._connected = True   # ← was missing
        self._recv_task = asyncio.create_task(
            self._receive_loop(), name="deepgram-recv"
        )   # ← was missing
        logger.info("Deepgram STT connected.")

    async def send(self, audio_bytes: bytes):
        if self._ws and self._connected and audio_bytes:
            try:
                await self._ws.send(audio_bytes)
                self._audio_chunks_sent += 1
                # DEBUG: heartbeat every ~2s of audio (100 frames @ 20ms) so we can
                # confirm audio is flowing continuously, including during "silent" attempts
                if self._audio_chunks_sent % 100 == 0:
                    logger.info(f"[DG-DEBUG] audio flowing: {self._audio_chunks_sent} chunks sent to Deepgram so far")
            except Exception as e:
                logger.warning(f"Deepgram send error: {e}")
        else:
            logger.warning(f"Deepgram send SKIPPED: ws={self._ws is not None} connected={self._connected} bytes={len(audio_bytes) if audio_bytes else 0}")

    async def disconnect(self):
        self._connected = False

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

                # DEBUG: log every single message type Deepgram sends, so we can see
                # exactly what happens between attempts (not just the final one)
                logger.info(f"[DG-DEBUG] msg #{self._msg_counter} type={msg_type} raw_keys={list(msg.keys())}")

                if msg_type == "Results":
                    try:
                        transcript   = msg["channel"]["alternatives"][0]["transcript"].strip()
                        is_final     = msg.get("is_final", False)      # end of this chunk of audio
                        speech_final = msg.get("speech_final", False)  # end of the whole utterance
                    except (KeyError, IndexError):
                        continue

                    # DEBUG: log EVERY Results message with a transcript, interim or not,
                    # so we can see partial recognition even when speech_final never fires
                    if transcript:
                        logger.info(
                            f"[DG-DEBUG] transcript='{transcript}' "
                            f"is_final={is_final} speech_final={speech_final}"
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
                    logger.info(f"[DG-DEBUG] UtteranceEnd received: {msg}")

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
                f"[DG-DEBUG] Deepgram websocket CLOSED unexpectedly: code={e.code} reason={e.reason} "
                f"— no auto-reconnect exists, all further audio sends will silently fail from here on"
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram receive loop error: {e}")