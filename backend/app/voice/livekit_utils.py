"""
voice/livekit_utils.py — LiveKit token generation.

v0 equivalent: /token endpoint generated a Twilio access token
  so the browser could authenticate with Twilio's WebRTC infrastructure.

v1: we generate a LiveKit access token so the browser can join a room.
  Same concept — short-lived JWT granting permission to join a specific room.

Flow:
  1. User clicks "Call" in browser
  2. Browser calls GET /livekit/token
  3. We create a unique room name + generate a token for it
  4. Browser joins that room using the token + LiveKit URL
  5. LiveKit sees participant joined → dispatches job to our worker
  6. Worker calls entrypoint() → joins same room → conversation starts
"""

import uuid
from livekit.api import AccessToken, VideoGrants
from app.config import settings


def generate_livekit_token(participant_name: str = "user") -> dict:
    """
    Generate a LiveKit access token for a browser participant.

    Returns token, room_name, and livekit_url so the frontend
    has everything it needs to connect.

    room_name uses UUID so two simultaneous callers never share a room.
    """
    room_name = f"wealtheasy-{uuid.uuid4().hex[:8]}"

    token = (
        AccessToken(
            api_key    = settings.LIVEKIT_API_KEY,
            api_secret = settings.LIVEKIT_API_SECRET,
        )
        .with_identity(participant_name)
        .with_name(participant_name)
        .with_grants(
            VideoGrants(
                room_join = True,
                room      = room_name,
            )
        )
        .to_jwt()
    )

    return {
        "token"      : token,
        "room_name"  : room_name,
        "livekit_url": settings.LIVEKIT_URL,
    }