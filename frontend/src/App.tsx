import { useState } from 'react';
import { useMarketData } from './hooks/useMarketData';
import { Activity, Radio, BarChart3, Crosshair, Terminal } from 'lucide-react';
import HeatMap from './components/HeatMap';
import IntervalMap from './components/IntervalMap';

function App() {
  const { connected, connecting, metrics, logs, connectToIBKR, executeTrade, getMetrics, fetchHistory } = useMarketData();
  const [activeTab, setActiveTab] = useState<'heatmap' | 'interval'>('heatmap');
  const [port, setPort] = useState("4002");

  const [tradeForm, setTradeForm] = useState({ 
    type: 'CCS', 
    qty: 1,
    target_mode: 'Delta', 
    target_value: 50, 
    width: 10, 
    tp_pct: 50,
    sl_ratio: 2.5,
    transmit: false 
  });

  return (
    <div className="layout-container" style={{ display: 'flex', height: '100vh', width: '100vw' }}>
      
      {/* 1. SIDEBAR */}
      <aside className="sidebar panel" style={{ width: '300px', margin: '12px', display: 'flex', flexDirection: 'column' }}>
        
        {/* Connection Widget */}
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px', marginBottom: '16px' }}>
            <Radio color={connected ? 'var(--accent-call)' : 'var(--text-muted)'} />
            TRADING DECK
          </h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input 
              type="text" 
              value={port} 
              onChange={e => setPort(e.target.value)}
              className="font-data"
              style={{ flex: 1, background: 'var(--bg-abyss)', border: '1px solid var(--border-subtle)', color: 'white', padding: '8px', borderRadius: '4px' }}
            />
            <button 
              onClick={() => connectToIBKR(parseInt(port))}
              disabled={connected || connecting}
              style={{
                padding: '8px 16px',
                background: connected ? 'var(--bg-surface)' : 'var(--text-primary)',
                color: connected ? 'var(--accent-call)' : 'black',
                border: 'none',
                borderRadius: '4px',
                fontWeight: 'bold',
                cursor: 'pointer'
              }}
            >
              {connected ? 'LIVE' : connecting ? '...' : 'CONNECT'}
            </button>
          </div>
        </div>

        {/* Trade Execution */}
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)', flex: 1 }}>
          <h3 style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Crosshair size={16} /> EXECUTION ENGINE
          </h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Quantity</label>
              <input type="number" value={tradeForm.qty} onChange={e => setTradeForm({...tradeForm, qty: Number(e.target.value)})} style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Target By</label>
              <select 
                value={tradeForm.target_mode} 
                onChange={e => {
                  const mode = e.target.value;
                  setTradeForm({
                    ...tradeForm, 
                    target_mode: mode, 
                    target_value: mode === 'Delta' ? 50 : 1.75 
                  });
                }}
                style={{ background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }}
              >
                <option value="Delta">Delta (Δ)</option>
                <option value="R:R">Risk:Reward</option>
              </select>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>{tradeForm.target_mode === 'Delta' ? 'Target Delta' : 'Min R:R'}</label>
              <input type="number" step="0.1" value={tradeForm.target_value} onChange={e => setTradeForm({...tradeForm, target_value: Number(e.target.value)})} style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Spread Width</label>
              <input type="number" value={tradeForm.width} onChange={e => setTradeForm({...tradeForm, width: Number(e.target.value)})} style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Take Profit %</label>
              <input type="number" value={tradeForm.tp_pct} onChange={e => setTradeForm({...tradeForm, tp_pct: Number(e.target.value)})} style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <label>Stop Loss Mult.</label>
              <input type="number" step="0.1" value={tradeForm.sl_ratio} onChange={e => setTradeForm({...tradeForm, sl_ratio: Number(e.target.value)})} style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
              <label style={{ color: tradeForm.transmit ? 'var(--accent-call)' : 'var(--text-secondary)' }}>
                {tradeForm.transmit ? 'LIVE TRANSMIT' : 'STAGE (Pendiente)'}
              </label>
              <input 
                type="checkbox" 
                checked={tradeForm.transmit} 
                onChange={e => setTradeForm({...tradeForm, transmit: e.target.checked})}
                style={{ width: '18px', height: '18px', cursor: 'pointer', accentColor: 'var(--accent-call)' }} 
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
              <button 
                onClick={() => executeTrade('CCS', tradeForm.qty, tradeForm.target_mode, tradeForm.target_value, tradeForm.width, tradeForm.tp_pct, tradeForm.sl_ratio, tradeForm.transmit)}
                style={{
                  flex: 1,
                  padding: '12px',
                  background: 'var(--accent-put)', // CCS is bearish, typically accent-put (red)
                  color: 'black',
                  fontWeight: '900',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                Launch CCS
              </button>

              <button 
                onClick={() => executeTrade('PCS', tradeForm.qty, tradeForm.target_mode, tradeForm.target_value, tradeForm.width, tradeForm.tp_pct, tradeForm.sl_ratio, tradeForm.transmit)}
                style={{
                  flex: 1,
                  padding: '12px',
                  background: 'var(--accent-call)', // PCS is bullish, typically accent-call (green)
                  color: 'black',
                  fontWeight: '900',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                Launch PCS
              </button>
            </div>
          </div>
        </div>

        {/* Terminal Logs */}
        <div style={{ padding: '12px', height: '200px', background: 'var(--bg-abyss)', overflowY: 'auto', fontSize: '12px' }} className="font-data text-secondary">
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', color: 'var(--text-muted)' }}>
            <Terminal size={14} /> SYSTEM LOGS
          </div>
          {logs.map((log, i) => (
            <div key={i} style={{ marginBottom: '4px' }}>{log}</div>
          ))}
        </div>
      </aside>

      {/* 2. MAIN DASHBOARD */}
      <main style={{ flex: 1, padding: '12px', paddingLeft: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        
        {/* Top Header / Sigma Engine */}
        <header className="panel" style={{ padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>SPX SPOT PRICE</div>
              <div className="font-data text-glow-spot" style={{ fontSize: '32px', color: 'var(--text-primary)', fontWeight: '800' }}>
                {metrics?.spot ? metrics.spot.toFixed(2) : '-----'}
              </div>
            </div>
            
            {/* Sigma Levels */}
            <div style={{ display: 'flex', gap: '16px', borderLeft: '1px solid var(--border-subtle)', paddingLeft: '20px' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--accent-put)' }}>Call Wall</div>
                <div className="font-data text-glow-put" style={{ fontWeight: 'bold' }}>{metrics?.call_wall || '---'}</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--accent-spot)' }}>Gamma Flip</div>
                <div className="font-data text-glow-spot" style={{ fontWeight: 'bold' }}>{metrics?.gamma_flip || '---'}</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--accent-call)' }}>Put Wall</div>
                <div className="font-data text-glow-call" style={{ fontWeight: 'bold' }}>{metrics?.put_wall || '---'}</div>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button 
              onClick={getMetrics}
              style={{ padding: '8px 16px', background: 'transparent', border: '1px solid var(--border-subtle)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}
            >
              <Activity size={16} style={{ verticalAlign: 'middle', marginRight: '6px' }} />
              FORCE REFRESH
            </button>
            <div style={{ display: 'flex', background: 'var(--bg-abyss)', padding: '4px', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}>
              <button 
                onClick={() => setActiveTab('heatmap')}
                style={{ padding: '6px 16px', background: activeTab === 'heatmap' ? 'var(--bg-surface-elevated)' : 'transparent', color: activeTab === 'heatmap' ? 'white' : 'var(--text-muted)', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
              >
                GEX HEATMAP
              </button>
              <button 
                onClick={() => setActiveTab('interval')}
                style={{ padding: '6px 16px', background: activeTab === 'interval' ? 'var(--bg-surface-elevated)' : 'transparent', color: activeTab === 'interval' ? 'white' : 'var(--text-muted)', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
              >
                <BarChart3 size={14} style={{ verticalAlign: 'middle', marginRight: '6px' }}/>
                INTERVAL MAP
              </button>
            </div>
          </div>
        </header>

        {/* Content Area */}
        <section className="panel" style={{ flex: 1, padding: '20px', position: 'relative' }}>
          {!metrics ? (
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', color: 'var(--text-muted)', textAlign: 'center' }}>
              <Activity size={48} className="animate-pulse-glow" style={{ marginBottom: '16px' }} />
              <p>AWAITING MARKET DATA</p>
            </div>
          ) : (
            activeTab === 'heatmap' ? (
              <HeatMap metrics={metrics} />
            ) : (
              <IntervalMap metrics={metrics} fetchHistory={fetchHistory} />
            )
          )}
        </section>
      </main>

    </div>
  );
}

export default App;
