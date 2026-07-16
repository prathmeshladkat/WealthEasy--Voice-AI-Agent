'use client';

import { useRef, useEffect } from 'react';
import { AlertCircle, CheckCircle, Phone } from 'lucide-react';
import type { TranscriptMessage } from '@/hooks/useDashboardWebSocket';

interface LiveTranscriptPanelProps {
  messages  : TranscriptMessage[];
  callActive: boolean;
}

export function LiveTranscriptPanel({ messages, callActive }: LiveTranscriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="bg-card border border-border rounded-lg p-6 space-y-4 h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
          Live Transcript
        </h2>
        {callActive && (
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
            <span className="text-xs text-success font-mono">LIVE</span>
          </div>
        )}
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="space-y-3 h-[420px] overflow-y-auto pr-1"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full space-y-2 text-muted-foreground">
            <Phone className="w-8 h-8 opacity-20" />
            <p className="text-xs">Transcript will appear here during a call</p>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`flex animate-fade-in-up ${
                message.type === 'system'
                  ? 'justify-center'
                  : message.type === 'user'
                  ? 'justify-start'
                  : 'justify-end'
              }`}
            >
              {/* System message */}
              {message.type === 'system' && (
                <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/30 border border-border rounded-full text-xs max-w-xs">
                  {message.text.includes('✓') || message.text.includes('verified') ? (
                    <CheckCircle className="w-3 h-3 text-success flex-shrink-0" />
                  ) : (
                    <AlertCircle className="w-3 h-3 text-primary flex-shrink-0" />
                  )}
                  <span className="text-muted-foreground font-mono truncate">
                    {message.text}
                  </span>
                </div>
              )}

              {/* User (caller) message */}
              {message.type === 'user' && (
                <div className="max-w-[75%] space-y-1">
                  <span className="text-xs text-muted-foreground ml-1">Caller</span>
                  <div className="bg-muted/40 border border-border text-foreground text-sm p-3 rounded-lg rounded-bl-none">
                    {message.text}
                  </div>
                  <span className="text-xs text-muted-foreground ml-1 font-mono">
                    {message.timestamp}
                  </span>
                </div>
              )}

              {/* Agent message */}
              {message.type === 'agent' && (
                <div className="max-w-[75%] space-y-1">
                  <span className="text-xs text-primary font-semibold text-right block mr-1">
                    Agent (Aryan)
                  </span>
                  <div className="bg-primary/20 border border-primary/40 text-foreground text-sm p-3 rounded-lg rounded-br-none">
                    {message.text}
                  </div>
                  <span className="text-xs text-muted-foreground font-mono text-right block mr-1">
                    {message.timestamp}
                  </span>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}