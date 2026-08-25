import React, { useEffect, useState } from 'react';
import type { GexData, PositionData, BotTapeSignal } from '../../hooks/useMarketData';
import { HeaderStats } from './HeaderStats';
import { StrikeLadder } from './StrikeLadder';
import { GammaExposureBars } from './GammaExposureBars';
import { IvSkewChart } from './IvSkewChart';
import { ActivePosition } from './ActivePosition';
import { EngineHealth } from './EngineHealth';
import { SignalTape } from './SignalTape';
import { AlertRules } from './AlertRules';
import { SoundSettingsPanel } from './SoundSettings';
import type { AlertRule, SoundSettings as SoundSettingsType } from '../../hooks/useMarketData';

// ---------------------------------------------------------------------------
// Responsive helpers
// ---------------------------------------------------------------------------

/** Track the current viewport width. SSR-safe (returns 1400 on the server). */
const useWindowWidth = (): number => {
  const [width, setWidth] = useState<number>(() =>
    typeof window === 'undefined' ? 1400 : window.innerWidth
  );
  useEffect(() => {
    let rafId: number | null = null;
    const handler = () => {
      // Coalesce resize events via rAF to avoid setState storms
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        setWidth(window.innerWidth);
        rafId = null;
      });
    };
    window.addEventListener('resize', handler);
    return () => {
      window.removeEventListener('resize', handler);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, []);
  return width;
};

/** Width breakpoints for the 12-col grid. */
const BREAKPOINTS = {
  mobile: 900,   // <900: single column
  tablet: 1280,  // 900-1280: 6-col grid (3 panels side-by-side as 2 rows of 3)
  // >=1280: full 12-col layout (3 panels per row)
} as const;

const computeLayout = (width: number) => {
  if (width < BREAKPOINTS.mobile) {
    return {
      gridCols: '1fr',
      panelSpan: 12,
      ladderSpan: 12,
      ladderMinHeight: 400,
    };
  }
  if (width < BREAKPOINTS.tablet) {
    return {
      gridCols: 'repeat(6, 1fr)',
      panelSpan: 6,
      ladderSpan: 6,
      ladderMinHeight: 480,
    };
  }
  return {
    gridCols: 'repeat(12, 1fr)',
    panelSpan: 4,
    ladderSpan: 4,
    ladderMinHeight: 520,
  };
};

interface GammaHunterProps {
  metrics: GexData | null;
  position: PositionData;
  tapeSignals: BotTapeSignal[];
  spotHistory: number[];
  netGexHistory: number[];
  pnlHistory: number[];
  notificationPermission: NotificationPermission | 'unsupported';
  requestNotificationPermission: () => Promise<NotificationPermission | 'unsupported'>;
  isPaused: boolean;
  alertRules: AlertRule[];
  setAlertRules: (rules: AlertRule[]) => void;
  soundSettings: SoundSettingsType;
  setSoundSettings: (s: SoundSettingsType) => void;
  onTestBeep: () => void;
}

export const GammaHunter: React.FC<GammaHunterProps> = ({
  metrics,
  position,
  tapeSignals,
  spotHistory,
  netGexHistory,
  pnlHistory,
  notificationPermission,
  requestNotificationPermission,
  isPaused,
  alertRules,
  setAlertRules,
  soundSettings,
  setSoundSettings,
  onTestBeep,
}) => {
  const engineHealth = metrics?.engine_health;
  const width = useWindowWidth();
  const layout = computeLayout(width);
  // Default the gamma-bars expiry tab to the first available (typically 0DTE)
  const [selectedExpiry, setSelectedExpiry] = useState<string | undefined>(
    () => metrics?.expiries?.[0]
  );
  // When new metrics arrive with a different expiry list, follow the new default
  useEffect(() => {
    if (!metrics?.expiries?.length) return;
    setSelectedExpiry(prev => {
      if (prev && metrics.expiries.includes(prev)) return prev;
      return metrics.expiries[0];
    });
  }, [metrics?.expiries]);

  return (
    <div
      className="gamma-hunter"
      style={{
        display: 'grid',
        gridTemplateColumns: layout.gridCols,
        gridAutoRows: 'min-content',
        gap: '12px',
        padding: '12px',
        height: '100%',
        overflowY: 'auto',
      }}
    >
      {/* Header stats: always full width */}
      <div style={{ gridColumn: '1 / -1', position: 'relative' }}>
        <HeaderStats
          metrics={metrics}
          position={position}
          tapeSignals={tapeSignals}
          spotHistory={spotHistory}
          netGexHistory={netGexHistory}
          pnlHistory={pnlHistory}
        />
        {isPaused && (
          <div
            aria-live="polite"
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              background: 'rgba(245, 158, 11, 0.18)',
              border: '1.5px solid #f59e0b',
              borderRadius: '8px',
              padding: '10px 24px',
              fontSize: '14px',
              fontWeight: 800,
              letterSpacing: '0.12em',
              color: '#f59e0b',
              pointerEvents: 'none',
              textShadow: '0 0 12px rgba(245, 158, 11, 0.5)',
            }}
          >
            ⏸ PAUSED — press SPACE to resume
          </div>
        )}
      </div>

      {/* Left: Strike ladder */}
      <div style={{ gridColumn: `span 6`, height: '460px', display: 'flex', flexDirection: 'column' }}>
        <StrikeLadder metrics={metrics} />
      </div>

      {/* Right: Gamma exposure bars only */}
      <div style={{ gridColumn: `span 6`, height: '460px', display: 'flex', flexDirection: 'column' }}>
        <GammaExposureBars
          metrics={metrics}
          selectedExpiry={selectedExpiry}
          onSelectExpiry={setSelectedExpiry}
        />
      </div>

      {/* Full-width: IV skew chart */}
      <div style={{ gridColumn: '1 / -1' }}>
        <IvSkewChart metrics={metrics} />
      </div>

      {/* Full-width: Active position */}
      <div style={{ gridColumn: '1 / -1' }}>
        <ActivePosition position={position} />
      </div>

      {/* Full-width: Engine health */}
      <div style={{ gridColumn: '1 / -1' }}>
        <EngineHealth metrics={metrics} health={engineHealth} />
      </div>

      {/* Alert rules: collapsible full-width strip below header */}
      <div style={{ gridColumn: '1 / -1' }}>
        <AlertRules rules={alertRules} onChange={setAlertRules} />
      </div>

      {/* Sound settings: collapsible strip below alert rules */}
      <div style={{ gridColumn: '1 / -1' }}>
        <SoundSettingsPanel settings={soundSettings} onChange={setSoundSettings} onTest={onTestBeep} />
      </div>

      {/* Bottom: Signal tape — always full width */}
      <div style={{ gridColumn: '1 / -1' }}>
        <SignalTape
          signals={tapeSignals}
          notificationPermission={notificationPermission}
          requestNotificationPermission={requestNotificationPermission}
        />
      </div>
    </div>
  );
};

export default GammaHunter;
