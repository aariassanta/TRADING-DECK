import { Radio } from 'lucide-react';

interface ConnectionWidgetProps {
  port: string;
  setPort: (v: string) => void;
  connected: boolean;
  connectedLive: boolean;
  connecting: boolean;
  connectToIBKR: (port: number) => void;
  connectLive: () => void;
}

export function ConnectionWidget({
  port, setPort, connected, connectedLive, connecting, connectToIBKR, connectLive
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
            color: 'white', padding: '8px', borderRadius: '4px',
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
    </div>
  );
}