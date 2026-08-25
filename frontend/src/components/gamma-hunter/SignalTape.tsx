import React, { useEffect, useMemo, useState } from 'react';
import type { BotTapeSignal } from '../../hooks/useMarketData';
import { toCsv, downloadCsv, timestampedFilename } from './csv';
import type { CsvColumn } from './csv';

type StatusFilter = 'ALL' | 'EXECUTED' | 'PENDING' | 'OUT WINDOW';
type SideFilter = 'ALL' | 'C' | 'P';

interface SignalTapeProps {
  signals: BotTapeSignal[];
  notificationPermission: NotificationPermission | 'unsupported';
  requestNotificationPermission: () => Promise<NotificationPermission | 'unsupported'>;
}

const STATUS_FILTERS: StatusFilter[] = ['ALL', 'EXECUTED', 'PENDING', 'OUT WINDOW'];
const SIDE_FILTERS: SideFilter[] = ['ALL', 'C', 'P'];

const FILTERS_STORAGE_KEY = 'gh.signaltape.filters.v1';

/** Load persisted filter state with a safe fallback. */
const loadPersistedFilters = (): { status: StatusFilter; side: SideFilter } => {
  try {
    const raw = localStorage.getItem(FILTERS_STORAGE_KEY);
    if (!raw) return { status: 'ALL', side: 'ALL' };
    const parsed = JSON.parse(raw);
    const status = STATUS_FILTERS.includes(parsed.status) ? parsed.status : 'ALL';
    const side = SIDE_FILTERS.includes(parsed.side) ? parsed.side : 'ALL';
    return { status, side };
  } catch {
    return { status: 'ALL', side: 'ALL' };
  }
};

interface FilterChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
  color?: string;
}

const FilterChip: React.FC<FilterChipProps> = ({ label, active, onClick, color }) => (
  <button
    type="button"
    onClick={onClick}
    style={{
      padding: '3px 9px',
      borderRadius: '10px',
      fontSize: '10px',
      fontWeight: 700,
      letterSpacing: '0.04em',
      cursor: 'pointer',
      background: active ? (color || 'var(--accent-spot)') + '22' : 'transparent',
      border: `1px solid ${active ? (color || 'var(--accent-spot)') : 'var(--border-subtle)'}`,
      color: active ? (color || 'var(--accent-spot)') : 'var(--text-muted)',
      transition: 'all 0.15s ease',
    }}
  >
    {label}
  </button>
);

export const SignalTape: React.FC<SignalTapeProps> = ({
  signals,
  notificationPermission,
  requestNotificationPermission,
}) => {
  const [flashIdx, setFlashIdx] = useState<number>(-1);
  const [flashTime, setFlashTime] = useState<number>(0);
  // Initialize from localStorage so filters survive tab switches / reloads
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => loadPersistedFilters().status);
  const [sideFilter, setSideFilter] = useState<SideFilter>(() => loadPersistedFilters().side);

  // Persist any filter change. Wrapped in try/catch — localStorage may be
  // disabled in private browsing or by quota policies.
  useEffect(() => {
    try {
      localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify({ status: statusFilter, side: sideFilter }));
    } catch {
      // Silent fail — UI keeps working, just won't persist
    }
  }, [statusFilter, sideFilter]);

  useEffect(() => {
    if (signals.length === 0) return;
    const lastIdx = signals.length - 1;
    if (lastIdx !== flashIdx) {
      setFlashIdx(lastIdx);
      setFlashTime(Date.now());
    }
  }, [signals, flashIdx]);

  // Filtered view (do not mutate the source — signals prop is shared)
  const filtered = useMemo(() => {
    return signals.filter(sig => {
      if (statusFilter !== 'ALL' && sig.status !== statusFilter) return false;
      if (sideFilter !== 'ALL' && sig.side !== sideFilter) return false;
      return true;
    });
  }, [signals, statusFilter, sideFilter]);

  // Counts per status for chip labels
  const counts = useMemo(() => {
    const c = { EXECUTED: 0, PENDING: 0, 'OUT WINDOW': 0 } as Record<StatusFilter, number>;
    for (const s of signals) c[s.status]++;
    return c;
  }, [signals]);

  const statusColor: Record<StatusFilter, string> = {
    ALL: 'var(--accent-spot)',
    EXECUTED: 'var(--accent-call)',
    PENDING: '#f59e0b',
    'OUT WINDOW': 'var(--text-muted)',
  };

  const handleExport = () => {
    // Export the currently-filtered view so the file matches what the user sees.
    const columns: CsvColumn<BotTapeSignal>[] = [
      { header: 'Timestamp', accessor: s => s.timestamp },
      { header: 'Side', accessor: s => s.side === 'C' ? 'Call' : 'Put' },
      { header: 'Strike', accessor: s => s.strike },
      { header: 'Z-Score', accessor: s => s.z_score.toFixed(2) },
      { header: 'Volume Ratio', accessor: s => s.ratio.toFixed(2) },
      { header: 'Volume', accessor: s => s.volume ?? '' },
      { header: 'Ask', accessor: s => s.ask.toFixed(2) },
      { header: 'Status', accessor: s => s.status },
    ];
    const csv = toCsv(filtered, columns);
    downloadCsv(timestampedFilename('signaltape'), csv);
  };

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
      {/* Header row: title + counts + export */}
      <div
        style={{
          padding: '10px 16px 6px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '12px',
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Tape · Signal Feed
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            {filtered.length === signals.length
              ? `${signals.length} signals`
              : `${filtered.length} of ${signals.length}`}
          </span>
          {/* Notification permission indicator + action */}
          {notificationPermission !== 'unsupported' && (
            <button
              type="button"
              onClick={() => {
                if (notificationPermission === 'default') {
                  void requestNotificationPermission();
                }
              }}
              disabled={notificationPermission !== 'default'}
              title={
                notificationPermission === 'granted'
                  ? 'Browser notifications enabled — sound + system notification on EXECUTED'
                  : notificationPermission === 'denied'
                  ? 'Browser notifications blocked — enable in browser settings'
                  : 'Click to enable browser notifications + sound on EXECUTED'
              }
              style={{
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 700,
                border: '1px solid var(--border-subtle)',
                background: notificationPermission === 'granted' ? 'var(--accent-call-dim)' : 'transparent',
                color: notificationPermission === 'granted' ? 'var(--accent-call)' :
                       notificationPermission === 'denied' ? 'var(--text-muted)' :
                       'var(--accent-spot)',
                cursor: notificationPermission === 'default' ? 'pointer' : 'default',
              }}
            >
              {notificationPermission === 'granted' ? '🔔' :
               notificationPermission === 'denied' ? '🔕' : '🔔+'}
            </button>
          )}
          <button
            type="button"
            onClick={handleExport}
            disabled={filtered.length === 0}
            title="Download filtered signals as CSV"
            style={{
              padding: '3px 10px',
              borderRadius: '4px',
              fontSize: '10px',
              fontWeight: 700,
              letterSpacing: '0.04em',
              border: '1px solid var(--border-subtle)',
              background: 'transparent',
              color: filtered.length === 0 ? 'var(--text-muted)' : 'var(--text-secondary)',
              cursor: filtered.length === 0 ? 'not-allowed' : 'pointer',
              opacity: filtered.length === 0 ? 0.5 : 1,
            }}
          >
            ⬇ Export CSV
          </button>
        </div>
      </div>

      {/* Filter chips row */}
      <div
        style={{
          padding: '6px 16px 8px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          gap: '12px',
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <span style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: '2px' }}>Status</span>
          {STATUS_FILTERS.map(f => (
            <FilterChip
              key={f}
              label={f === 'ALL' ? 'ALL' : `${f} (${counts[f]})`}
              active={statusFilter === f}
              onClick={() => setStatusFilter(f)}
              color={f === 'ALL' ? statusColor.ALL : statusColor[f]}
            />
          ))}
        </div>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <span style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: '2px' }}>Side</span>
          {SIDE_FILTERS.map(f => (
            <FilterChip
              key={f}
              label={f === 'ALL' ? 'ALL' : f === 'C' ? 'Calls' : 'Puts'}
              active={sideFilter === f}
              onClick={() => setSideFilter(f)}
              color={f === 'C' ? 'var(--accent-call)' : f === 'P' ? 'var(--accent-put)' : 'var(--accent-spot)'}
            />
          ))}
        </div>
      </div>

      <div style={{ maxHeight: '140px', overflowY: 'auto' }}>
        {signals.length === 0 && (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: '12px', textAlign: 'center' }}>
            No bot signals yet
          </div>
        )}
        {signals.length > 0 && filtered.length === 0 && (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: '12px', textAlign: 'center' }}>
            No signals match the current filters
          </div>
        )}
        {filtered.map((sig) => {
          const isCall = sig.side === 'C';
          const executed = sig.status === 'EXECUTED';
          // Use timestamp as a stable key + index for flash detection
          const matchedIdx = signals.indexOf(sig);
          const isLatest = matchedIdx === flashIdx && Date.now() - flashTime < 1500;

          return (
            <div
              key={`${sig.timestamp}-${sig.strike}-${sig.side}`}
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
                background: executed ? 'var(--accent-call-dim)' : sig.status === 'PENDING' ? 'rgba(245, 158, 11, 0.12)' : 'transparent',
                color: executed ? 'var(--accent-call)' : sig.status === 'PENDING' ? '#f59e0b' : 'var(--text-muted)',
                border: executed ? '1px solid var(--accent-call)' : sig.status === 'PENDING' ? '1px solid #f59e0b' : '1px solid var(--border-subtle)',
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
