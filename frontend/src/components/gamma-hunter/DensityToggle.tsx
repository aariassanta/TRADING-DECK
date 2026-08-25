import React, { createContext, useContext, useState, useEffect } from 'react';

export type Density = 'comfortable' | 'compact';

interface DensityContextValue {
  density: Density;
  setDensity: (d: Density) => void;
}

const DensityContext = createContext<DensityContextValue>({
  density: 'comfortable',
  setDensity: () => {},
});

const STORAGE_KEY = 'gh.density.v1';

export const DensityProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [density, setDensityState] = useState<Density>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw === 'compact' || raw === 'comfortable') return raw;
    } catch { /* ignore */ }
    return 'comfortable';
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, density);
    } catch { /* ignore */ }
    document.documentElement.dataset.density = density;
  }, [density]);

  const setDensity = (d: Density) => setDensityState(d);

  return (
    <DensityContext.Provider value={{ density, setDensity }}>
      {children}
    </DensityContext.Provider>
  );
};

export const useDensity = () => useContext(DensityContext);

/** Compact mode: 10% smaller everywhere. Applied via CSS var on :root[data-density]. */
export const DensityToggle: React.FC = () => {
  const { density, setDensity } = useDensity();
  const isCompact = density === 'compact';

  return (
    <button
      type="button"
      onClick={() => setDensity(isCompact ? 'comfortable' : 'compact')}
      title={`Switch to ${isCompact ? 'comfortable' : 'compact'} layout`}
      style={{
        padding: '4px 10px',
        borderRadius: '12px',
        border: '1px solid var(--border-subtle)',
        background: 'transparent',
        color: 'var(--text-secondary)',
        fontSize: '10px',
        fontWeight: 700,
        letterSpacing: '0.06em',
        cursor: 'pointer',
      }}
    >
      {isCompact ? 'COMPACT' : '◉ COMPACT'}
    </button>
  );
};

export default DensityToggle;
