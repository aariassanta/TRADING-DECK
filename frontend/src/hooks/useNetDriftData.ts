import { useEffect, useState, useRef } from 'react';

export interface NetDriftPoint {
  time: string;
  Spot: number;
  Calls: number;
  Puts: number;
  Volume: number;
}

export function useNetDriftData() {
  const [driftData, setDriftData] = useState<NetDriftPoint[]>([]);
  const [dateStr, setDateStr] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const fetchRef = useRef(() => {
    fetch(`http://127.0.0.1:8000/api/history/net_drift?t=${Date.now()}`, { cache: 'no-store' })
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
