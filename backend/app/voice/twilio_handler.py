"""
voice/twilio_handler.py — FastAPI WebSocket route for Twilio Media Streams.

One function: twilio_ws_handler()
  - Accepts the WebSocket connection from Twilio
  - Waits for the "start" event to get stream_sid and call_sid
  - Creates a CallSession and hands all frames to it
  - Cleans up when connection closes

This file knows nothing about verification, LLM, or tools.
It just receives raw frames and passes them to the session.
"""

import json

from fastapi import WebSocket, WebSocketDisconnect

from app.utils.logger import logger
from app.voice.session import CallSession


async def twilio_ws_handler(websocket: WebSocket, broadcast_fn=None):
    await websocket.accept()
    logger.info("Twilio WebSocket connected.")

    session: CallSession | None = None

    try:
        async for raw_message in websocket.iter_text():
            try:
                data = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event = data.get("event")

            if event == "connected":
                logger.info("Twilio: connected event received.")

            elif event == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid") or data.get("streamSid", "")
                call_sid   = start_data.get("callSid", "unknown")

                logger.info(f"Twilio: stream started (callSid={call_sid} streamSid={stream_sid})")

                session = CallSession(
                    websocket  = websocket,
                    stream_sid = stream_sid,
                    call_sid   = call_sid,
                )

                if broadcast_fn:
                    session.set_broadcast(broadcast_fn)

                await session.start()

            elif event == "media":
                if session:
                    await session.handle_frame(raw_message)

            elif event == "stop":
                logger.info("Twilio: stop event received.")
                break

    except WebSocketDisconnect:
        logger.info("Twilio WebSocket disconnected.")
    except Exception as e:
        logger.error(f"Twilio WS error: {e}", exc_info=True)
    finally:
        if session:
            await session.stop()
        logger.info("Twilio handler exited.")