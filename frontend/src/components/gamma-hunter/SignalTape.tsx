import React, { useEffect, useState } from 'react';
import type { BotTapeSignal } from '../../hooks/useMarketData';

interface SignalTapeProps {
  signals: BotTapeSignal[];
}

export const SignalTape: React.FC<SignalTapeProps> = ({ signals }) => {
  const [flashIdx, setFlashIdx] = useState<number>(-1);
  const [flashTime, setFlashTime] = useState<number>(0);

  useEffect(() => {
    if (signals.length === 0) return;
    const lastIdx = signals.length - 1;
    if (lastIdx !== flashIdx) {
      setFlashIdx(lastIdx);
      setFlashTime(Date.now());
    }
  }, [signals, flashIdx]);

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Tape · Signal Feed
        </span>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{signals.length} signals</span>
      </div>

      <div style={{ maxHeight: '140px', overflowY: 'auto' }}>
        {signals.length === 0 && (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: '12px', textAlign: 'center' }}>
            No bot signals yet
          </div>
        )}
        {signals.map((sig, idx) => {
          const isCall = sig.side === 'C';
          const executed = sig.status === 'EXECUTED';
          const isLatest = idx === flashIdx && Date.now() - flashTime < 1500;

          return (
            <div
              key={idx}
              style={{
                display: 'grid',
                gridTemplateColumns: '70px 1fr 1fr 1fr 1fr 1fr 80px',
                alignItems: 'center',
                padding: '8px 16px',
                borderBottom: '1px solid var(--border-subtle)',
                fontSize: '11px',
                gap: '8px',
                background: isLatest ? 'rgba(0, 229, 255, 0.1)' : 'transparent',
                transition: 'background 1.5s ease',
              }}
            >
              <span className="font-data" style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
                {sig.timestamp}
              </span>
              <span style={{ fontWeight: 700, color: isCall ? 'var(--accent-call)' : 'var(--accent-put)' }}>
                {isCall ? 'C' : 'P'} {sig.strike}
              </span>
              <span className="font-data" style={{ color: 'var(--text-secondary)' }}>
                Z={sig.z_score.toFixed(2)}
              </span>
              <span className="font-data" style={{ color: 'var(--text-secondary)' }}>
                ratio {sig.ratio.toFixed(1)}
              </span>
              <span className="font-data" style={{ color: 'var(--text-secondary)' }}>
                {sig.volume !== null ? sig.volume.toLocaleString() : '—'}
              </span>
              <span className="font-data" style={{ color: 'var(--text-secondary)' }}>
                ${sig.ask.toFixed(2)}
              </span>
              <span style={{
                padding: '2px 8px',
                borderRadius: '4px',
                textAlign: 'center',
                fontSize: '10px',
                fontWeight: 700,
                background: executed ? 'var(--accent-call-dim)' : 'transparent',
                color: executed ? 'var(--accent-call)' : 'var(--text-muted)',
                border: executed ? '1px solid var(--accent-call)' : '1px solid var(--border-subtle)',
              }}>
                {sig.status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};