import { useEffect, useState, useRef } from 'react';

export interface NetDriftPoint {
  time: string;
  Spot: number;
  Calls: number;
  Puts: number;
  Volume: number;
  CallVolume: number;
  PutVolume: number;
  CallWall?: number | null;
  PutWall?: number | null;
  GammaFlip?: number | null;
}

export function useNetDriftData() {
  const BACKEND = (import.meta.env.VITE_BACKEND_URL as string | undefined)?.replace(/\/+$/, '') ?? '';
  const [driftData, setDriftData] = useState<NetDriftPoint[]>([]);
  const [dateStr, setDateStr] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const fetchRef = useRef(() => {
    fetch(`${BACKEND}/api/history/net_drift?t=${Date.now()}`, { cache: 'no-store' })
      .then(res => res.json())
      .then(json => {
        if (json.data) {
          setDriftData(json.data.map((d: any) => ({ ...d, Puts: -Math.abs(d.Puts) })));
        }
        if (json.date) setDateStr(json.date);
      })
      .catch(e => console.error("Failed to fetch Net Drift data:", e))
      .finally(() => setLoading(false));
  });

  useEffect(() => {
    fetchRef.current();
    const intervalId = setInterval(fetchRef.current, 60000);
    return () => clearInterval(intervalId);
  }, []);

  const fetchDriftHistory = () => fetchRef.current();

  return { driftData, dateStr, loading, fetchDriftHistory };
}
