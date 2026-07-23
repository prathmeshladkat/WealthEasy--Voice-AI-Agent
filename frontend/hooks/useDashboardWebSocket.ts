'use client';

import { useEffect, useRef, useState } from 'react';

// ── Types ──────────────────────────────────────────────────────────────────────

export type CallState =
  | 'IDLE' | 'GREETING' | 'VERIFY_PHONE'
  | 'VERIFY_PAN' | 'VERIFIED' | 'QUERY' | 'ENDING';

export type AgentState = 'IDLE' | 'THINKING' | 'SPEAKING';

export interface TranscriptMessage {
  id       : string;
  type     : 'user' | 'agent' | 'system';
  text     : string;
  timestamp: string;
}

export interface ToolCallEntry {
  id       : string;
  tool     : string;
  status   : 'running' | 'done';
  timestamp: string;
  cached?  : boolean;
}

export interface FundHolding {
  fund_name    : string;
  units_held   : number;
  current_nav  : number;
  current_value: number;
  invested     : number;
}

export interface PortfolioSummary {
  funds               : FundHolding[];
  total_current_value : number;
  total_invested      : number;
  nav_date            : string;
  nav_type            : string;
}

export interface VerifiedUser {
  user_id: number;
  name   : string;
  phone? : string;
  pan?   : string;
}

export interface DashboardState {
  connected       : boolean;
  callActive      : boolean;
  callSid         : string | null;
  callState       : CallState;
  agentState      : AgentState;
  durationSeconds : number;
  bargeInCount    : number;
  verifiedUser    : VerifiedUser | null;
  messages        : TranscriptMessage[];
  toolCalls       : ToolCallEntry[];
  portfolioSummary: PortfolioSummary | null;
}

const INITIAL: DashboardState = {
  connected       : false,
  callActive      : false,
  callSid         : null,
  callState       : 'IDLE',
  agentState      : 'IDLE',
  durationSeconds : 0,
  bargeInCount    : 0,
  verifiedUser    : null,
  messages        : [],
  toolCalls       : [],
  portfolioSummary: null,
};

let msgId = 0;
const nid = () => String(++msgId);
const now = () => new Date().toLocaleTimeString('en-IN', {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});

export function useDashboardWebSocket(url: string): DashboardState {
  const [state, setState]    = useState<DashboardState>(INITIAL);
  const stateRef             = useRef<DashboardState>(INITIAL);
  const timerRef             = useRef<ReturnType<typeof setInterval> | null>(null);
  const clearTimerRef        = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep stateRef in sync so event handler always has fresh state
  const update = (patch: Partial<DashboardState>) => {
    stateRef.current = { ...stateRef.current, ...patch };
    setState({ ...stateRef.current });
  };

  const startTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      stateRef.current = {
        ...stateRef.current,
        durationSeconds: stateRef.current.durationSeconds + 1,
      };
      setState({ ...stateRef.current });
    }, 1000);
  };

  const stopTimer = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  };

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const handleEvent = (event: Record<string, unknown>) => {
      const type = event.event as string;
      console.log('[WS event]', type, event); // debug — remove after confirming

      switch (type) {

        case 'call_started':
          if (clearTimerRef.current) { clearTimeout(clearTimerRef.current); clearTimerRef.current = null; }
          update({
            callActive: true, callSid: event.call_sid as string,
            callState: 'GREETING', agentState: 'IDLE',
            durationSeconds: 0, bargeInCount: 0,
            verifiedUser: null, messages: [], toolCalls: [], portfolioSummary: null,
          });
          startTimer();
          break;

        case 'transcript': {
          const msg: TranscriptMessage = {
            id: nid(), type: event.role === 'user' ? 'user' : 'agent',
            text: event.text as string, timestamp: now(),
          };
          update({ messages: [...stateRef.current.messages, msg] });
          break;
        }

        case 'verified': {
          const user: VerifiedUser = {
            user_id: event.user_id as number,
            name: event.name as string,
          };
          const sysMsg: TranscriptMessage = {
            id: nid(), type: 'system',
            text: `✓ Identity verified — ${user.name}`, timestamp: now(),
          };
          update({
            verifiedUser: user, callState: 'VERIFIED',
            messages: [...stateRef.current.messages, sysMsg],
          });
          break;
        }

        case 'state_change':
          update({ agentState: event.state as AgentState });
          break;

        case 'tool_call': {
          const tool = event.tool as string;
          const entry: ToolCallEntry = { id: nid(), tool, status: 'running', timestamp: now() };
          const sysMsg: TranscriptMessage = {
            id: nid(), type: 'system',
            text: `🔧 Fetching ${tool.replace(/_/g, ' ')}...`, timestamp: now(),
          };
          update({
            toolCalls: [...stateRef.current.toolCalls, entry],
            messages: [...stateRef.current.messages, sysMsg],
          });
          break;
        }

        case 'tool_result': {
          const toolName = event.tool as string;
          const result   = event.result as Record<string, unknown>;
          const toolCalls = stateRef.current.toolCalls.map(tc =>
            tc.tool === toolName && tc.status === 'running'
              ? { ...tc, status: 'done' as const, cached: event.cached as boolean }
              : tc
          );
          let portfolioSummary = stateRef.current.portfolioSummary;
          if (toolName === 'get_portfolio_summary' && result) {
            portfolioSummary = result as unknown as PortfolioSummary;
          }
          update({ toolCalls, portfolioSummary });
          break;
        }

        case 'barge_in':
          update({ bargeInCount: event.count as number });
          break;

        case 'intent':
          if (event.intent === 'ENDING') update({ callState: 'ENDING' });
          break;

        case 'call_ended': {
          stopTimer();
          const endMsg: TranscriptMessage = {
            id: nid(), type: 'system',
            text: `📞 Call ended — ${event.duration_seconds}s`, timestamp: now(),
          };
          update({
            callActive: false, callState: 'IDLE', agentState: 'IDLE',
            messages: [...stateRef.current.messages, endMsg],
          });
          // 10 second buffer before clearing
          clearTimerRef.current = setTimeout(() => {
            update({
              callSid: null, durationSeconds: 0, bargeInCount: 0,
              verifiedUser: null, messages: [], toolCalls: [], portfolioSummary: null,
            });
          }, 10000);
          break;
        }
      }
    };

    const connect = () => {
      console.log('[WS] connecting to', url);
      ws = new WebSocket(url);

      ws.onopen    = () => { console.log('[WS] connected'); update({ connected: true }); };
      ws.onmessage = (e) => { try { handleEvent(JSON.parse(e.data)); } catch {} };
      ws.onclose   = () => { update({ connected: false }); reconnectTimer = setTimeout(connect, 3000); };
      ws.onerror   = () => ws.close();
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      if (timerRef.current) clearInterval(timerRef.current);
      if (clearTimerRef.current) clearTimeout(clearTimerRef.current);
      ws?.close();
    };
  }, [url]);

  return state;
}