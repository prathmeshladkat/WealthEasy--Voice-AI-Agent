import asyncio 
import time
import numpy as mp
import torch
from app.utils.audio_utils import pcm_bytes_to_float32
from app.utils.logger import logger

VAD_THRESHOLD = 0.5
VAD_SAMPLE_RATE = 8000
VAD_WINDOW_SIZE_MS = 32
BARGE_IN_GRACE_PERIOD = 0.8

class VADTask:
    def __init__(
        self,
        audio_queue : asyncio.Queue,
        interrupt_event : asyncio.Event,
        is_agent_speaking_fn,
    ):
        self._audio_queue    = audio_queue
        self._interrupt_event = interrupt_event
        self._is_speaking_fn = is_agent_speaking_fn
        self._model          = None
        self._task: asyncio.Task | None = None
        self._speaking_since: float | None = None

        samples_per_ms       = VAD_SAMPLE_RATE // 1000
        self._window_samples = samples_per_ms * VAD_WINDOW_SIZE_MS   # 256 samples
        self._bytes_needed   = self._window_samples * 2              # 512 bytes (16-bit PCM)
 
        logger.info(
            f"VAD window: {VAD_WINDOW_SIZE_MS}ms = {self._window_samples} samples "
            f"| threshold={VAD_THRESHOLD}"
        )

    def notify_agent_started_speaking(self):
        """
        Call this whenever agent begins a new TTS response.
        """
        self._speaking_since = time.monotonic()

    def _load_model(self):
        logger.info("Loading silero VAD model...")
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model = "silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        model.eval()
        return model
        
    async def start(self):
        """Load the VAD model in a thread executor(blocking), then start the task."""
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(None, self._load_model)
        self._task = asyncio.create_task(self._run(), name="vad-task")
        logger.info("VAD task started.")

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("VAD task stopped.")

    
    async def _run(self):
        buffer      = b""
        log_counter = 0
 
        while True:
            try:
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
 
            buffer += chunk
 
            while len(buffer) >= self._bytes_needed:
                window_bytes = buffer[:self._bytes_needed]
                buffer       = buffer[self._bytes_needed:]
 
                audio_f32 = pcm_bytes_to_float32(window_bytes)
                tensor    = torch.from_numpy(audio_f32)
 
                try:
                    speech_prob = self._model(tensor, VAD_SAMPLE_RATE).item()
                except Exception as e:
                    logger.warning(f"VAD inference error: {e}")
                    continue
 
                is_speech      = speech_prob > VAD_THRESHOLD
                agent_speaking = self._is_speaking_fn()
 
                # Reset speaking_since when agent stops speaking
                if agent_speaking and self._speaking_since is None:
                    self._speaking_since = time.monotonic()
                elif not agent_speaking:
                    self._speaking_since = None
 
                # Log every 15 windows (~480ms) to avoid log spam
                log_counter += 1
                if log_counter % 15 == 0:
                    logger.debug(
                        f"VAD prob={speech_prob:.2f} | "
                        f"speech={is_speech} | "
                        f"agent_speaking={agent_speaking}"
                    )
 
                # Trigger barge-in if:
                #   - speech detected
                #   - agent is currently speaking
                #   - interrupt not already fired
                #   - grace period has elapsed
                if is_speech and agent_speaking and not self._interrupt_event.is_set():
                    grace_ok = (
                        self._speaking_since is None or
                        (time.monotonic() - self._speaking_since) >= BARGE_IN_GRACE_PERIOD
                    )
                    if grace_ok:
                        logger.info(f"VAD: BARGE-IN detected (prob={speech_prob:.2f})")
                        self._interrupt_event.set()
                    else:
                        elapsed = time.monotonic() - self._speaking_since
                        logger.debug(
                            f"VAD: suppressed (grace {elapsed:.2f}s < {BARGE_IN_GRACE_PERIOD}s)"
                        )