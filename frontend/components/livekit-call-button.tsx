'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { Phone, PhoneOff, Loader2 } from 'lucide-react';
import {
  Room,
  RoomEvent,
  Track,
  createLocalAudioTrack,
  ConnectionState,
} from 'livekit-client';

type CallStatus = 'idle' | 'loading' | 'connected' | 'error';

const SERVER_URL = process.env.NEXT_PUBLIC_WS_URL
  ? process.env.NEXT_PUBLIC_WS_URL
      .replace('ws://', 'http://')
      .replace('wss://', 'https://')
      .replace('/dashboard/ws', '')
  : 'http://localhost:8000';

export function LiveKitCallButton() {
  const [status, setStatus]   = useState<CallStatus>('idle');
  const [error, setError]     = useState<string | null>(null);
  const roomRef               = useRef<Room | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      roomRef.current?.disconnect();
    };
  }, []);

  const makeCall = useCallback(async () => {
    setStatus('loading');
    setError(null);

    try {
      // Step 1 — get token from our backend
      // v0: fetched Twilio token from /token
      // v1: fetch LiveKit token from /livekit/token
      const res  = await fetch(`${SERVER_URL}/livekit/token`);
      const data = await res.json();

      const { token, room_name, livekit_url } = data;

      // Step 2 — create LiveKit room
      // v0: Twilio.Device handled all WebRTC internally
      // v1: we create a Room object and connect explicitly
      const room = new Room({
        audioCaptureDefaults: {
          echoCancellation  : true,
          noiseSuppression  : true,
          autoGainControl   : true,
        },
      });
      roomRef.current = room;

      // Step 3 — listen for room events
      room.on(RoomEvent.Connected, () => {
        setStatus('connected');
      });

      room.on(RoomEvent.Disconnected, () => {
        setStatus('idle');
        roomRef.current = null;
      });

      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
          if (track.kind === Track.Kind.Audio) {
            // Attach the agent's audio track to the DOM so browser plays it
            const audioElement = track.attach();
            audioElement.autoplay = true;
            document.body.appendChild(audioElement);
          }
        });

        room.on(RoomEvent.TrackUnsubscribed, (track) => {
          if (track.kind === Track.Kind.Audio) {
            track.detach();
          }
        });

      room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
        if (state === ConnectionState.Reconnecting) {
          setStatus('loading');
        }
      });

      // Step 4 — connect to the room
      // This triggers LiveKit to dispatch a job to our Python worker
      await room.connect(livekit_url, token);

      // Step 5 — publish microphone track
      // v0: Twilio JS SDK captured mic automatically
      // v1: we explicitly create and publish a local audio track
      const audioTrack = await createLocalAudioTrack();
      await room.localParticipant.publishTrack(audioTrack);

    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setError(msg);
      setStatus('error');
    }
  }, []);

  const hangUp = useCallback(async () => {
    document.querySelectorAll('audio').forEach(el => el.remove());
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
    }
    setStatus('idle');
  }, []);

  if (status === 'idle') {
    return (
      <button
        onClick={makeCall}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-success/20 border border-success/40 text-success text-xs font-mono hover:bg-success/30 transition-colors"
      >
        <Phone className="w-3.5 h-3.5" />
        Call Aryan
      </button>
    );
  }

  if (status === 'loading') {
    return (
      <button
        disabled
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-warning/20 border border-warning/40 text-warning text-xs font-mono cursor-not-allowed"
      >
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Connecting...
      </button>
    );
  }

  if (status === 'connected') {
    return (
      <button
        onClick={hangUp}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/20 border border-destructive/50 text-destructive text-xs font-mono hover:bg-destructive/30 transition-colors animate-pulse"
      >
        <PhoneOff className="w-3.5 h-3.5" />
        Hang Up
      </button>
    );
  }

  if (status === 'error') {
    return (
      <button
        onClick={() => setStatus('idle')}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/20 border border-destructive/40 text-destructive text-xs font-mono hover:bg-destructive/30 transition-colors"
        title={error || 'Error'}
      >
        Error — Retry
      </button>
    );
  }

  return null;
}