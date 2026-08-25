import React, { useEffect, useState } from 'react';
import type { GexData, PositionData, BotTapeSignal } from '../../hooks/useMarketData';
import { HeaderStats } from './HeaderStats';
import { StrikeLadder } from './StrikeLadder';
import { GammaExposureBars } from './GammaExposureBars';
import { IvSkewChart } from './IvSkewChart';
import { ActivePosition } from './ActivePosition';
import { EngineHealth } from './EngineHealth';
import { SignalTape } from './SignalTape';

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
  wsConnected: boolean;
  spotHistory: number[];
  netGexHistory: number[];
  pnlHistory: number[];
  notificationPermission: NotificationPermission | 'unsupported';
  requestNotificationPermission: () => Promise<NotificationPermission | 'unsupported'>;
}

export const GammaHunter: React.FC<GammaHunterProps> = ({
  metrics,
  position,
  tapeSignals,
  wsConnected,
  spotHistory,
  netGexHistory,
  pnlHistory,
  notificationPermission,
  requestNotificationPermission,
}) => {
  const engineHealth = metrics?.engine_health;
  const width = useWindowWidth();
  const layout = computeLayout(width);

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
      <div style={{ gridColumn: '1 / -1' }}>
        <HeaderStats
          metrics={metrics}
          position={position}
          tapeSignals={tapeSignals}
          wsConnected={wsConnected}
          spotHistory={spotHistory}
          netGexHistory={netGexHistory}
          pnlHistory={pnlHistory}
        />
      </div>

      {/* Left: Strike ladder */}
      <div style={{ gridColumn: `span ${layout.ladderSpan}`, minHeight: layout.ladderMinHeight }}>
        <StrikeLadder metrics={metrics} />
      </div>

      {/* Center: Gamma bars + IV skew */}
      <div style={{ gridColumn: `span ${layout.panelSpan}`, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <GammaExposureBars metrics={metrics} />
        <IvSkewChart metrics={metrics} />
      </div>

      {/* Right: Active position + Engine health */}
      <div style={{ gridColumn: `span ${layout.panelSpan}`, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <ActivePosition position={position} />
        <EngineHealth metrics={metrics} health={engineHealth} />
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
