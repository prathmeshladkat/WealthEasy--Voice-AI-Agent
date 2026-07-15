import asyncio
import json
import websockets
from typing import Callable, Awaitable
 
from app.config import settings
from app.utils.logger import logger
 
 
DEEPGRAM_WSS_URL = (
    f"wss://api.deepgram.com/v1/listen"
    f"?model=nova-3"
    f"&encoding=mulaw"
    f"&sample_rate=8000"
    f"&channels=1"
    f"&punctuate=true"
    f"&smart_format=true"
    f"&interim_results=true"
    f"&utterance_end_ms=1000"
    f"&vad_events=true"
    f"&endpointing=300"
)

class DeepgramSTT:
    def __init__(
            self,
            on_transcript  : Callable[[str], Awaitable[None]],
            on_speech_started : Callable[[], Awaitable[None]] | None = None,
    ):
        self._on_transcript = on_transcript
        self._on_speech_started = on_speech_started
        self._ws                = None
        self._recv_task: asyncio.Task | None = None
        self._connected         = False

    async def connect(self):
        headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"}
        self._ws = await websockets.connect(
            DEEPGRAM_WSS_URL,
            extra_headers=headers,
            ping_interval=10,
            ping_timeout=5,
            logger=None,
        )
        self._connected = True
        self._recv_task = asyncio.create_task(
            self._receive_loop(), name="deepgram-recv"
        )
        logger.info("Deepgram STT connected.")

    async def send(self, audio_bytes: bytes):
        """Send raw mulaw audio bytes to Deepgram"""
        if self._ws and self._connected and audio_bytes:
            try:
                await self._ws.send(audio_bytes)
            except Exception as e:
                logger.warning(f"Deepgram send error: {e}")

    async def disconnect(self):
        """Gracefully close the Deepgram connection"""
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
        """Parse incoming Deepgram JSON messages"""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "Results":
                    try:
                        transcript = msg["channel"]["alternatives"][0]["transcript"].strip()
                        speech_final = msg.get("speech_final", False)
                    except (KeyError, IndexError):
                        continue

                    if not transcript:
                        continue

                    if speech_final:
                        logger.info(f"Deepgram final: '{transcript}'")
                        await self._on_transcript(transcript)

                elif msg_type == "sppechStarted":
                    logger.debug("Deepgram: Sppechstarted")
                    if self._on_speech_started:
                        await self._on_speech_started()

                elif msg_type == "Metadata":
                    logger.debug(f"Deepgram metadata: {msg.get('request_id', '')}")
 
                elif msg_type == "Error":
                    logger.error(f"Deepgram error: {msg}")

        except websockets.ConnectionClosed as e:
            logger.info(f"Deepgram connection closed: {e.code}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram receive loop error: {e}")