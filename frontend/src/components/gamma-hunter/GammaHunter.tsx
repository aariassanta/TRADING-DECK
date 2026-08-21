import React from 'react';
import type { GexData, PositionData, BotTapeSignal } from '../../hooks/useMarketData';
import { HeaderStats } from './HeaderStats';
import { StrikeLadder } from './StrikeLadder';
import { GammaExposureBars } from './GammaExposureBars';
import { IvSkewChart } from './IvSkewChart';
import { ActivePosition } from './ActivePosition';
import { EngineHealth } from './EngineHealth';
import { SignalTape } from './SignalTape';

interface GammaHunterProps {
  metrics: GexData | null;
  position: PositionData;
  tapeSignals: BotTapeSignal[];
}

export const GammaHunter: React.FC<GammaHunterProps> = ({ metrics, position, tapeSignals }) => {
  const engineHealth = metrics?.engine_health;

  return (
    <div
      className="gamma-hunter"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(12, 1fr)',
        gridAutoRows: 'min-content',
        gap: '12px',
        padding: '12px',
        height: '100%',
        overflowY: 'auto',
      }}
    >
      {/* Header stats: full width */}
      <div style={{ gridColumn: 'span 12' }}>
        <HeaderStats metrics={metrics} position={position} tapeSignals={tapeSignals} />
      </div>

      {/* Left: Strike ladder */}
      <div style={{ gridColumn: 'span 4', minHeight: '520px' }}>
        <StrikeLadder metrics={metrics} />
      </div>

      {/* Center: Gamma bars + IV skew */}
      <div style={{ gridColumn: 'span 4', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <GammaExposureBars metrics={metrics} />
        <IvSkewChart metrics={metrics} />
      </div>

      {/* Right: Active position + Engine health */}
      <div style={{ gridColumn: 'span 4', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <ActivePosition position={position} />
        <EngineHealth metrics={metrics} health={engineHealth} />
      </div>

      {/* Bottom: Signal tape */}
      <div style={{ gridColumn: 'span 12' }}>
        <SignalTape signals={tapeSignals} />
      </div>
    </div>
  );
};

export default GammaHunter;
