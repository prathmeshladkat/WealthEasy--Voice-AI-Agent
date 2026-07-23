"""
voice/livekit_agent.py — v1 voice pipeline using LiveKit as transport.
"""

import asyncio
import audioop
import sys
from typing import Optional

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
)

from app.config import settings
from app.utils.logger import logger
from app.voice.deepgram_client import DeepgramSTT
from app.voice.elevenlabs_client import ElevenLabsTTS
from app.voice.state_machine import CallState, VerificationStateMachine
from app.voice.llm_stream import (
    add_user_message,
    build_initial_messages,
    stream_llm_response,
)
from app.voice.intent_classifier import classify_intent
from app.broadcast import publish
from app.utils.latency_logger import LatencyTracker

# How long to wait, after a finalized transcript fragment, for MORE fragments
# before treating the utterance as complete. Only applies during VERIFY_PHONE /
# VERIFY_PAN — phone numbers and PANs are often spoken with pauses between
# groups of digits/letters, which Deepgram can (correctly) finalize as separate
# fragments. Without this, each fragment gets treated as the caller's full
# answer, causing early/incorrect verification failures.
VERIFY_DEBOUNCE_SECONDS = 1.2


class LiveKitCallSession:

    def __init__(self, ctx: JobContext):
        self._ctx        = ctx
        self._room       = ctx.room
        self._call_sid   = ctx.room.name
        self._started_at = asyncio.get_event_loop().time()

        self._state_machine = VerificationStateMachine()
        self._verified_user = None
        self._messages: list[dict] = []

        # AudioSource — push PCM frames here, LiveKit delivers to browser
        self._audio_source = rtc.AudioSource(
            sample_rate  = 8000,
            num_channels = 1,
        )
        self._audio_track: Optional[rtc.LocalAudioTrack] = None

        self._interrupt_event = asyncio.Event()
        self._is_speaking     = False
        self._call_ending     = False
        self._llm_task: Optional[asyncio.Task] = None
        self._active_ctx_id: Optional[str]     = None
        self._barge_in_count  = 0
        self._current_turn_tracker: Optional[LatencyTracker] = None  # LATENCY: tracks current turn

        # Debounce buffer for VERIFY_PHONE / VERIFY_PAN — see VERIFY_DEBOUNCE_SECONDS above.
        self._pending_verify_text = ""
        self._verify_debounce_task: Optional[asyncio.Task] = None

        # STT — will set encoding after seeing first frame
        # Start with linear16 since LiveKit gives us PCM
        self._stt = DeepgramSTT(
            on_transcript     = self._on_transcript,
            on_speech_started = self._on_speech_started,
            encoding          = "linear16",
            sample_rate       = 8000,
        )

        self._tts = ElevenLabsTTS(
            on_audio_chunk  = self._on_tts_audio,
            on_context_done = self._on_tts_context_done,
        )

    async def start(self):
        logger.info(f"LiveKit session starting (room={self._call_sid})")

        # Publish our audio track first
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            "aryan-voice", self._audio_source
        )
        await self._room.local_participant.publish_track(self._audio_track)
        logger.info("Audio track published to room")

        # Register event handlers
        self._room.on("track_subscribed",        self._on_track_subscribed)
        self._room.on("participant_disconnected", self._on_participant_disconnected)

        # Connect STT/TTS
        await self._stt.connect()
        await self._tts.connect()

        await publish({"event": "call_started", "call_sid": self._call_sid})

        # Speak greeting
        result = self._state_machine.get_greeting()
        await self._speak(result.agent_message)

        logger.info("LiveKit session ready.")

        # Start reading audio AFTER greeting so we don't process stale frames
        await self._subscribe_to_existing_tracks()

    async def _subscribe_to_existing_tracks(self):
        """Subscribe to any audio tracks already in the room."""
        for participant in self._room.remote_participants.values():
            logger.info(f"Checking participant: {participant.identity}")
            for track_pub in participant.track_publications.values():
                logger.info(f"Track: kind={track_pub.kind} subscribed={track_pub.subscribed} track={track_pub.track is not None}")
                if track_pub.track and track_pub.kind == rtc.TrackKind.KIND_AUDIO:
                    logger.info("Starting audio reader for existing track")
                    self._start_audio_reader(track_pub.track)

    def _start_audio_reader(self, track: rtc.Track):
        """Create AudioStream and start reading frames."""
        audio_stream = rtc.AudioStream(
            track,
            sample_rate  = 8000,
            num_channels = 1,
        )
        asyncio.create_task(
            self._read_audio_track(audio_stream),
            name="audio-reader"
        )

    async def stop(self):
        logger.info("LiveKit session stopping...")

        if self._llm_task and not self._llm_task.done():
            self._llm_task.cancel()
            await asyncio.gather(self._llm_task, return_exceptions=True)

        if self._verify_debounce_task and not self._verify_debounce_task.done():
            self._verify_debounce_task.cancel()
            await asyncio.gather(self._verify_debounce_task, return_exceptions=True)

        await self._stt.disconnect()
        await self._tts.disconnect()

        duration = int(asyncio.get_event_loop().time() - self._started_at)
        await publish({"event": "call_ended", "duration_seconds": duration})
        logger.info(f"LiveKit session ended. Duration={duration}s")

    # ── Track handling ─────────────────────────────────────────────────────────

    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Track subscribed from {participant.identity}")
            self._start_audio_reader(track)

    async def _read_audio_track(self, audio_stream: rtc.AudioStream):
        """
        Read PCM frames from LiveKit and send to Deepgram.
        Logs the first frame to confirm format.
        """
        logged_first = False
        try:
            async for event in audio_stream:
                if not isinstance(event, rtc.AudioFrameEvent):
                    continue

                frame = event.frame

                if not logged_first:
                    logged_first = True
                    logger.info(
                        f"First audio frame: sample_rate={frame.sample_rate} "
                        f"channels={frame.num_channels} "
                        f"samples={frame.samples_per_channel} "
                        f"bytes={len(frame.data)}"
                    )

                await self._stt.send(bytes(frame.data))

        except Exception as e:
            logger.error(f"Audio reader error: {e}", exc_info=True)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        logger.info(f"Participant disconnected: {participant.identity}")
        asyncio.create_task(self.stop())

    # ── STT callbacks ──────────────────────────────────────────────────────────

    async def _on_speech_started(self):
        logger.debug("Speech started (Deepgram)")

    async def _on_transcript(self, text: str):
        if not text.strip() or self._call_ending:
            return

        logger.info(f"Transcript: '{text}'")
        await publish({"event": "transcript", "role": "user", "text": text})

        current_state = self._state_machine.state

        if current_state in (CallState.VERIFY_PHONE, CallState.VERIFY_PAN):
            # Stop the agent talking immediately if the caller starts speaking —
            # this part should NOT wait for the debounce window.
            if self._is_speaking:
                await self._handle_interrupt()
            self._interrupt_event.clear()

            # LATENCY: only start a fresh timer on the FIRST fragment of a group —
            # if fragments are already pending, we're still timing the same turn.
            if not self._pending_verify_text:
                self._current_turn_tracker = LatencyTracker(
                    call_sid  = self._call_sid,
                    turn_type = current_state.name,
                )

            # Append this fragment and (re)start the debounce timer. Phone numbers
            # and PANs are frequently spoken with pauses between groups of digits/
            # letters — Deepgram can legitimately finalize each group separately.
            # We wait for a quiet gap before treating the utterance as complete,
            # instead of acting on the very first fragment.
            self._pending_verify_text = f"{self._pending_verify_text} {text}".strip()
            logger.debug(f"Verification fragment buffered: '{self._pending_verify_text}'")

            if self._verify_debounce_task and not self._verify_debounce_task.done():
                self._verify_debounce_task.cancel()
            self._verify_debounce_task = asyncio.create_task(
                self._debounced_verify(), name="verify-debounce"
            )
            return

        # LATENCY: start timing this turn NOW — this is the moment the caller's
        # speech became a usable transcript. Everything after this is "why is
        # the agent slow to respond", which is what we actually want to measure.
        self._current_turn_tracker = LatencyTracker(
            call_sid  = self._call_sid,
            turn_type = current_state.name,
        )

        if current_state == CallState.QUERY:
            if self._is_speaking:
                await self._handle_interrupt()
            elif self._llm_task and not self._llm_task.done():
                self._llm_task.cancel()
                await asyncio.gather(self._llm_task, return_exceptions=True)

            self._interrupt_event.clear()
            self._active_ctx_id = await self._tts.new_context()
            self._messages      = add_user_message(self._messages, text)
            if self._current_turn_tracker:
                self._current_turn_tracker.mark("llm_task_starting")  # LATENCY: about to call Groq
            self._llm_task      = asyncio.create_task(
                self._run_llm(), name="llm-task"
            )

    async def _debounced_verify(self):
        """
        Fires VERIFY_DEBOUNCE_SECONDS after the most recent transcript fragment
        arrived during VERIFY_PHONE / VERIFY_PAN. If another fragment shows up
        before this runs, _on_transcript cancels and reschedules this task, so
        this only actually executes once the caller has genuinely paused —
        meaning self._pending_verify_text holds the FULL spoken answer, not
        just whichever piece Deepgram happened to finalize first.
        """
        try:
            await asyncio.sleep(VERIFY_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return  # a newer fragment arrived — superseded, do nothing

        text = self._pending_verify_text.strip()
        self._pending_verify_text = ""
        if not text:
            return

        logger.info(f"Verification utterance complete (debounced): '{text}'")

        result = await self._state_machine.process_transcript(text)
        if self._current_turn_tracker:
            self._current_turn_tracker.mark("state_machine_done")  # LATENCY: DB lookup etc. done here
        await self._speak(result.agent_message)

        if result.verified_user:
            self._verified_user       = result.verified_user
            self._messages            = build_initial_messages()
            self._state_machine.state = CallState.QUERY
            await publish({
                "event"  : "verified",
                "user_id": result.verified_user.id,
                "name"   : result.verified_user.name,
            })

        if result.end_call:
            await self._schedule_hangup()

    # ── LLM runner ─────────────────────────────────────────────────────────────

    async def _run_llm(self):
        try:
            updated_messages = await stream_llm_response(
                messages      = self._messages,
                user_id       = self._verified_user.id,
                on_sentence   = self._on_llm_sentence,
                on_tool_start = self._on_tool_start,
            )
            self._messages = updated_messages

            if not self._interrupt_event.is_set() and self._active_ctx_id:
                await self._tts.flush_context(self._active_ctx_id)
                await self._tts.close_context(self._active_ctx_id)

            if not self._call_ending and self._messages:
                last_user_msg = next(
                    (m["content"] for m in reversed(self._messages) if m["role"] == "user"),
                    ""
                )
                if last_user_msg:
                    intent = await classify_intent(last_user_msg)
                    await publish({"event": "intent", "intent": intent})
                    if intent == "ENDING":
                        result = self._state_machine.set_ending()
                        await self._speak(result.agent_message)
                        await self._schedule_hangup()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"LLM task error: {e}", exc_info=True)

    async def _on_llm_sentence(self, sentence: str):
        if self._interrupt_event.is_set() or not self._active_ctx_id:
            return
        if self._current_turn_tracker and not any(
            s["stage"] == "first_llm_sentence" for s in self._current_turn_tracker._stages
        ):
            self._current_turn_tracker.mark("first_llm_sentence")  # LATENCY: Groq produced usable text
        await self._tts.send_text(self._active_ctx_id, sentence)
        await publish({"event": "transcript", "role": "assistant", "text": sentence})

    async def _on_tool_start(self, tool_name: str):
        logger.info(f"Tool call: {tool_name}")
        await publish({"event": "tool_call", "tool": tool_name})

    # ── TTS callbacks ──────────────────────────────────────────────────────────

    async def _on_tts_audio(self, audio_bytes: bytes):
        """ElevenLabs sends ulaw_8000 → convert to PCM → push to LiveKit."""
        if self._interrupt_event.is_set():
            return

        if not self._is_speaking:
            self._is_speaking = True
            await publish({"event": "state_change", "state": "SPEAKING"})
            # LATENCY: this is the moment the caller will actually start hearing
            # something — the real end-to-end number that matters to them.
            if self._current_turn_tracker:
                self._current_turn_tracker.mark("first_tts_audio_received")
                self._current_turn_tracker.flush()
                self._current_turn_tracker = None

        pcm_bytes = audioop.ulaw2lin(audio_bytes, 2)

        frame = rtc.AudioFrame(
            data                = pcm_bytes,
            sample_rate         = 8000,
            num_channels        = 1,
            samples_per_channel = len(pcm_bytes) // 2,
        )
        await self._audio_source.capture_frame(frame)

    async def _on_tts_context_done(self, context_id: str):
        if context_id == self._active_ctx_id:
            self._is_speaking = False
            await publish({"event": "state_change", "state": "IDLE"})
            logger.info("Agent finished speaking → IDLE")

    # ── Barge-in ───────────────────────────────────────────────────────────────

    async def _handle_interrupt(self):
        self._barge_in_count += 1
        logger.info(f"Barge-in #{self._barge_in_count}")
        await publish({"event": "barge_in", "count": self._barge_in_count})

        if self._llm_task and not self._llm_task.done():
            self._llm_task.cancel()
            await asyncio.gather(self._llm_task, return_exceptions=True)

        if self._active_ctx_id:
            await self._tts.interrupt_context(self._active_ctx_id)
            self._active_ctx_id = None

        self._is_speaking = False

    # ── Speak / hangup ─────────────────────────────────────────────────────────

    async def _speak(self, text: str):
        if not text.strip():
            return
        ctx_id = await self._tts.new_context()
        self._active_ctx_id = ctx_id
        await self._tts.send_text(ctx_id, text, flush=True)
        await self._tts.close_context(ctx_id)

    async def _schedule_hangup(self):
        self._call_ending = True
        await asyncio.sleep(3)
        await self._ctx.shutdown()


# ── Entrypoint ─────────────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    logger.info(f"Agent job received for room: {ctx.room.name}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")

    session = LiveKitCallSession(ctx)
    await session.start()

    shutdown_event = asyncio.Event()
    ctx.add_shutdown_callback(lambda: shutdown_event.set())
    await shutdown_event.wait()

    await session.stop()


# ── Worker startup ─────────────────────────────────────────────────────────────
# Run with: python -m app.voice.livekit_agent dev

if __name__ == "__main__":
    # psycopg needs SelectorEventLoop on Windows
    # Set before cli.run_app starts the event loop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())



    cli.run_app(
        WorkerOptions(
            entrypoint_fnc = entrypoint,
            api_key        = settings.LIVEKIT_API_KEY,
            api_secret     = settings.LIVEKIT_API_SECRET,
            ws_url         = settings.LIVEKIT_URL,
        )
    )