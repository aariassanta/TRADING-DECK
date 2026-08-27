import React, { useState } from 'react';
import {
  ComposedChart,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';

interface NetDriftChartProps {
  data: any[];
  dateStr: string;
}

const formatMillions = (val: number) => {
  const sign = val < 0 ? '-' : '';
  const absVal = Math.abs(val);
  if (absVal >= 1_000_000) return `${sign}$${(absVal / 1_000_000).toFixed(1)} M`;
  if (absVal >= 1_000) return `${sign}$${(absVal / 1_000).toFixed(1)} K`;
  return `${sign}$${absVal}`;
};

const formatVolume = (val: number) => {
  const absVal = Math.abs(val);
  if (absVal >= 1_000_000) return `${(absVal / 1_000_000).toFixed(1)} M`;
  if (absVal >= 1_000) return `${(absVal / 1_000).toFixed(1)} K`;
  return `${absVal}`;
};

const CustomPremiumTooltip = ({ active, payload, label, domainLeft, domainRight }: any) => {
  if (active && payload && payload.length) {
    const spotVal = payload[0].payload.Spot;
    
    // Map bounds
    const [leftMin, leftMax] = domainLeft || [-1, 1];
    const [rightMin, rightMax] = domainRight || [0, 1];
    
    const spotLabel = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(spotVal);
    
    const isPriceLevel = (key: string) =>
      key === 'CallWall' || key === 'PutWall' || key === 'GammaFlip';
    const isPremium = (key: string) =>
      key === 'Calls' || key === 'PutAbs';

    return (
      <div style={{ backgroundColor: '#1b2a22', border: '1px solid #2d4236', color: '#fff', borderRadius: '6px', padding: '10px' }}>
        <p style={{ color: '#889890', margin: '0 0 8px 0' }}>{label}</p>
        {payload.map((entry: any, index: number) => {
          if (entry.dataKey === 'Spot') {
            return (
              <p key={index} style={{ color: entry.color, margin: '4px 0', fontWeight: 'bold' }}>
                {entry.name}: {spotLabel}
              </p>
            );
          }

          if (isPriceLevel(entry.dataKey)) {
            // Price levels — show directly without interpolation
            const priceLabel = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(entry.value);
            return (
              <p key={index} style={{ color: entry.color, margin: '4px 0' }}>
                {entry.name}: <span style={{ fontWeight: 'bold' }}>{priceLabel}</span>
              </p>
            );
          }

          // Premium values (left axis) — show credit + interpolated equivalent
          let rightEquiv = rightMin + ((entry.value - leftMin) / (leftMax - leftMin)) * (rightMax - rightMin);
          let formattedEquiv = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rightEquiv);

          return (
            <p key={index} style={{ color: entry.color, margin: '4px 0' }}>
              {entry.dataKey === 'PutAbs' ? '|Puts|' : entry.name}: {formatMillions(entry.value)} <span style={{ color: '#a0aab2', fontWeight: 'normal' }}>@ {formattedEquiv}</span>
            </p>
          );
        })}
      </div>
    );
  }
  return null;
};

const CustomVolumeTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const netVol = payload[0].value;
    const color = netVol >= 0 ? '#00ff41' : '#ff2a2a';
    return (
      <div style={{ backgroundColor: '#1b2a22', border: '1px solid #2d4236', color: '#fff', borderRadius: '6px', padding: '10px' }}>
        <p style={{ color: '#889890', margin: '0 0 8px 0' }}>{label}</p>
        <p style={{ color, margin: '4px 0', fontWeight: 'bold' }}>
          Net Vol: {formatVolume(netVol)}
        </p>
      </div>
    );
  }
  return null;
};

const formatThousands = (val: number) => {
  if (Math.abs(val) >= 1_000) return `${(val / 1_000).toFixed(1)} K`;
  return `${val}`;
};

export const NetDriftChart: React.FC<NetDriftChartProps> = ({ data, dateStr }) => {
  const [priceRange, setPriceRange] = useState<'auto' | 'full' | 'walls'>('auto');

  if (!data || data.length === 0) {
    return (
      <div style={{ backgroundColor: '#131b18', padding: '1rem', borderRadius: '8px', marginTop: '1rem', border: '1px solid #1a2a22' }}>
        <p style={{ color: '#889890', textAlign: 'center' }}>No live 0DTE premium data recorded yet for {dateStr || 'today'}.</p>
      </div>
    );
  }

  // Use all data points from current day
  const chartData = data;
  let maxCall = Math.max(...chartData.map(d => d.Calls), 0);
  let minPut = Math.min(...chartData.map(d => d.Puts), 0);
  let absMaxPremium = Math.max(maxCall, Math.abs(minPut)) * 1.1; // 10% padding
  if (absMaxPremium === 0) absMaxPremium = 1_000_000;
  const domainLeft = [-absMaxPremium, absMaxPremium];

  const spotMin = Math.min(...chartData.map(d => d.Spot));
  const spotMax = Math.max(...chartData.map(d => d.Spot));
  const allWalls = chartData.flatMap(d => [d.CallWall, d.PutWall, d.GammaFlip].filter(v => v != null));
  // Deduplicate and sort unique wall values
  const uniqueWalls = [...new Set(allWalls)].sort((a, b) => a - b);
  // Dynamic floor: use Q1 - 1.5×IQR to exclude early-session outliers from the floor itself
  const wallFloor = (() => {
    if (uniqueWalls.length < 4) return uniqueWalls[0] ?? 7300;
    const q1 = uniqueWalls[Math.floor(uniqueWalls.length * 0.25)];
    const q3 = uniqueWalls[Math.floor(uniqueWalls.length * 0.75)];
    const iqr = q3 - q1;
    return Math.max(q1 - 1.5 * iqr, uniqueWalls[0]);
  })();
  const wallMin = allWalls.length ? Math.min(spotMin, ...uniqueWalls) : spotMin;
  const wallMax = allWalls.length ? Math.max(spotMax, ...uniqueWalls) : spotMax;
  const midPrice = (wallMin + wallMax) / 2;

  const domainRight = (() => {
    if (priceRange === 'full')   return [wallMin * 0.95, wallMax * 1.05];
    if (priceRange === 'walls') {
      // IQR + dynamic floor based on lowest wall value
      const vals = [...uniqueWalls].sort((a, b) => a - b);
      const q1 = vals[Math.floor(vals.length * 0.25)];
      const q3 = vals[Math.floor(vals.length * 0.75)];
      const iqr = q3 - q1;
      const lower = Math.max(q1 - 1.5 * iqr, wallFloor);
      const upper = q3 + 1.5 * iqr;
      const filtered = vals.filter(v => v >= lower && v <= upper);
      const useVals = filtered.length >= 2 ? filtered : vals;
      const wMin = Math.max(useVals[0], wallFloor);
      const wMax = useVals[useVals.length - 1];
      const pad = Math.max((wMax - wMin) * 0.02, 1);
      return [wMin - pad, wMax + pad];
    }
    // auto: default behavior
    const padding = Math.max((wallMax - wallMin) * 0.1, 5);
    return [wallMin - padding, wallMax + padding];
  })();

  // Chart data
  const dataWithNet = chartData.map(d => ({
    ...d,
    NetPremium: d.Calls + d.Puts,
    // Display |Puts| as positive so Calls and Put curves cross and reveal Net GEX sign changes
    PutAbs: Math.abs(d.Puts),
    // Net volume: positive = call volume > put volume, negative = vice versa
    NetVolume: (d.CallVolume ?? 0) - (d.PutVolume ?? 0),
    ...(priceRange === 'walls' ? {
      Spot: d.Spot >= wallFloor ? d.Spot : null,
      CallWall: (d.CallWall ?? 0) >= wallFloor ? d.CallWall : null,
      PutWall: (d.PutWall ?? 0) >= wallFloor ? d.PutWall : null,
      GammaFlip: (d.GammaFlip ?? 0) >= wallFloor ? d.GammaFlip : null,
    } : { Spot: d.Spot }),
  }));

  const currentValues = dataWithNet.length > 0 ? dataWithNet[dataWithNet.length - 1] : { Calls: 0, Puts: 0, PutAbs: 0, Spot: 0, NetPremium: 0 };

  return (
    <div style={{
      backgroundColor: '#131b18',
      padding: '1.5rem',
      borderRadius: '8px',
      marginTop: '1rem',
      border: '1px solid #1a2a22',
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem'
    }}>

      <div style={{ display: 'flex', justifyContent: 'center', gap: '1.5rem', color: '#a0aab2', fontSize: '0.9rem', flexWrap: 'wrap', alignItems: 'center' }}>
         <span><span style={{ backgroundColor: '#00ff41', display: 'inline-block', width: '10px', height:'10px', borderRadius: '50%', marginRight: '6px' }}></span>Calls <span style={{ color: '#00ff41', fontWeight: 'bold' }}>{formatMillions(currentValues.Calls)}</span></span>
         <span><span style={{ backgroundColor: '#ff2a2a', display: 'inline-block', width: '10px', height:'10px', borderRadius: '50%', marginRight: '6px' }}></span>|Puts| <span style={{ color: '#ff2a2a', fontWeight: 'bold' }}>{formatMillions(currentValues.PutAbs)}</span></span>
         <span><span style={{ backgroundColor: '#b2babb', display: 'inline-block', width: '12px', height:'2px', borderTop: '2px dotted #b2babb', marginRight: '6px', verticalAlign: 'middle' }}></span>Net <span style={{ color: '#b2babb', fontWeight: 'bold' }}>{formatMillions(currentValues.NetPremium || 0)}</span></span>
         {priceRange === 'walls' && (
           <span><span style={{ backgroundColor: '#ffffff', display: 'inline-block', width: '12px', height:'2px', marginRight: '6px', verticalAlign: 'middle' }}></span>Spot <span style={{ color: '#ffffff', fontWeight: 'bold' }}>{new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(currentValues.Spot)}</span></span>
         )}

         {/* Price range selector */}
         <div style={{ display: 'flex', gap: '4px', marginLeft: '8px', alignItems: 'center' }}>
           <span style={{ fontSize: '10px', color: '#889890' }}>RANGE</span>
           {(['auto', 'full', 'walls'] as const).map(mode => (
             <button
               key={mode}
               onClick={() => setPriceRange(mode)}
               style={{
                 padding: '2px 8px',
                 fontSize: '10px',
                 fontWeight: 'bold',
                 background: priceRange === mode ? 'var(--accent-call)' : 'var(--bg-surface-elevated)',
                 color: priceRange === mode ? 'black' : '#889890',
                 border: 'none',
                 borderRadius: '3px',
                 cursor: 'pointer',
               }}
             >
               {mode.toUpperCase()}
             </button>
           ))}
         </div>
      </div>

      {/* Primary Chart (Premium & Spot) */}
      <div style={{ height: 400, width: '100%' }}>
        <ResponsiveContainer>
          <ComposedChart data={dataWithNet} syncId="netDriftSync" margin={{ top: 10, right: 30, left: 30, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1d2e24" vertical={false} />
            {(priceRange !== 'walls') && (
              <ReferenceLine y={0} yAxisId="left" stroke="#889890" strokeDasharray="3 3" opacity={0.5} />
            )}
            <XAxis dataKey="time" tick={{ fill: '#889890' }} tickLine={false} tickMargin={10} minTickGap={30} />

            {priceRange !== 'walls' && (
              <YAxis
                yAxisId="left"
                orientation="left"
                domain={domainLeft}
                tickFormatter={formatMillions}
                tick={{ fill: '#889890', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                label={{ value: 'Premium ($)', angle: -90, position: 'insideLeft', fill: '#fff', fontSize: 13, offset: -15 }}
              />
            )}
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              width={60}
              domain={domainRight} 
              tick={{ fill: '#889890', fontSize: 12 }} 
              axisLine={false} 
              tickLine={false} 
              label={{ value: 'Underlying ($)', angle: 90, position: 'insideRight', fill: '#fff', fontSize: 13, offset: -15 }}
            />
            <Tooltip content={<CustomPremiumTooltip domainLeft={domainLeft} domainRight={domainRight} />} cursor={{ stroke: '#2d4236', strokeDasharray: '3 3' }} />

            {(priceRange !== 'walls') && (
              <>
                <Line yAxisId="left" type="monotone" dataKey="Calls" stroke="#00ff41" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="left" type="monotone" dataKey="PutAbs" stroke="#ff2a2a" strokeWidth={2} dot={false} isAnimationActive={false} name="PutAbs" />
                <Line yAxisId="left" type="monotone" name="Net Premium" dataKey="NetPremium" stroke="#b2babb" strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} opacity={0.8} />
              </>
            )}
            {(priceRange === 'walls') && (
              <>
                <Line yAxisId="right" type="stepAfter" dataKey="Spot" stroke="#ffffff" strokeWidth={2.5} dot={false} isAnimationActive={false} opacity={0.9} />
                <Line yAxisId="right" type="stepAfter" dataKey="CallWall" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="5 5" dot={false} isAnimationActive={false} />
                <Line yAxisId="right" type="stepAfter" dataKey="PutWall" stroke="#22c55e" strokeWidth={1.5} strokeDasharray="5 5" dot={false} isAnimationActive={false} />
                <Line yAxisId="right" type="stepAfter" dataKey="GammaFlip" stroke="#3b82f6" strokeWidth={1.5} strokeDasharray="5 5" dot={false} isAnimationActive={false} />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Secondary Chart (Net Volume) — hidden in walls mode */}
      {priceRange !== 'walls' && (
      <div style={{ height: 140, width: '100%' }}>
        <ResponsiveContainer>
          <LineChart data={dataWithNet} syncId="netDriftSync" margin={{ top: 0, right: 30, left: 30, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1d2e24" vertical={false} />
            <XAxis dataKey="time" tick={{ fill: '#889890', fontSize: 12 }} tickLine={false} minTickGap={30} />
            <YAxis
              tickFormatter={formatThousands}
              tick={{ fill: '#889890', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              label={{ value: 'Net Vol (Call-Put)', angle: -90, position: 'insideLeft', fill: '#fff', fontSize: 13, offset: -15 }}
            />
            <Tooltip content={<CustomVolumeTooltip />} cursor={{ stroke: '#2d4236', strokeDasharray: '3 3' }} />
            <Line
              type="monotone"
              dataKey="NetVolume"
              stroke="#06db41"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      )}
    </div>
  );
};
