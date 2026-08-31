import { useEffect, useState } from 'react';

/**
 * Track the current viewport width. SSR-safe (returns 1400 on the server).
 * Coalesces resize events via requestAnimationFrame to avoid setState storms.
 */
export const useWindowWidth = (): number => {
  const [width, setWidth] = useState<number>(() =>
    typeof window === 'undefined' ? 1400 : window.innerWidth
  );
  useEffect(() => {
    let rafId: number | null = null;
    const handler = () => {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        setWidth(window.innerWidth);
        rafId = null;
      });
    };
    window.addEventListener('resize', handler);
    return () => {
      window.removeEventListener('resize', handler);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, []);
  return width;
};