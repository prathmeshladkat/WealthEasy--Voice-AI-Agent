'use client';

import { Phone, Mic, Volume2, Brain, PhoneOff } from 'lucide-react';
import type { CallState, AgentState } from '@/hooks/useDashboardWebSocket';

interface CallStatusPanelProps {
  callActive     : boolean;
  callState      : CallState;
  agentState     : AgentState;
  durationSeconds: number;
  bargeInCount   : number;
}

const STATE_CONFIG: Record<CallState, { label: string; color: string; bg: string }> = {
  IDLE        : { label: 'IDLE',         color: 'text-muted-foreground', bg: 'bg-muted/20'    },
  GREETING    : { label: 'GREETING',     color: 'text-primary',          bg: 'bg-primary/20'  },
  VERIFY_PHONE: { label: 'VERIFY PHONE', color: 'text-warning',          bg: 'bg-warning/20'  },
  VERIFY_PAN  : { label: 'VERIFY PAN',   color: 'text-warning',          bg: 'bg-warning/20'  },
  VERIFIED    : { label: 'VERIFIED ✓',   color: 'text-success',          bg: 'bg-success/20'  },
  QUERY       : { label: 'IN QUERY',     color: 'text-primary',          bg: 'bg-primary/20'  },
  ENDING      : { label: 'ENDING',       color: 'text-destructive',      bg: 'bg-destructive/20' },
};

export function CallStatusPanel({
  callActive,
  callState,
  agentState,
  durationSeconds,
  bargeInCount,
}: CallStatusPanelProps) {

  const formatDuration = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const stateConfig = STATE_CONFIG[callState];

  return (
    <div className="bg-card border border-border rounded-lg p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
          Call Status
        </h2>
        {callActive ? (
          <div className="flex items-center gap-2">
            <Phone className="w-4 h-4 text-success animate-pulse" />
            <span className="text-xs font-mono text-success font-semibold">ACTIVE</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <PhoneOff className="w-4 h-4 text-muted-foreground" />
            <span className="text-xs font-mono text-muted-foreground">NO CALL</span>
          </div>
        )}
      </div>

      {!callActive ? (
        <div className="flex flex-col items-center justify-center py-8 space-y-2">
          <div className="w-2 h-2 rounded-full bg-muted-foreground animate-pulse" />
          <p className="text-xs text-muted-foreground">Waiting for incoming call...</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Verification State */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">
              Verification
            </span>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${stateConfig.color.replace('text-', 'bg-')} animate-pulse`} />
              <span className={`text-xs font-mono px-2 py-1 rounded ${stateConfig.bg} ${stateConfig.color}`}>
                {stateConfig.label}
              </span>
            </div>
          </div>

          {/* Duration */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">Duration</span>
            <span className="text-lg font-mono text-primary font-bold">
              {formatDuration(durationSeconds)}
            </span>
          </div>

          {/* Agent State */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">Agent State</span>
            <div className="flex items-center gap-2">
              {agentState === 'SPEAKING' && (
                <>
                  <Mic className="w-4 h-4 text-primary animate-pulse" />
                  <span className="text-xs font-mono text-primary">SPEAKING</span>
                </>
              )}
              {agentState === 'THINKING' && (
                <>
                  <Brain className="w-4 h-4 text-warning animate-pulse" />
                  <span className="text-xs font-mono text-warning">THINKING</span>
                </>
              )}
              {agentState === 'IDLE' && (
                <>
                  <Volume2 className="w-4 h-4 text-muted-foreground" />
                  <span className="text-xs font-mono text-muted-foreground">LISTENING</span>
                </>
              )}
            </div>
          </div>

          {/* Barge-in Counter */}
          <div className="flex items-center justify-between pt-2 border-t border-border">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">
              Barge-In Count
            </span>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-mono font-bold text-warning">{bargeInCount}</span>
              <span className="text-xs text-warning">interruptions</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}