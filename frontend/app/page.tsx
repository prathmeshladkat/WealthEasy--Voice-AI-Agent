'use client';

import { useDashboardWebSocket } from '@/hooks/useDashboardWebSocket';
import { CallStatusPanel }      from '@/components/call-status-panel';
import { CallerIdentityPanel }  from '@/components/caller-identity-panel';
import { LiveTranscriptPanel }  from '@/components/live-transcript-panel';
import { ToolsDataPanel }       from '@/components/tools-data-panel';
import { CallButton }           from '@/components/call-button';
import { LiveKitCallButton } from '@/components/livekit-call-button';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/dashboard/ws';

export default function Home() {
  const state = useDashboardWebSocket(WS_URL);

  return (
    <main className="min-h-screen bg-background p-4 md:p-6">

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-foreground tracking-tight">
            WealthEasy
          </h1>
          <p className="text-sm text-muted-foreground">
            AI Voice Agent Monitoring Dashboard — Real-time Call & Portfolio Analytics
          </p>
        </div>

        {/* Right side — connection status + call button */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${state.connected ? 'bg-success animate-pulse' : 'bg-destructive'}`} />
            <span className="text-xs font-mono text-muted-foreground">
              {state.connected ? 'System Online' : 'Disconnected'}
            </span>
          </div>
          <LiveKitCallButton />
          <span className="text-xs font-mono text-muted-foreground">v1.0.0 · Aryan Agent</span>
        </div>
      </div>

      {/* Dashboard Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-4">
          <CallStatusPanel
            callActive      = {state.callActive}
            callState       = {state.callState}
            agentState      = {state.agentState}
            durationSeconds = {state.durationSeconds}
            bargeInCount    = {state.bargeInCount}
          />
          <CallerIdentityPanel
            verifiedUser = {state.verifiedUser}
          />
        </div>
        <div className="lg:col-span-1">
          <LiveTranscriptPanel
            messages   = {state.messages}
            callActive = {state.callActive}
          />
        </div>
        <div className="lg:col-span-1">
          <ToolsDataPanel
            toolCalls        = {state.toolCalls}
            portfolioSummary = {state.portfolioSummary}
          />
        </div>
      </div>

      {/* Footer */}
      <div className="mt-6 pt-4 border-t border-border">
        <div className="flex items-center justify-between text-xs text-muted-foreground font-mono">
          <div>
            {state.callSid && <span>Call SID: {state.callSid}</span>}
          </div>
          
        </div>
      </div>
    </main>
  );
}