import React, { useState } from 'react';
import type { AlertRule, AlertRuleType } from '../../hooks/useMarketData';

interface AlertRulesProps {
  rules: AlertRule[];
  onChange: (rules: AlertRule[]) => void;
}

const RULE_LABELS: Record<AlertRuleType, string> = {
  SPOT_BREAKS_PUT_WALL:  'Spot breaks Put Wall',
  SPOT_BREAKS_CALL_WALL: 'Spot breaks Call Wall',
  SPOT_CROSSES_GAMMA_FLIP: 'Spot crosses Gamma Flip',
  NET_GEX_CHANGES_SIGN:  'Net GEX flips sign',
  NET_GEX_ABOVE:         'Net GEX > threshold',
  NET_GEX_BELOW:         'Net GEX < threshold',
};

const NEEDS_THRESHOLD: AlertRuleType[] = ['NET_GEX_ABOVE', 'NET_GEX_BELOW'];

/**
 * Inline rule editor for user-configurable alerts. Toggle each rule,
 * edit the threshold (where applicable), and adjust the cooldown in seconds.
 * State is owned by useMarketData and persisted to localStorage there.
 */
export const AlertRules: React.FC<AlertRulesProps> = ({ rules, onChange }) => {
  const [expanded, setExpanded] = useState(false);
  const enabledCount = rules.filter(r => r.enabled).length;

  const updateRule = (id: string, patch: Partial<AlertRule>) => {
    onChange(rules.map(r => (r.id === id ? { ...r, ...patch } : r)));
  };

  return (
    <div
      className="panel"
      style={{ display: 'flex', flexDirection: 'column' }}
    >
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        style={{
          padding: '10px 16px',
          background: 'transparent',
          border: 'none',
          borderBottom: expanded ? '1px solid var(--border-subtle)' : 'none',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          width: '100%',
        }}
      >
        <span style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          🔔 Alert Rules · {enabledCount}/{rules.length} active
        </span>
        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
          {expanded ? '▲ Collapse' : '▼ Configure'}
        </span>
      </button>

      {expanded && (
        <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {rules.map(rule => {
            const needsThreshold = NEEDS_THRESHOLD.includes(rule.type);
            return (
              <div
                key={rule.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '24px 1fr auto auto',
                  gap: '10px',
                  alignItems: 'center',
                  padding: '8px 10px',
                  borderRadius: '4px',
                  background: rule.enabled ? 'rgba(0, 229, 255, 0.04)' : 'transparent',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={e => updateRule(rule.id, { enabled: e.target.checked })}
                  style={{ cursor: 'pointer' }}
                />
                <span style={{ fontSize: '12px', color: 'var(--text-primary)' }}>
                  {RULE_LABELS[rule.type]}
                </span>
                {needsThreshold ? (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--text-muted)' }}>
                    ±
                    <input
                      type="number"
                      step="1"
                      value={rule.threshold ?? 0}
                      onChange={e => updateRule(rule.id, { threshold: Number(e.target.value) })}
                      disabled={!rule.enabled}
                      style={{
                        width: '60px',
                        padding: '2px 6px',
                        background: 'var(--bg-abyss)',
                        color: 'var(--text-primary)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: '3px',
                        fontFamily: 'var(--font-data)',
                        fontSize: '11px',
                      }}
                    />
                    M
                  </label>
                ) : (
                  <span />
                )}
                <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--text-muted)' }}>
                  <input
                    type="number"
                    min={0}
                    step={30}
                    value={rule.cooldownSec ?? 300}
                    onChange={e => updateRule(rule.id, { cooldownSec: Math.max(0, Number(e.target.value)) })}
                    disabled={!rule.enabled}
                    style={{
                      width: '60px',
                      padding: '2px 6px',
                      background: 'var(--bg-abyss)',
                      color: 'var(--text-primary)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: '3px',
                      fontFamily: 'var(--font-data)',
                      fontSize: '11px',
                    }}
                  />
                  s cd
                </label>
              </div>
            );
          })}
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: 1.5, marginTop: '4px' }}>
            Sound + browser notification (if granted) fire on each rule. Cooldown prevents re-firing for N seconds.
          </div>
        </div>
      )}
    </div>
  );
};
