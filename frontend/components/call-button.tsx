'use client';

import { useState, useEffect, useRef } from 'react';
import { Phone, PhoneOff, Loader2 } from 'lucide-react';

type CallStatus = 'idle' | 'loading' | 'ready' | 'calling' | 'connected' | 'error';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/dashboard/ws';
const SERVER_URL = WS_URL.replace('ws://', 'http://').replace('wss://', 'https://').replace('/dashboard/ws', '');

declare global {
  interface Window {
    Twilio: {
      Device: new (token: string, options?: object) => TwilioDevice;
    };
  }
}

interface TwilioDevice {
  on: (event: string, cb: (...args: unknown[]) => void) => void;
  register: () => void;
  connect: () => Promise<TwilioCall>;
  disconnectAll: () => void;
}

interface TwilioCall {
  on: (event: string, cb: (...args: unknown[]) => void) => void;
  disconnect: () => void;
}

export function CallButton() {
  const [status, setStatus]   = useState<CallStatus>('idle');
  const [error, setError]     = useState<string | null>(null);
  const deviceRef             = useRef<TwilioDevice | null>(null);
  const callRef               = useRef<TwilioCall | null>(null);

  useEffect(() => {
    // Wait for Twilio SDK to load then set up device
    const init = async () => {
      setStatus('loading');
      try {
        // Poll until Twilio SDK is available
        await waitForTwilio();

        const res   = await fetch(`${SERVER_URL}/token`);
        const data  = await res.json();

        const device = new window.Twilio.Device(data.token, {
          logLevel: 1,
          codecPreferences: ['opus', 'pcmu'],
        });

        device.on('registered', () => setStatus('ready'));
        device.on('error', (err: unknown) => {
          const e = err as { message: string };
          setError(e.message);
          setStatus('error');
        });

        device.register();
        deviceRef.current = device;
      } catch (e) {
        setError('Failed to initialize. Check server.');
        setStatus('error');
      }
    };

    init();

    return () => {
      deviceRef.current?.disconnectAll();
    };
  }, []);

  const waitForTwilio = (): Promise<void> =>
    new Promise((resolve, reject) => {
      let attempts = 0;
      const check = setInterval(() => {
        attempts++;
        if (window.Twilio?.Device) {
          clearInterval(check);
          resolve();
        }
        if (attempts > 20) {
          clearInterval(check);
          reject(new Error('Twilio SDK not loaded'));
        }
      }, 300);
    });

  const makeCall = async () => {
    if (!deviceRef.current) return;
    setStatus('calling');
    try {
      const call = await deviceRef.current.connect();
      callRef.current = call;

      call.on('accept', () => setStatus('connected'));
      call.on('disconnect', () => {
        callRef.current = null;
        setStatus('ready');
      });
      call.on('error', () => setStatus('ready'));
    } catch {
      setStatus('ready');
    }
  };

  const hangUp = () => {
    callRef.current?.disconnect();
    callRef.current = null;
    setStatus('ready');
  };

  // Button variants
  if (status === 'idle' || status === 'loading') {
    return (
      <button
        disabled
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-muted/30 border border-border text-muted-foreground text-xs font-mono cursor-not-allowed"
      >
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Initializing...
      </button>
    );
  }

  if (status === 'error') {
    return (
      <button
        disabled
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/20 border border-destructive/40 text-destructive text-xs font-mono cursor-not-allowed"
        title={error || 'Error'}
      >
        Error
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

  if (status === 'calling') {
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

  // Ready state
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