import React from 'react';
import type { Recommendation } from '../../hooks/useMarketData';

interface RecommendationBannerProps {
  recommendation: Recommendation | null;
}

const INSTRUMENT_LABELS: Record<string, string> = {
  BUY_CALL: 'BUY CALL',
  BUY_PUT: 'BUY PUT',
  CCS: 'BEAR CALL SPREAD',
  PCS: 'BULL PUT SPREAD',
  NO_TRADE: 'NO TRADE',
};

export const RecommendationBanner: React.FC<RecommendationBannerProps> = ({ recommendation }) => {
  if (!recommendation) {
    return (
      <div style={{
        background: 'linear-gradient(90deg, #1a1a2e 0%, #16213e 100%)',
        border: '1px solid #334155',
        borderRadius: '10px',
        padding: '14px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        color: '#64748b',
        fontSize: '13px',
        fontStyle: 'italic',
      }}>
        <span style={{ fontSize: '18px' }}>⏳</span>
        Awaiting 10-minute recommendation...
      </div>
    );
  }

  const isBullish = recommendation.direction === 'BULLISH';
  const isBearish = recommendation.direction === 'BEARISH';
  const isNoTrade = recommendation.instrument === 'NO_TRADE';

  const dirColor = isBearish ? '#ef4444' : isBullish ? '#22c55e' : '#94a3b8';
  const bgGradient = isBearish
    ? 'linear-gradient(90deg, #7f1d1d 0%, #450a0a 100%)'
    : isBullish
    ? 'linear-gradient(90deg, #14532d 0%, #052e16 100%)'
    : 'linear-gradient(90deg, #1e293b 0%, #0f172a 100%)';

  const confidenceColors: Record<string, string> = { LOW: '#94a3b8', MEDIUM: '#f59e0b', HIGH: '#22c55e' };
  const confColor = confidenceColors[recommendation.confidence] ?? '#94a3b8';
  const score = recommendation.score;
  const absScore = Math.abs(score);
  const barWidth = Math.round((absScore / 3) * 100);

  return (
    <div style={{
      background: bgGradient,
      border: `1.5px solid ${dirColor}66`,
      borderRadius: '10px',
      padding: '14px 20px',
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
    }}>
      {/* Top row: label + direction + instrument + confidence + levels + time */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
        {/* "10-MIN REC" label */}
        <div style={{
          background: dirColor + '22',
          border: `1px solid ${dirColor}`,
          color: dirColor,
          borderRadius: '6px',
          padding: '4px 12px',
          fontSize: '11px',
          fontWeight: 800,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}>
          10-Min Rec
        </div>

        {/* Direction arrow + word */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '22px', lineHeight: 1 }}>
            {isBearish ? '🔻' : isBullish ? '🔺' : '➖'}
          </span>
          <span style={{
            fontSize: '18px',
            fontWeight: 800,
            color: dirColor,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
          }}>
            {recommendation.direction}
          </span>
        </div>

        {/* Instrument */}
        <div style={{
          background: '#ffffff10',
          borderRadius: '6px',
          padding: '4px 14px',
          fontSize: '15px',
          fontWeight: 700,
          color: '#ffffff',
          letterSpacing: '0.03em',
        }}>
          {INSTRUMENT_LABELS[recommendation.instrument] ?? recommendation.instrument}
        </div>

        {/* Confidence */}
        <div style={{
          background: confColor + '22',
          border: `1px solid ${confColor}`,
          color: confColor,
          borderRadius: '6px',
          padding: '4px 12px',
          fontSize: '11px',
          fontWeight: 700,
          letterSpacing: '0.08em',
        }}>
          {recommendation.confidence} CONFIDENCE
        </div>

        {/* Anchor strike */}
        {recommendation.anchor_strike && (
          <div style={{ color: '#e2e8f0', fontSize: '14px', fontWeight: 600 }}>
            @ strike <strong style={{ color: '#f8fafc' }}>{recommendation.anchor_strike.toFixed(0)}</strong>
          </div>
        )}

        {/* Timestamp */}
        <div style={{ marginLeft: 'auto', color: '#64748b', fontSize: '12px' }}>
          {new Date(recommendation.timestamp * 1000).toLocaleTimeString()}
        </div>
      </div>

      {/* Conviction bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span style={{ fontSize: '11px', color: '#64748b', width: 72, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Conviction</span>
        <div style={{ flex: 1, height: '8px', background: '#1e293b', borderRadius: '4px', overflow: 'hidden' }}>
          <div style={{
            width: `${barWidth}%`,
            height: '100%',
            background: `linear-gradient(90deg, ${dirColor}cc, ${dirColor})`,
            borderRadius: '4px',
            transition: 'width 0.6s ease',
          }} />
        </div>
        <span style={{ fontSize: '14px', fontWeight: 700, color: dirColor, width: 48, textAlign: 'right' }}>
          {score >= 0 ? '+' : ''}{score.toFixed(2)}
        </span>
      </div>

    </div>
  );
};
