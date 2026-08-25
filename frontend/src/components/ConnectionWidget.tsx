import { Radio, Shield, ShieldOff } from 'lucide-react';

interface ConnectionWidgetProps {
  port: string;
  setPort: (v: string) => void;
  connected: boolean;
  connectedLive: boolean;
  connecting: boolean;
  liveTradingArmed: boolean;
  connectToIBKR: (port: number) => void;
  connectLive: () => void;
  armLiveTrading: () => void;
  disarmLiveTrading: () => void;
}

export function ConnectionWidget({
  port, setPort, connected, connectedLive, connecting, liveTradingArmed,
  connectToIBKR, connectLive, armLiveTrading, disarmLiveTrading
}: ConnectionWidgetProps) {
  return (
    <div style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)', flexShrink: 0 }}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px', marginBottom: '16px' }}>
        <Radio color={connected ? 'var(--accent-call)' : 'var(--text-muted)'} />
        TRADING DECK
      </h2>
      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          id="port-input"
          type="text"
          value={port}
          onChange={e => setPort(e.target.value)}
          className="font-data"
          style={{
            flex: 1, background: 'var(--bg-abyss)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-primary)', padding: '8px', borderRadius: '4px',
          }}
        />
        <button
          id="connect-btn"
          onClick={() => connectToIBKR(parseInt(port))}
          disabled={connected || connecting}
          style={{
            padding: '8px 16px',
            background: connected ? 'var(--bg-surface)' : 'var(--text-primary)',
            color: connected ? 'var(--accent-call)' : 'black',
            border: 'none', borderRadius: '4px',
            fontWeight: 'bold', cursor: 'pointer',
          }}
        >
          {connected ? 'LIVE' : connecting ? '...' : 'CONNECT'}
        </button>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
        <button
          onClick={() => connectLive()}
          disabled={connectedLive || connecting}
          style={{
            flex: 1,
            padding: '8px 16px',
            background: connectedLive ? 'var(--bg-surface)' : 'var(--accent-put)',
            color: connectedLive ? 'var(--accent-put)' : 'black',
            border: 'none', borderRadius: '4px',
            fontWeight: 'bold', cursor: 'pointer',
          }}
        >
          {connectedLive ? 'REAL CONNECTED (4001)' : 'CONNECT REAL'}
        </button>
      </div>

      {/* Live trading safety gate */}
      <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <button
          id="arm-live-btn"
          onClick={() => liveTradingArmed ? disarmLiveTrading() : armLiveTrading()}
          disabled={!connectedLive}
          title={connectedLive ? '' : 'Connect to LIVE account first'}
          style={{
            flex: 1,
            padding: '8px 16px',
            background: liveTradingArmed ? 'var(--accent-put)' : 'var(--bg-surface)',
            color: liveTradingArmed ? 'var(--text-primary)' : 'var(--text-muted)',
            border: liveTradingArmed ? '2px solid var(--accent-put)' : '1px solid var(--border-subtle)',
            borderRadius: '4px',
            fontWeight: 'bold',
            cursor: connectedLive ? 'pointer' : 'not-allowed',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
            animation: liveTradingArmed ? 'pulse 2s infinite' : 'none',
          }}
        >
          {liveTradingArmed ? <Shield size={14} /> : <ShieldOff size={14} />}
          {liveTradingArmed ? 'LIVE ARMED' : 'ARM LIVE TRADING'}
        </button>
      </div>
      {liveTradingArmed && (
        <div style={{ marginTop: '4px', fontSize: '10px', color: 'var(--accent-put)', textAlign: 'center' }}>
          ⚠️ Live orders will transmit. Disarm to disable.
        </div>
      )}
    </div>
  );
}