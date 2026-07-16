'use client';

import { CheckCircle2, Loader2, Database } from 'lucide-react';
import type { ToolCallEntry, PortfolioSummary } from '@/hooks/useDashboardWebSocket';

interface ToolsDataPanelProps {
  toolCalls       : ToolCallEntry[];
  portfolioSummary: PortfolioSummary | null;
}

// Shorten tool names for display
function formatToolName(tool: string): string {
  return tool.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Short fund name for table display
function shortFundName(name: string): string {
  if (name.length <= 30) return name;
  // Extract key part: "Mirae Asset Large Cap Fund..." → "Mirae Asset Large Cap"
  return name.split(' - ')[0].split(' ').slice(0, 4).join(' ');
}

export function ToolsDataPanel({ toolCalls, portfolioSummary }: ToolsDataPanelProps) {

  const gainLoss = portfolioSummary
    ? portfolioSummary.total_current_value - portfolioSummary.total_invested
    : 0;

  const gainPercent = portfolioSummary && portfolioSummary.total_invested > 0
    ? (gainLoss / portfolioSummary.total_invested) * 100
    : 0;

  return (
    <div className="bg-card border border-border rounded-lg p-6 space-y-6 h-full">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
        Tool Calls & Data
      </h2>

      {/* Tool call feed */}
      <div className="space-y-2">
        <h3 className="text-xs text-muted-foreground uppercase tracking-wider">
          Recent Tool Calls
        </h3>

        {toolCalls.length === 0 ? (
          <p className="text-xs text-muted-foreground py-2">No tool calls yet</p>
        ) : (
          <div className="space-y-2 max-h-36 overflow-y-auto">
            {toolCalls.map((call) => (
              <div
                key={call.id}
                className="flex items-center justify-between p-2 bg-muted/20 border border-border rounded text-xs animate-slide-in-right"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {call.status === 'done' ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-success flex-shrink-0" />
                  ) : (
                    <Loader2 className="w-3.5 h-3.5 text-primary animate-spin flex-shrink-0" />
                  )}
                  <span className="font-mono text-foreground truncate">
                    {formatToolName(call.tool)}
                  </span>
                  {call.cached && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded font-mono flex-shrink-0">
                      CACHED
                    </span>
                  )}
                </div>
                <span className="text-muted-foreground font-mono flex-shrink-0 ml-2">
                  {call.timestamp}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Portfolio data */}
      <div className="space-y-3 border-t border-border pt-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs text-muted-foreground uppercase tracking-wider">
            Portfolio Holdings
          </h3>
          {portfolioSummary && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-primary font-semibold">
                ₹{portfolioSummary.total_current_value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </span>
              <span className={`text-xs font-mono font-semibold ${gainLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                {gainLoss >= 0 ? '▲' : '▼'} {Math.abs(gainPercent).toFixed(1)}%
              </span>
            </div>
          )}
        </div>

        {!portfolioSummary ? (
          <div className="flex flex-col items-center justify-center py-6 space-y-2 text-muted-foreground">
            <Database className="w-6 h-6 opacity-20" />
            <p className="text-xs">Portfolio data will appear after tool call</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 px-1 text-muted-foreground font-semibold">Fund</th>
                    <th className="text-right py-2 px-1 text-muted-foreground font-semibold">Units</th>
                    <th className="text-right py-2 px-1 text-muted-foreground font-semibold">Value</th>
                    <th className="text-right py-2 px-1 text-muted-foreground font-semibold">G/L</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolioSummary.funds.map((fund, i) => {
                    const gl = fund.current_value - fund.invested;
                    return (
                      <tr key={i} className="border-b border-border/50 hover:bg-muted/10 transition-colors">
                        <td className="py-2 px-1 text-primary font-semibold max-w-[120px]">
                          <span title={fund.fund_name}>{shortFundName(fund.fund_name)}</span>
                        </td>
                        <td className="text-right py-2 px-1 text-foreground">
                          {fund.units_held.toFixed(2)}
                        </td>
                        <td className="text-right py-2 px-1 text-foreground">
                          ₹{fund.current_value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </td>
                        <td className={`text-right py-2 px-1 font-semibold ${gl >= 0 ? 'text-success' : 'text-destructive'}`}>
                          {gl >= 0 ? '+' : ''}₹{gl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border">
                    <td colSpan={2} className="py-2 px-1 text-muted-foreground text-[10px]">
                      NAV: {portfolioSummary.nav_type} · {portfolioSummary.nav_date}
                    </td>
                    <td className="text-right py-2 px-1 text-foreground font-semibold">
                      ₹{portfolioSummary.total_current_value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </td>
                    <td className={`text-right py-2 px-1 font-semibold ${gainLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                      {gainLoss >= 0 ? '+' : ''}₹{gainLoss.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}