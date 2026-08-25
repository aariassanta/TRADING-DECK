import { Crosshair, RotateCcw } from 'lucide-react';

interface TradeForm {
  type: string;
  qty: number | string;
  target_mode: string;
  target_value: number | string;
  width: number | string;
  tp_pct: number | string;
  sl_ratio: number | string;
  transmit: boolean;
}

interface TradeExecutionFormProps {
  tradeForm: TradeForm;
  setTradeForm: React.Dispatch<React.SetStateAction<TradeForm>>;
  targetEnv: 'paper' | 'live';
  executeTrade: (req: any) => void;
  onReset: () => void;
}

export function TradeExecutionForm({ tradeForm, setTradeForm, targetEnv, executeTrade, onReset }: TradeExecutionFormProps) {
  const inputStyle = { width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' };
  const rowStyle = { display: 'flex', justifyContent: 'space-between' as const };
  const labelStyle = { color: 'var(--text-secondary)', fontSize: '12px' };

  return (
    <div style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)', flexShrink: 0 }}>
      <h3 style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'space-between' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Crosshair size={16} /> EXECUTION ENGINE
        </span>
        <button
          id="reset-defaults-btn"
          onClick={onReset}
          title="Reset to factory defaults"
          style={{
            display: 'flex', alignItems: 'center', gap: '4px',
            background: 'none', border: '1px solid var(--border-subtle)',
            color: 'var(--text-muted)', borderRadius: '4px',
            padding: '3px 7px', cursor: 'pointer', fontSize: '10px',
          }}
        >
          <RotateCcw size={10} /> RESET
        </button>
      </h3>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

        <div style={rowStyle}>
          <label style={labelStyle}>Quantity</label>
          <input
            id="qty-input"
            type="number"
            value={tradeForm.qty}
            onChange={e => setTradeForm({ ...tradeForm, qty: e.target.value })}
            style={inputStyle}
          />
        </div>

        <div style={rowStyle}>
          <label style={labelStyle}>Target By</label>
          <select
            id="target-mode-select"
            value={tradeForm.target_mode}
            onChange={e => {
              const mode = e.target.value;
              setTradeForm(prev => ({
                ...prev,
                target_mode: mode,
                target_value: mode === 'Delta' ? 50 : mode === 'R:R' ? 1.75 : prev.target_value,
              }));
            }}
            style={{ width: '80px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }}
          >
            <option value="Delta">Delta</option>
            <option value="R:R">R:R</option>
            <option value="GEX">GEX Wall</option>
          </select>
        </div>

        <div style={rowStyle}>
          <label style={labelStyle}>Target Value</label>
          <input
            id="target-value-input"
            type="number"
            value={tradeForm.target_value}
            onChange={e => setTradeForm({ ...tradeForm, target_value: e.target.value })}
            disabled={tradeForm.target_mode === 'GEX'}
            style={{ ...inputStyle, opacity: tradeForm.target_mode === 'GEX' ? 0.5 : 1 }}
          />
        </div>

        <div style={rowStyle}>
          <label style={labelStyle}>Width (pts)</label>
          <input
            id="width-input"
            type="number"
            value={tradeForm.width}
            onChange={e => setTradeForm({ ...tradeForm, width: e.target.value })}
            style={inputStyle}
          />
        </div>

        <div style={rowStyle}>
          <label style={labelStyle}>Take Profit %</label>
          <input
            id="tp-pct-input"
            type="number"
            value={tradeForm.tp_pct}
            onChange={e => setTradeForm({ ...tradeForm, tp_pct: e.target.value })}
            style={inputStyle}
          />
        </div>

        <div style={rowStyle}>
          <label style={labelStyle}>Stop Loss (xW)</label>
          <input
            id="sl-ratio-input"
            type="number"
            value={tradeForm.sl_ratio}
            onChange={e => setTradeForm({ ...tradeForm, sl_ratio: e.target.value })}
            style={inputStyle}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label style={labelStyle}>Transmit?</label>
          <input
            id="transmit-checkbox"
            type="checkbox"
            checked={tradeForm.transmit}
            onChange={e => setTradeForm({ ...tradeForm, transmit: e.target.checked })}
          />
        </div>

        <div style={rowStyle}>
          <label style={labelStyle}>Stage</label>
          <div style={{ display: 'flex', gap: '4px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
              <input
                type="radio"
                checked={!tradeForm.transmit}
                onChange={() => setTradeForm({ ...tradeForm, transmit: false })}
              />
              STAGE
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
              <input
                type="radio"
                checked={tradeForm.transmit}
                onChange={() => setTradeForm({ ...tradeForm, transmit: true })}
              />
              LIVE
            </label>
          </div>
        </div>

        {/* Execution buttons */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
          <button
            id="launch-ccs-btn"
            onClick={() => {
              if (targetEnv === 'live') {
                if (!window.confirm("🚨 ALERTA CRÍTICA: Estás a punto de enviar una órden simultánea a tu CUENTA REAL. ¿Estás absolutamente seguro de querer proceder?")) return;
              }
              executeTrade({
                trade_type: 'CCS', qty: Number(tradeForm.qty), target_mode: tradeForm.target_mode as any, target_value: Number(tradeForm.target_value),
                width: Number(tradeForm.width), tp_pct: Number(tradeForm.tp_pct), sl_ratio: Number(tradeForm.sl_ratio), transmit: tradeForm.transmit, target_env: targetEnv
              });
            }}
            style={{
              flex: 1, padding: '12px',
              background: 'var(--accent-put)',
              color: 'black', fontWeight: '900',
              border: 'none', borderRadius: '4px', cursor: 'pointer',
            }}
          >
            Launch CCS
          </button>
          <button
            id="launch-pcs-btn"
            onClick={() => {
              if (targetEnv === 'live') {
                if (!window.confirm("🚨 ALERTA CRÍTICA: Estás a punto de enviar una órden simultánea a tu CUENTA REAL. ¿Estás absolutamente seguro de vouloir proceder?")) return;
              }
              executeTrade({
                trade_type: 'PCS', qty: Number(tradeForm.qty), target_mode: tradeForm.target_mode as any, target_value: Number(tradeForm.target_value),
                width: Number(tradeForm.width), tp_pct: Number(tradeForm.tp_pct), sl_ratio: Number(tradeForm.sl_ratio), transmit: tradeForm.transmit, target_env: targetEnv
              });
            }}
            style={{
              flex: 1, padding: '12px',
              background: 'var(--accent-call)',
              color: 'black', fontWeight: '900',
              border: 'none', borderRadius: '4px', cursor: 'pointer',
            }}
          >
            Launch PCS
          </button>
        </div>
      </div>
    </div>
  );
}