"""
app/utils/latency_logger.py — per-turn latency tracking.

Problem this solves:
  You can SEE that the agent feels slow to respond, but not WHERE the time
  goes — Deepgram finalizing, a DB lookup, Groq/LLM generation, ElevenLabs
  TTS, or audio actually reaching the caller. Sprinkling print()s doesn't
  give you clean numbers you can compare turn to turn or share.

How it works:
  1. Create one LatencyTracker at the moment you have the final transcript
     (i.e. the instant on_transcript fires) — that's t0 for this turn.
  2. Call .mark("stage_name") at each checkpoint as the turn progresses.
     Each mark records BOTH total elapsed time since t0 AND time since the
     previous mark, so you can see which single step ate the most time.
  3. Call .flush() once, when the agent's audio actually starts playing
     back (the moment the caller would perceive as "it responded").
     This appends ONE line of JSON to logs/latency.log.

Usage:
    from app.utils.latency_logger import LatencyTracker

    # when a transcript is finalized:
    tracker = LatencyTracker(call_sid=self._call_sid, turn_type="VERIFY_PHONE")

    # ... after DB lookup / state machine work ...
    tracker.mark("state_machine_done")

    # ... after TTS new_context() call ...
    tracker.mark("tts_context_opened")

    # ... on the FIRST audio chunk received from ElevenLabs for this turn ...
    tracker.mark("first_tts_audio_received")
    tracker.flush()   # writes the line, call is done being tracked

Output (logs/latency.log — one line per turn, easy to paste/share):
    {"call_sid": "CAxxxx", "turn_type": "VERIFY_PHONE", "stages": [
        {"stage": "state_machine_done", "since_start_ms": 420.1, "since_prev_ms": 420.1},
        {"stage": "tts_context_opened", "since_start_ms": 455.3, "since_prev_ms": 35.2},
        {"stage": "first_tts_audio_received", "since_start_ms": 1380.7, "since_prev_ms": 925.4}
    ], "total_ms": 1380.7}

Reading it:
  - Big jump between "state_machine_done" and "tts_context_opened"?  -> TTS/network is slow to start.
  - Big jump between "tts_context_opened" and "first_tts_audio_received"? -> ElevenLabs generation itself is slow.
  - Big jump before "state_machine_done" even appears (i.e. total_ms already
    high for the FIRST mark)? -> the DB lookup / LLM call itself is slow.
"""

import json
import time
from pathlib import Path
from typing import Optional

from app.utils.logger import logger

_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "latency.log"


class LatencyTracker:
    """One instance per conversational turn. Not thread-safe across turns —
    create a fresh one for every new user utterance / agent response cycle."""

    def __init__(self, call_sid: str, turn_type: str):
        self.call_sid   = call_sid
        self.turn_type  = turn_type
        self._t0        = time.monotonic()
        self._last      = self._t0
        self._stages: list[dict] = []
        self._flushed   = False

    def mark(self, stage: str) -> float:
        """Record a checkpoint. Returns elapsed ms since turn start."""
        now              = time.monotonic()
        since_start_ms   = (now - self._t0) * 1000
        since_prev_ms    = (now - self._last) * 1000
        self._last       = now
        self._stages.append({
            "stage"         : stage,
            "since_start_ms": round(since_start_ms, 1),
            "since_prev_ms" : round(since_prev_ms, 1),
        })
        return since_start_ms

    def flush(self):
        """Write this turn's full timeline as one JSON line to logs/latency.log."""
        if self._flushed:
            return
        self._flushed = True

        total_ms = (time.monotonic() - self._t0) * 1000
        record = {
            "call_sid" : self.call_sid,
            "turn_type": self.turn_type,
            "stages"   : self._stages,
            "total_ms" : round(total_ms, 1),
        }

        try:
            _LOG_DIR.mkdir(exist_ok=True)
            with open(_LOG_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[latency] failed to write latency log: {e}")

        # Also surface it in the normal logs immediately, so you don't have
        # to open the file mid-call to sanity check.
        logger.info(f"[LATENCY] {self.turn_type} total={record['total_ms']}ms "
                     f"stages={[(s['stage'], s['since_prev_ms']) for s in self._stages]}")