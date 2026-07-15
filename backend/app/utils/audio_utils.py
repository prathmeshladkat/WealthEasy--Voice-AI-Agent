
import audioop   # audioop-lts on Python 3.12+
import base64
import numpy as np
 
 
def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Convert µ-law bytes to 16-bit signed PCM bytes."""
    return audioop.ulaw2lin(mulaw_bytes, 2)
 
 
def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert 16-bit signed PCM bytes to µ-law bytes."""
    return audioop.lin2ulaw(pcm_bytes, 2)
 
 
def base64_to_mulaw(b64_str: str) -> bytes:
    """Decode base64 string from Twilio into raw µ-law bytes."""
    return base64.b64decode(b64_str)

def mulaw_to_twilio_payload(mulaw_bytes: bytes) -> str:
    """Convert raw mulaw bytes directly to base64 for Twilio — no conversion needed."""
    return base64.b64encode(mulaw_bytes).decode("utf-8")
 
 
def pcm16_to_twilio_payload(pcm_bytes: bytes) -> str:
    """
    Convert raw 16-bit PCM (from ElevenLabs pcm_8000) to
    base64 µ-law string ready to send back to Twilio.
    """
    mulaw = pcm16_to_mulaw(pcm_bytes)
    return base64.b64encode(mulaw).decode("utf-8")
 
 
def pcm_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """
    Convert 16-bit PCM bytes to float32 numpy array in [-1, 1].
    Used for Silero VAD input.
    """
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0
 
 
def chunk_audio(data: bytes, chunk_size: int) -> list[bytes]:
    """Split raw bytes into fixed-size chunks."""
    return [data[i: i + chunk_size] for i in range(0, len(data), chunk_size)]