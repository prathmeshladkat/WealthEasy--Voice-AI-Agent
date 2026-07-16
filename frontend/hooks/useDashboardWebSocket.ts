'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

// ── Types ──────────────────────────────────────────────────────────────────────

export type CallState =
  | 'IDLE'
  | 'GREETING'
  | 'VERIFY_PHONE'
  | 'VERIFY_PAN'
  | 'VERIFIED'
  | 'QUERY'
  | 'ENDING';

export type AgentState = 'IDLE' | 'THINKING' | 'SPEAKING';

export interface TranscriptMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  text: string;
  timestamp: string;
}

export interface ToolCallEntry {
  id: string;
  tool: string;
  status: 'running' | 'done';
  timestamp: string;
  cached?: boolean;
}

export interface FundHolding {
  fund_name: string;
  units_held: number;
  current_nav: number;
  current_value: number;
  invested: number;
}

export interface PortfolioSummary {
  funds: FundHolding[];
  total_current_value: number;
  total_invested: number;
  nav_date: string;
  nav_type: string;
}

export interface VerifiedUser {
  user_id: number;
  name: string;
  phone?: string;
  pan?: string;
}

export interface DashboardState {
  // Connection
  connected: boolean;

  // Call
  callActive: boolean;
  callSid: string | null;
  callState: CallState;
  agentState: AgentState;
  durationSeconds: number;
  bargeInCount: number;

  // Verified user
  verifiedUser: VerifiedUser | null;

  // Transcript
  messages: TranscriptMessage[];

  // Tools
  toolCalls: ToolCallEntry[];
  portfolioSummary: PortfolioSummary | null;
}

const INITIAL_STATE: DashboardState = {
  connected      : false,
  callActive     : false,
  callSid        : null,
  callState      : 'IDLE',
  agentState     : 'IDLE',
  durationSeconds: 0,
  bargeInCount   : 0,
  verifiedUser   : null,
  messages       : [],
  toolCalls      : [],
  portfolioSummary: null,
};

// ── Hook ───────────────────────────────────────────────────────────────────────

export function useDashboardWebSocket(url: string): DashboardState {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const wsRef            = useRef<WebSocket | null>(null);
  const timerRef         = useRef<NodeJS.Timeout | null>(null);
  const clearTimerRef    = useRef<NodeJS.Timeout | null>(null);  // 10s buffer timer
  const msgIdRef         = useRef(0);

  const nextId = () => String(++msgIdRef.current);

  const now = () =>
    new Date().toLocaleTimeString('en-IN', {
      hour  : '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });

  // ── Duration timer ─────────────────────────────────────────────────────────

  const startTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setState(prev => ({ ...prev, durationSeconds: prev.durationSeconds + 1 }));
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // ── Event handler ──────────────────────────────────────────────────────────

  const handleEvent = useCallback((event: Record<string, unknown>) => {
    const type = event.event as string;

    switch (type) {

      case 'call_started':
        // Cancel any pending clear from previous call
        if (clearTimerRef.current) {
          clearTimeout(clearTimerRef.current);
          clearTimerRef.current = null;
        }
        setState(prev => ({
          ...prev,
          callActive      : true,
          callSid         : event.call_sid as string,
          callState       : 'GREETING',
          agentState      : 'IDLE',
          durationSeconds : 0,
          bargeInCount    : 0,
          verifiedUser    : null,
          messages        : [],
          toolCalls       : [],
          portfolioSummary: null,
        }));
        startTimer();
        break;

      case 'transcript': {
        const role = event.role as string;
        const text = event.text as string;
        const msg: TranscriptMessage = {
          id       : nextId(),
          type     : role === 'user' ? 'user' : 'agent',
          text,
          timestamp: now(),
        };
        setState(prev => ({ ...prev, messages: [...prev.messages, msg] }));
        break;
      }

      case 'verified': {
        const user: VerifiedUser = {
          user_id: event.user_id as number,
          name   : event.name as string,
        };
        const sysMsg: TranscriptMessage = {
          id       : nextId(),
          type     : 'system',
          text     : `✓ Identity verified — ${user.name}`,
          timestamp: now(),
        };
        setState(prev => ({
          ...prev,
          verifiedUser: user,
          callState   : 'VERIFIED',
          messages    : [...prev.messages, sysMsg],
        }));
        break;
      }

      case 'state_change': {
        const agentState = event.state as AgentState;
        setState(prev => ({ ...prev, agentState }));
        break;
      }

      case 'tool_call': {
        const tool = event.tool as string;
        const entry: ToolCallEntry = {
          id       : nextId(),
          tool,
          status   : 'running',
          timestamp: now(),
        };
        const sysMsg: TranscriptMessage = {
          id       : nextId(),
          type     : 'system',
          text     : `🔧 Fetching ${tool.replace(/_/g, ' ')}...`,
          timestamp: now(),
        };
        setState(prev => ({
          ...prev,
          toolCalls: [...prev.toolCalls, entry],
          messages : [...prev.messages, sysMsg],
        }));
        break;
      }

      case 'tool_result': {
        // Mark the last running tool as done
        const toolName = event.tool as string;
        const result   = event.result as Record<string, unknown>;
        setState(prev => {
          const toolCalls = [...prev.toolCalls];
          // Find last running entry for this tool and mark done
          for (let i = toolCalls.length - 1; i >= 0; i--) {
            if (toolCalls[i].tool === toolName && toolCalls[i].status === 'running') {
              toolCalls[i] = { ...toolCalls[i], status: 'done', cached: event.cached as boolean };
              break;
            }
          }
          // If portfolio summary came back, store it
          let portfolioSummary = prev.portfolioSummary;
          if (toolName === 'get_portfolio_summary' && result) {
            portfolioSummary = result as unknown as PortfolioSummary;
          }
          return { ...prev, toolCalls, portfolioSummary };
        });
        break;
      }

      case 'barge_in':
        setState(prev => ({
          ...prev,
          bargeInCount: event.count as number,
        }));
        break;

      case 'intent':
        if (event.intent === 'ENDING') {
          setState(prev => ({ ...prev, callState: 'ENDING' }));
        }
        break;

      case 'call_ended':
        stopTimer();
        // Add system message
        const endMsg: TranscriptMessage = {
          id       : nextId(),
          type     : 'system',
          text     : `📞 Call ended — ${event.duration_seconds}s`,
          timestamp: now(),
        };
        setState(prev => ({
          ...prev,
          callActive: false,
          callState : 'IDLE',
          agentState: 'IDLE',
          messages  : [...prev.messages, endMsg],
        }));

        // 10 second buffer — keep transcript visible then clear
        clearTimerRef.current = setTimeout(() => {
          setState(prev => ({
            ...prev,
            callSid         : null,
            durationSeconds : 0,
            bargeInCount    : 0,
            verifiedUser    : null,
            messages        : [],
            toolCalls       : [],
            portfolioSummary: null,
          }));
        }, 10000);
        break;
    }
  }, [startTimer, stopTimer]);

  // ── WebSocket connection ───────────────────────────────────────────────────

  useEffect(() => {
    let reconnectTimer: NodeJS.Timeout;

    function connect() {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setState(prev => ({ ...prev, connected: true }));
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          handleEvent(data);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        setState(prev => ({ ...prev, connected: false }));
        // Reconnect after 3 seconds
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      if (timerRef.current) clearInterval(timerRef.current);
      if (clearTimerRef.current) clearTimeout(clearTimerRef.current);
      wsRef.current?.close();
    };
  }, [url, handleEvent]);

  return state;
}