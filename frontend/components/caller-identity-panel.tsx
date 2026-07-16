'use client';

import { Lock, Check } from 'lucide-react';
import type { VerifiedUser } from '@/hooks/useDashboardWebSocket';

interface CallerIdentityPanelProps {
  verifiedUser: VerifiedUser | null;
}

// Mask PAN — show first 5 chars, hide last 5
function maskPan(pan: string): string {
  if (!pan || pan.length < 10) return pan;
  return pan.slice(0, 5) + '*'.repeat(5);
}

export function CallerIdentityPanel({ verifiedUser }: CallerIdentityPanelProps) {
  const isRevealed = verifiedUser !== null;

  return (
    <div className="bg-card border border-border rounded-lg p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
          Caller Identity
        </h2>
        {isRevealed ? (
          <div className="flex items-center gap-2">
            <Check className="w-4 h-4 text-success" />
            <span className="text-xs font-mono text-success font-semibold">REVEALED</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-warning" />
            <span className="text-xs font-mono text-warning font-semibold">LOCKED</span>
          </div>
        )}
      </div>

      <div className="space-y-3 pt-2">
        {/* Name */}
        <div className="space-y-1">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">Full Name</span>
          <div className={`font-mono text-sm p-3 rounded bg-muted/20 border border-border transition-all duration-500 ${
            isRevealed ? 'opacity-100 blur-none' : 'opacity-40 blur-sm'
          }`}>
            {isRevealed ? verifiedUser!.name : '••••••••••••'}
          </div>
        </div>

        {/* PAN */}
        <div className="space-y-1">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">PAN Card</span>
          <div className={`font-mono text-sm p-3 rounded bg-success/10 border border-success/30 transition-all duration-500 ${
            isRevealed ? 'opacity-100 blur-none' : 'opacity-40 blur-sm'
          }`}>
            {isRevealed ? (
              <span className="text-success font-semibold">
                {verifiedUser!.pan ? maskPan(verifiedUser!.pan) : 'VERIFIED ✓'}
              </span>
            ) : (
              <span className="text-success">••••••••••</span>
            )}
          </div>
        </div>

        {/* Phone */}
        <div className="space-y-1">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">Phone</span>
          <div className={`font-mono text-sm p-3 rounded bg-muted/20 border border-border transition-all duration-500 ${
            isRevealed ? 'opacity-100 blur-none' : 'opacity-40 blur-sm'
          }`}>
            {isRevealed
              ? (verifiedUser!.phone || 'Verified')
              : '••••••••••••'}
          </div>
        </div>
      </div>

      {/* Verification banner */}
      {isRevealed && (
        <div className="mt-4 p-3 bg-success/10 border border-success/30 rounded text-xs text-success animate-fade-in-up">
          ✓ Identity verified via PAN. Session secured.
        </div>
      )}
    </div>
  );
}