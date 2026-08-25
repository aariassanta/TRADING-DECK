import React, { useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// IRON_FLY window: 0DTE Iron Butterfly, entry 1:40-1:55 PM ET, hold to expiry
// (see bot_engine.py: _evaluate_iron_fly, time window 13:40-13:55 ET).
// ---------------------------------------------------------------------------

interface WindowSpec {
  /** Display label, e.g. "IRON_FLY" */
  label: string;
  /** Window open time in minutes from midnight ET (1:40 PM = 13*60+40 = 820) */
  openMinEt: number;
  /** Window close time in minutes from midnight ET (1:55 PM = 13*60+55 = 835) */
  closeMinEt: number;
  /** Long description for the tooltip */
  description: string;
}

const IRON_FLY_WINDOW: WindowSpec = {
  label: 'IRON_FLY',
  openMinEt: 13 * 60 + 40,   // 820
  closeMinEt: 13 * 60 + 55,  // 835
  description: '0DTE Iron Butterfly entry window on SPXW (1:40-1:55 PM ET). Hold to expiry.',
};

const etParts = (d: Date): { h: number; m: number; s: number } => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(d);
  const lookup: Record<string, string> = {};
  for (const p of parts) lookup[p.type] = p.value;
  return {
    h: Number(lookup.hour ?? 0) % 24,
    m: Number(lookup.minute ?? 0),
    s: Number(lookup.second ?? 0),
  };
};

/**
 * Solve for the UTC instant at which the ET wall clock equals (h, m, s) on
 * the date represented by `nowEt`. Uses a single-shot offset calculation.
 */
const etWallClockToInstant = (nowEt: Date, h: number, m: number, s: number): Date => {
  const candidate = new Date(Date.UTC(
    nowEt.getFullYear(), nowEt.getMonth(), nowEt.getDate(), h, m, s
  ));
  const et = etParts(candidate);
  const etMin = et.h * 60 + et.m + et.s / 60;
  const utcMin = h * 60 + m + s / 60;
  const offsetMin = utcMin - etMin; // EST: +300 (UTC is 5h ahead of ET)
  return new Date(candidate.getTime() - offsetMin * 60_000);
};

type Status = 'before' | 'open' | 'closed';

interface Snapshot {
  status: Status;
  /** Seconds until next event (positive = future). */
  deltaSec: number;
}

const computeSnapshot = (spec: WindowSpec, now: Date): Snapshot => {
  const et = etParts(now);
  const nowMin = et.h * 60 + et.m + et.s / 60;
  // Anchor "today" to the ET calendar day as seen by `now`.
  const todayEt = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));

  if (nowMin < spec.openMinEt) {
    return { status: 'before', deltaSec: (spec.openMinEt - nowMin) * 60 - et.s };
  }
  if (nowMin < spec.closeMinEt) {
    return { status: 'open', deltaSec: (spec.closeMinEt - nowMin) * 60 - et.s };
  }
  // After close: show time until tomorrow's open.
  const openH = Math.floor(spec.openMinEt / 60);
  const openM = spec.openMinEt % 60;
  let nextOpen = etWallClockToInstant(todayEt, openH, openM, 0);
  if (nextOpen.getTime() <= now.getTime()) {
    nextOpen = new Date(nextOpen.getTime() + 24 * 3600 * 1000);
  }
  return { status: 'closed', deltaSec: (nextOpen.getTime() - now.getTime()) / 1000 };
};

const formatHHMMSS = (totalSec: number): string => {
  const abs = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const s = abs % 60;
  const pad = (n: number) => n.toString().padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
};

interface WindowCountdownProps {
  /** Override the default window (for testing). */
  window?: WindowSpec;
}

/**
 * Countdown to the next IRON_FLY entry window. Three states:
 *  - BEFORE: dim color, label "OPENS IN HH:MM:SS" until 1:40 PM ET
 *  - OPEN: bright call-green, label "OPEN · MM:SS LEFT" between 1:40-1:55 PM ET
 *  - CLOSED: muted, label "CLOSED · OPENS IN HH:MM:SS" pointing to next day
 */
export const WindowCountdown: React.FC<WindowCountdownProps> = ({ window: spec = IRON_FLY_WINDOW }) => {
  const [snap, setSnap] = useState<Snapshot>(() => computeSnapshot(spec, new Date()));

  useEffect(() => {
    // Align next tick to the top of the next second for smooth display.
    const msToNext = 1000 - (Date.now() % 1000);
    let interval: ReturnType<typeof setInterval> | undefined;
    const timeout = setTimeout(() => {
      setSnap(computeSnapshot(spec, new Date()));
      interval = setInterval(() => setSnap(computeSnapshot(spec, new Date())), 1000);
    }, msToNext);
    return () => {
      clearTimeout(timeout);
      if (interval) clearInterval(interval);
    };
  }, [spec]);

  const statusColor =
    snap.status === 'open' ? 'var(--accent-call)' :
    snap.status === 'before' ? 'var(--text-secondary)' :
    'var(--text-muted)';

  const statusLabel =
    snap.status === 'open' ? 'OPEN · CLOSES IN' :
    snap.status === 'before' ? 'OPENS IN' :
    'CLOSED · NEXT IN';

  return (
    <div
      title={spec.description}
      style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}
    >
      <div style={{
        fontSize: '9px',
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
      }}>
        {spec.label}
        {snap.status === 'open' && (
          <span
            style={{
              display: 'inline-block',
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--accent-call)',
              boxShadow: '0 0 6px var(--accent-call)',
              animation: 'wcPulse 1s ease-in-out infinite',
            }}
          />
        )}
        <style>{`@keyframes wcPulse { 0%,100% { opacity: 1 } 50% { opacity: 0.35 } }`}</style>
      </div>
      <div
        className="font-data"
        style={{
          fontSize: '20px',
          fontWeight: 700,
          color: statusColor,
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1.1,
        }}
      >
        {formatHHMMSS(snap.deltaSec)}
      </div>
      <div style={{ fontSize: '9px', color: statusColor, letterSpacing: '0.04em' }}>
        {statusLabel}
      </div>
    </div>
  );
};

export default WindowCountdown;
