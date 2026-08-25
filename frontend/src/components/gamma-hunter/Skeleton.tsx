import React from 'react';

interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  /** Border-radius shorthand: 'sm' (2px), 'md' (4px), 'lg' (8px), 'pill' (999px), or a number. */
  radius?: 'sm' | 'md' | 'lg' | 'pill' | number;
  /** Whether the skeleton should pulse opacity instead of shimmer. */
  pulse?: boolean;
  className?: string;
}

const radiusValue = (r: SkeletonProps['radius']): string => {
  if (r === undefined) return '4px';
  if (typeof r === 'number') return `${r}px`;
  switch (r) {
    case 'sm': return '2px';
    case 'md': return '4px';
    case 'lg': return '8px';
    case 'pill': return '999px';
  }
};

/**
 * Loading placeholder. Renders an animated block with shimmer (default) or
 * opacity pulse. Use to replace data-bound UI before metrics arrive.
 */
export const Skeleton: React.FC<SkeletonProps> = ({
  width = '100%',
  height = 16,
  radius = 'md',
  pulse = false,
  className,
}) => {
  const radiusPx = radiusValue(radius);
  const style: React.CSSProperties = {
    width,
    height,
    borderRadius: radiusPx,
    background: pulse
      ? 'var(--bg-surface-elevated)'
      : 'linear-gradient(90deg, var(--bg-surface-elevated) 0%, var(--border-subtle) 50%, var(--bg-surface-elevated) 100%)',
    backgroundSize: pulse ? 'auto' : '200% 100%',
    animation: pulse ? 'skeletonPulse 1.6s ease-in-out infinite' : 'skeletonShimmer 1.6s linear infinite',
    border: '1px solid transparent',
  };
  return (
    <>
      <div className={className} style={style} aria-hidden="true" />
      <style>{`
        @keyframes skeletonShimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes skeletonPulse {
          0%, 100% { opacity: 0.55; }
          50%      { opacity: 1; }
        }
      `}</style>
    </>
  );
};

/**
 * Multi-row skeleton block — useful for tables/lists with many rows.
 * Renders a header bar plus N rows of consistent heights.
 */
interface SkeletonListProps {
  rows?: number;
  rowHeight?: number;
  rowGap?: number;
  headerHeight?: number;
  rowWidth?: string;
}

export const SkeletonList: React.FC<SkeletonListProps> = ({
  rows = 8,
  rowHeight = 18,
  rowGap = 6,
  headerHeight = 24,
  rowWidth = '100%',
}) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: rowGap, padding: '12px' }}>
    <Skeleton height={headerHeight} width="60%" />
    {Array.from({ length: rows }).map((_, i) => (
      <Skeleton
        key={i}
        height={rowHeight}
        // Alternate widths to mimic real table columns
        width={i % 3 === 0 ? rowWidth : i % 3 === 1 ? '85%' : '70%'}
      />
    ))}
  </div>
);
