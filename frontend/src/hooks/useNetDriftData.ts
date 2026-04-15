import { useEffect, useState } from 'react';

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

  const fetchDriftHistory = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8000/api/history/net_drift');
      const json = await res.json();
      if (json.data) {
        const processedData = json.data.map((d: any) => ({
          ...d,
          Puts: -Math.abs(d.Puts)
        }));
        setDriftData(processedData);
      }
      if (json.date) {
        setDateStr(json.date);
      }
    } catch (e) {
      console.error("Failed to fetch Net Drift data:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDriftHistory();
    // Poll every 2 minutes because the engine updates it every 2 minutes.
    const intervalId = setInterval(() => {
      fetchDriftHistory();
    }, 120000);
    return () => clearInterval(intervalId);
  }, []);

  return { driftData, dateStr, loading, fetchDriftHistory };
}
