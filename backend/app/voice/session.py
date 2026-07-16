"""
voice/session.py — orchestrator for one live phone call.

Owns everything for the duration of a single call:
  - Verification state machine (GREETING → VERIFIED)
  - Conversation history (messages list for Groq)
  - All async tasks: VAD, STT, TTS, LLM, playback
  - Barge-in interrupt logic
  - Call log saving to DB

Key differences from previous project:
  - No ConversationManager class — history is a plain list here,
    state is owned by VerificationStateMachine + a simple AgentState enum
  - No scheduler context — verified user comes from state machine result
  - Transcripts route to state_machine FIRST (during verification),
    then to LLM only after VERIFIED state is reached
  - Intent classifier only runs in QUERY state
  - Call log is updated in Neon via SQLAlchemy (not raw asyncpg)
"""

import asyncio
import json
import time
from enum import Enum, auto
from typing import Optional

import httpx
from fastapi import WebSocket
from sqlalchemy import update

from app.config import settings
from app.database import async_session_factory
from app.models import CallLog
from app.utils.audio_utils import base64_to_mulaw, mulaw_to_pcm16
from app.utils.logger import logger
from app.voice.deepgram_client import DeepgramSTT
from app.voice.elevanlabs_client import ElevenLabsTTS
from app.voice.intent_classifier import classify_intent
from app.voice.llm_stream import (
    add_user_message,
    build_initial_messages,
    stream_llm_response,
)
from app.voice.state_machine import CallState, VerificationStateMachine
from app.voice.vad import VADTask
from app.worker.playback_worker import PlaybackWorker


# ── Agent speaking state ───────────────────────────────────────────────────────
# Separate from CallState — CallState tracks verification progress,
# AgentSpeakingState tracks whether audio is currently playing.

class AgentSpeakingState(Enum):
    IDLE     = auto()
    THINKING = auto()
    SPEAKING = auto()


class CallSession:

    def __init__(self, websocket: WebSocket, stream_sid: str, call_sid: str):
        self._ws         = websocket
        self._stream_sid = stream_sid
        self._call_sid   = call_sid
        self._started_at = time.monotonic()

        # ── Verification state machine ─────────────────────────────────────────
        self._state_machine  = VerificationStateMachine()
        self._verified_user  = None   # set after VERIFY_PAN succeeds
        self._call_log_id: Optional[int] = None

        # ── Conversation history for Groq ──────────────────────────────────────
        # Empty until VERIFIED — LLM is not called during verification
        self._messages: list[dict] = []
        self._current_assistant_text = ""

        # ── Agent speaking state ───────────────────────────────────────────────
        self._speaking_state     = AgentSpeakingState.IDLE
        self._interrupt_event    = asyncio.Event()
        self._call_ending        = False
        self._first_audio_sent   = False
        self._active_ctx_id: Optional[str] = None
        self._llm_task: Optional[asyncio.Task] = None
        self._interruption_count = 0

        # ── Audio queues ───────────────────────────────────────────────────────
        self._vad_audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

        # ── Components ─────────────────────────────────────────────────────────
        self._vad = VADTask(
            audio_queue          = self._vad_audio_queue,
            interrupt_event      = self._interrupt_event,
            is_agent_speaking_fn = self._is_agent_speaking,
        )
        self._playback = PlaybackWorker(websocket, stream_sid)
        self._playback.set_on_done(self._on_playback_done)

        self._stt = DeepgramSTT(
            on_transcript     = self._on_transcript,
            on_speech_started = self._on_speech_started,
        )
        self._tts = ElevenLabsTTS(
            on_audio_chunk  = self._on_tts_audio,
            on_context_done = self._on_tts_context_done,
        )

        self._tasks: list[asyncio.Task] = []
        self._broadcast = None

    def set_broadcast(self, fn):
        self._broadcast = fn

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self):
        logger.info(f"CallSession starting (stream={self._stream_sid})")

        # Create call log row — user_id is NULL until verified
        await self._create_call_log()

        await self._stt.connect()
        await self._tts.connect()
        await self._playback.start()
        await self._vad.start()

        self._tasks.append(
            asyncio.create_task(self._interrupt_watcher(), name="interrupt-watcher")
        )

        await self._emit("call_started", {"call_sid": self._call_sid})

        # Kick off greeting — moves state machine to VERIFY_PHONE
        result = self._state_machine.get_greeting()
        await self._speak(result.agent_message)

        logger.info("CallSession ready.")

    async def stop(self):
        logger.info("CallSession stopping...")

        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        await self._vad.stop()
        await self._playback.stop()
        await self._stt.disconnect()
        await self._tts.disconnect()

        duration = int(time.monotonic() - self._started_at)
        await self._save_call_log(duration=duration)

        await self._emit("call_ended", {"duration_seconds": duration})
        logger.info(f"CallSession ended. Duration={duration}s")

    # ── Twilio frame handler ───────────────────────────────────────────────────

    async def handle_frame(self, raw: str):
        """Called by twilio_handler for every incoming WebSocket message."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        if data.get("event") == "media":
            payload_b64 = data.get("media", {}).get("payload", "")
            if not payload_b64:
                return
            mulaw_bytes = base64_to_mulaw(payload_b64)
            pcm_bytes   = mulaw_to_pcm16(mulaw_bytes)
            await self._stt.send(mulaw_bytes)           # raw mulaw → Deepgram
            await self._vad_audio_queue.put(pcm_bytes)  # PCM → VAD

    # ── STT callbacks ──────────────────────────────────────────────────────────

    async def _on_speech_started(self):
        logger.debug("Speech started (Deepgram)")

    async def _on_transcript(self, text: str):
        """
        Called by Deepgram on every speech_final transcript.

        Routing logic:
          - During verification states → state machine handles it
          - During QUERY state         → LLM handles it
          - During ENDING              → ignore
        """
        if not text.strip() or self._call_ending:
            return

        logger.info(f"Transcript: '{text}'")
        await self._emit("transcript", {"role": "user", "text": text})

        current_state = self._state_machine.state

        # ── Verification states: state machine handles the transcript ──────────
        if current_state in (CallState.VERIFY_PHONE, CallState.VERIFY_PAN):
            # If agent is speaking, interrupt first
            if self._is_agent_speaking():
                await self._handle_interrupt()
            self._interrupt_event.clear()

            result = await self._state_machine.process_transcript(text)
            await self._speak(result.agent_message)

            if result.verified_user:
                # Verification succeeded — attach user to session
                self._verified_user = result.verified_user
                await self._attach_user_to_call_log(result.verified_user.id)
                await self._emit("verified", {
                    "user_id": result.verified_user.id,
                    "name"   : result.verified_user.name,
                })
                # Initialize LLM message history now that we're verified
                self._messages = build_initial_messages()
                # Move state machine to QUERY
                self._state_machine.state = CallState.QUERY

            if result.end_call:
                await self._schedule_hangup()

        # ── QUERY state: LLM handles the transcript ───────────────────────────
        elif current_state == CallState.QUERY:
            if self._is_agent_speaking():
                await self._handle_interrupt()
            elif self._llm_task and not self._llm_task.done():
                self._llm_task.cancel()
                await asyncio.gather(self._llm_task, return_exceptions=True)

            self._interrupt_event.clear()
            self._first_audio_sent   = False
            self._current_assistant_text = ""
            self._active_ctx_id      = await self._tts.new_context()
            self._speaking_state     = AgentSpeakingState.THINKING

            # Add user message to history and start LLM stream
            self._messages = add_user_message(self._messages, text)
            self._llm_task = asyncio.create_task(
                self._run_llm(), name="llm-task"
            )

    # ── LLM runner ─────────────────────────────────────────────────────────────

    async def _run_llm(self):
        """
        Runs the LLM stream, handles tool calls, sends sentences to TTS.
        Updates conversation history when done.
        """
        try:
            updated_messages = await stream_llm_response(
                messages      = self._messages,
                user_id       = self._verified_user.id,
                on_sentence   = self._on_llm_sentence,
                on_tool_start = self._on_tool_start,
            )
            # LLM finished — update history and close TTS context
            self._messages = updated_messages

            if not self._interrupt_event.is_set() and self._active_ctx_id:
                await self._tts.flush_context(self._active_ctx_id)
                await self._tts.close_context(self._active_ctx_id)

            # Run intent classifier to detect if user wants to end call
            if not self._call_ending and self._messages:
                last_user_msg = next(
                    (m["content"] for m in reversed(self._messages) if m["role"] == "user"),
                    ""
                )
                if last_user_msg:
                    intent = await classify_intent(last_user_msg)
                    await self._emit("intent", {"intent": intent})
                    if intent == "ENDING":
                        result = self._state_machine.set_ending()
                        await self._speak(result.agent_message)
                        await self._schedule_hangup()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"LLM task error: {e}", exc_info=True)


    async def _on_llm_sentence(self, sentence: str):
        """Called by stream_llm_response for each complete sentence."""
        if self._interrupt_event.is_set() or not self._active_ctx_id:
            return
        self._current_assistant_text += sentence + " "
        await self._tts.send_text(self._active_ctx_id, sentence)
        await self._emit("transcript", {"role": "assistant", "text": sentence})


    async def _on_tool_start(self, tool_name: str):
        """Called when LLM decides to call a tool — notify dashboard."""
        logger.info(f"Tool call: {tool_name}")
        await self._emit("tool_call", {"tool": tool_name})


    # ── TTS callbacks ──────────────────────────────────────────────────────────

    async def _on_tts_audio(self, pcm_bytes: bytes):
        """Audio chunk received from ElevenLabs — push to playback queue."""
        if self._interrupt_event.is_set():
            return
        if not self._first_audio_sent:
            self._first_audio_sent = True
            self._speaking_state   = AgentSpeakingState.SPEAKING
            self._vad.notify_agent_started_speaking()
            await self._emit("state_change", {"state": "SPEAKING"})
        await self._playback.put(pcm_bytes)


    async def _on_tts_context_done(self, context_id: str):
        """ElevenLabs finished sending audio for this context."""
        if context_id == self._active_ctx_id:
            await self._playback.put(None)   # sentinel: queue can fire on_done now


    async def _on_playback_done(self):
        """Playback queue fully drained — agent has actually finished speaking."""
        if self._is_agent_speaking():
            self._speaking_state = AgentSpeakingState.IDLE
            logger.info("Agent finished speaking → IDLE")
            await self._emit("state_change", {"state": "IDLE"})


    # ── Barge-in ───────────────────────────────────────────────────────────────

    def _is_agent_speaking(self) -> bool:
        return self._speaking_state == AgentSpeakingState.SPEAKING
    

    async def _handle_interrupt(self):
        self._interruption_count += 1
        logger.info(f"Barge-in #{self._interruption_count}")
        await self._emit("barge_in", {"count": self._interruption_count})

        if self._llm_task and not self._llm_task.done():
            self._llm_task.cancel()
            await asyncio.gather(self._llm_task, return_exceptions=True)

        if self._active_ctx_id:
            await self._tts.interrupt_context(self._active_ctx_id)
            self._active_ctx_id = None

        await self._playback.clear()
        self._current_assistant_text = ""
        self._speaking_state         = AgentSpeakingState.IDLE


    async def _interrupt_watcher(self):
        """Background task — watches interrupt_event set by VAD."""
        while True:
            try:
                await asyncio.sleep(0.01)
                if self._interrupt_event.is_set() and self._is_agent_speaking():
                    await self._handle_interrupt()
                    self._interrupt_event.clear()
            except asyncio.CancelledError:
                break


    # ── Speaking helper ────────────────────────────────────────────────────────

    async def _speak(self, text: str):
        """
        Speak any text directly via TTS — used for verification messages
        and closing lines (not streamed through LLM).
        """
        if not text.strip():
            return
        self._first_audio_sent = False
        ctx_id = await self._tts.new_context()
        self._active_ctx_id = ctx_id
        await self._tts.send_text(ctx_id, text, flush=True)
        await self._tts.close_context(ctx_id)


    # ── Hangup ─────────────────────────────────────────────────────────────────

    async def _schedule_hangup(self):
        """Wait for agent to finish speaking, then hang up."""
        self._call_ending = True
        await asyncio.sleep(3)   # let final message play out
        await self._hangup()


    async def _hangup(self):
        try:
            url = (
                f"https://api.twilio.com/2010-04-01/Accounts"
                f"/{settings.TWILIO_ACCOUNT_SID}/Calls/{self._call_sid}.json"
            )
            async with httpx.AsyncClient() as client:
                await client.post(
                    url,
                    auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                    data={"Status": "completed"},
                    timeout=5.0,
                )
            logger.info("Twilio hangup sent.")
        except Exception as e:
            logger.error(f"Hangup failed: {e}")
            

    # ── DB helpers ─────────────────────────────────────────────────────────────

    async def _create_call_log(self):
        """Insert a new call_log row when call starts. user_id is NULL until verified."""
        async with async_session_factory() as session:
            log = CallLog(
                call_sid   = self._call_sid,
                transcript = [],
                outcome    = None,
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            self._call_log_id = log.id
            logger.info(f"Call log created: id={self._call_log_id}")

    async def _attach_user_to_call_log(self, user_id: int):
        """Update call log with verified user_id after successful PAN verification."""
        if not self._call_log_id:
            return
        async with async_session_factory() as session:
            await session.execute(
                update(CallLog)
                .where(CallLog.id == self._call_log_id)
                .values(user_id=user_id)
            )
            await session.commit()

    async def _save_call_log(self, duration: int):
        """Save final transcript and outcome when call ends."""
        if not self._call_log_id:
            return
        outcome = "COMPLETED" if self._verified_user else "VERIFICATION_FAILED"
        async with async_session_factory() as session:
            await session.execute(
                update(CallLog)
                .where(CallLog.id == self._call_log_id)
                .values(
                    transcript              = self._messages,
                    outcome                 = outcome,
                    duration_seconds        = duration,
                    verification_attempts   = (
                        self._state_machine.phone_retries +
                        self._state_machine.pan_retries
                    ),
                )
            )
            await session.commit()

    # ── Dashboard broadcast ────────────────────────────────────────────────────

    async def _emit(self, event: str, data: dict):
        if self._broadcast:
            try:
                await self._broadcast({"event": event, **data})
            except Exception:
                pass