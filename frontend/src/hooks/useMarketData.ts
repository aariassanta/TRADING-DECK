import { useState, useEffect } from 'react';

export interface GexData {
  gex_by_expiry: { [expiry: string]: { [strike: string]: number } };
  gex_profile: { [strike: string]: number };
  expiries: string[];
  spot: number;
  call_wall: number | null;
  put_wall: number | null;
  gamma_flip: number | null;
  sigmas: { [key: string]: number };
  dark_gamma: any[];
}

export interface MetricPayload {
  data: GexData;
}

export function useMarketData() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [metrics, setMetrics] = useState<GexData | null>(null);
  const [logs, setLogs] = useState<string[]>([]);

  const WsUrl = "ws://localhost:8000/ws/market_data";
  const ApiUrl = "http://localhost:8000/api";

  const addLog = (msg: string) => {
    setLogs(prev => {
      const newLogs = [...prev, `> ${msg}`];
      if (newLogs.length > 50) return newLogs.slice(newLogs.length - 50);
      return newLogs;
    });
  };

  useEffect(() => {
    // Check initial connection status
    fetch(`${ApiUrl}/status`)
      .then(res => res.json())
      .then(data => setConnected(data.connected))
      .catch(() => setConnected(false));

    let ws: WebSocket;
    let reconnectTimeout: ReturnType<typeof setTimeout>;

    const connectWS = () => {
      ws = new WebSocket(WsUrl);

      ws.onopen = () => {
        addLog("WebSocket Connected.");
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'log') {
            addLog(payload.message);
          } else if (payload.type === 'metrics') {
            setMetrics(payload.data);
          }
        } catch (e) {
          console.error("WS Parse Error", e);
        }
      };

      ws.onclose = () => {
        addLog("WebSocket disconnected. Reconnecting in 5s...");
        reconnectTimeout = setTimeout(connectWS, 5000);
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        ws.close();
      };
    };

    connectWS();

    return () => {
      clearTimeout(reconnectTimeout);
      if (ws) {
        ws.onclose = null; // Prevent reconnect on unmount
        ws.close();
      }
    };
  }, []);

  const connectToIBKR = async (port: number = 4002) => {
    setConnecting(true);
    addLog(`Connecting to IBKR on port ${port}...`);
    try {
      const res = await fetch(`${ApiUrl}/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ port })
      });
      const data = await res.json();
      if (data.status === 'success') {
        setConnected(true);
        addLog(data.message);
      } else {
        addLog(`Error: ${data.message}`);
      }
    } catch (e: any) {
      addLog(`Failed to connect: ${e.message}`);
    } finally {
      setConnecting(false);
    }
  };

  const getMetrics = async () => {
    addLog("Requesting manual GEX Scrape...");
    try {
      const res = await fetch(`${ApiUrl}/metrics`);
      const payload = await res.json();
      if (payload.status === "success" && payload.data) {
        setMetrics(payload.data);
      }
    } catch (e: any) {
      addLog(`Metrics fetch failed: ${e.message}`);
    }
  };

  const executeTrade = async (type: string, qty: number, target_mode: string, target_value: number, width: number, tp_pct: number, sl_ratio: number, transmit: boolean) => {
    addLog(`Transmitting [${type}] Order to Backend... (Live: ${transmit})`);
    try {
      await fetch(`${ApiUrl}/trade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trade_type: type, qty, target_mode, target_value, width, tp_pct, sl_ratio, transmit })
      });
    } catch (e: any) {
      addLog(`Trade payload failed: ${e.message}`);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${ApiUrl}/history`);
      const payload = await res.json();
      return payload; // Returns { data: [], date: "..." }
    } catch (e) {
      console.error(e);
      return { data: [], date: "" };
    }
  };

  return {
    connected,
    connecting,
    metrics,
    logs,
    connectToIBKR,
    getMetrics,
    executeTrade,
    fetchHistory
  };
}
