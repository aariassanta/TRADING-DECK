import React from 'react';
import {
  ComposedChart,
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
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
          
          // Interpolate exact physical level to equivalent Spot level on right axis
          let rightEquiv = rightMin + ((entry.value - leftMin) / (leftMax - leftMin)) * (rightMax - rightMin);
          let formattedEquiv = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rightEquiv);

          return (
            <p key={index} style={{ color: entry.color, margin: '4px 0' }}>
              {entry.name}: {formatMillions(entry.value)} <span style={{ color: '#a0aab2', fontWeight: 'normal' }}>@ {formattedEquiv}</span>
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
    return (
      <div style={{ backgroundColor: '#1b2a22', border: '1px solid #2d4236', color: '#fff', borderRadius: '6px', padding: '10px' }}>
        <p style={{ color: '#889890', margin: '0 0 8px 0' }}>{label}</p>
        <p style={{ color: payload[0].color, margin: '4px 0', fontWeight: 'bold' }}>
          Volume: {formatVolume(payload[0].value)}
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
  if (!data || data.length === 0) {
    return (
      <div style={{ backgroundColor: '#131b18', padding: '1rem', borderRadius: '8px', marginTop: '1rem', border: '1px solid #1a2a22' }}>
        <h3 style={{ color: '#fff', textAlign: 'center' }}>Net Drift (Premium) - SPX</h3>
        <p style={{ color: '#889890', textAlign: 'center' }}>No live 0DTE premium data recorded yet for {dateStr || 'today'}.</p>
      </div>
    );
  }

  // Explicit bounds for tooltip interpolation
  let maxCall = Math.max(...data.map(d => d.Calls), 0);
  let minPut = Math.min(...data.map(d => d.Puts), 0);
  let absMaxPremium = Math.max(maxCall, Math.abs(minPut)) * 1.1; // 10% padding
  if (absMaxPremium === 0) absMaxPremium = 1_000_000;
  const domainLeft = [-absMaxPremium, absMaxPremium];

  const spotMin = Math.min(...data.map(d => d.Spot));
  const spotMax = Math.max(...data.map(d => d.Spot));
  const domainRight = [spotMin - 5, spotMax + 5];

  const currentValues = data.length > 0 ? data[data.length - 1] : { Calls: 0, Puts: 0, Spot: 0 };

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

      <div style={{ display: 'flex', justifyContent: 'center', gap: '1.5rem', color: '#a0aab2', fontSize: '0.9rem' }}>
         <span><span style={{ backgroundColor: '#00ff41', display: 'inline-block', width: '10px', height:'10px', borderRadius: '50%', marginRight: '6px' }}></span>Calls <span style={{ color: '#00ff41', fontWeight: 'bold' }}>{formatMillions(currentValues.Calls)}</span></span>
         <span><span style={{ backgroundColor: '#ff2a2a', display: 'inline-block', width: '10px', height:'10px', borderRadius: '50%', marginRight: '6px' }}></span>Puts <span style={{ color: '#ff2a2a', fontWeight: 'bold' }}>{formatMillions(currentValues.Puts)}</span></span>
         <span><span style={{ backgroundColor: '#ffffff', display: 'inline-block', width: '12px', height:'2px', marginRight: '6px', verticalAlign: 'middle' }}></span>Spot <span style={{ color: '#ffffff', fontWeight: 'bold' }}>{new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(currentValues.Spot)}</span></span>
      </div>

      {/* Primary Chart (Premium & Spot) */}
      <div style={{ height: 400, width: '100%' }}>
        <ResponsiveContainer>
          <ComposedChart data={data} syncId="netDriftSync" margin={{ top: 10, right: 30, left: 30, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1d2e24" vertical={false} />
            <XAxis dataKey="time" tick={{ fill: '#889890' }} tickLine={false} tickMargin={10} minTickGap={30} />
            
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
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              domain={domainRight} 
              tick={{ fill: '#889890', fontSize: 12 }} 
              axisLine={false} 
              tickLine={false} 
              label={{ value: 'Underlying ($)', angle: 90, position: 'insideRight', fill: '#fff', fontSize: 13, offset: -15 }}
            />
            <Tooltip content={<CustomPremiumTooltip domainLeft={domainLeft} domainRight={domainRight} />} cursor={{ stroke: '#2d4236', strokeDasharray: '3 3' }} />
            
            <Line yAxisId="left" type="monotone" dataKey="Calls" stroke="#00ff41" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line yAxisId="left" type="monotone" dataKey="Puts" stroke="#ff2a2a" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line yAxisId="right" type="stepAfter" dataKey="Spot" stroke="#ffffff" strokeWidth={2.5} dot={false} isAnimationActive={false} opacity={0.9} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Secondary Chart (Volume) */}
      <div style={{ height: 140, width: '100%' }}>
        <ResponsiveContainer>
          <AreaChart data={data} syncId="netDriftSync" margin={{ top: 0, right: 30, left: 30, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1d2e24" vertical={false} />
            <XAxis dataKey="time" tick={{ fill: '#889890', fontSize: 12 }} tickLine={false} minTickGap={30} />
            <YAxis 
              tickFormatter={formatThousands} 
              tick={{ fill: '#889890', fontSize: 12 }} 
              axisLine={false} 
              tickLine={false}
              label={{ value: 'Volume', angle: -90, position: 'insideLeft', fill: '#fff', fontSize: 13, offset: -15 }}
            />
            <Tooltip content={<CustomVolumeTooltip />} cursor={{ stroke: '#2d4236', strokeDasharray: '3 3' }} />
            <Area type="monotone" dataKey="Volume" stroke="#06db41" fill="#06db41" fillOpacity={0.2} strokeWidth={2} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
