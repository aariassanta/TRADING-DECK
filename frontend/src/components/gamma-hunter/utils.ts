import type { StrikeLadderRow } from '../../hooks/useMarketData';

/**
 * Filter the strike ladder to a range around the current spot price.
 * Uses ±2 sigma by default; falls back to ±3% of spot if sigmas are missing.
 * Returns the visible rows and the strike row closest to spot (ATM).
 */
export function getVisibleStrikes(
  ladder: StrikeLadderRow[],
  spot: number,
  sigmas: { [key: string]: number } | undefined,
  sigmaKey: '1' | '2' | '3' = '2'
): { visible: StrikeLadderRow[]; atmStrike: StrikeLadderRow | null } {
  if (!spot || ladder.length === 0) {
    return { visible: ladder, atmStrike: null };
  }

  let lower: number;
  let upper: number;

  const upperSigma = sigmas?.[`+${sigmaKey}`];
  const lowerSigma = sigmas?.[`-${sigmaKey}`];

  if (upperSigma && lowerSigma && upperSigma > spot && lowerSigma < spot) {
    lower = lowerSigma;
    upper = upperSigma;
  } else {
    // Fallback: ±3% around spot
    lower = spot * 0.97;
    upper = spot * 1.03;
  }

  const visible = ladder.filter(r => r.strike >= lower && r.strike <= upper);

  const atmStrike = ladder.reduce<StrikeLadderRow | null>((closest, row) => {
    if (!closest) return row;
    return Math.abs(row.strike - spot) < Math.abs(closest.strike - spot) ? row : closest;
  }, null);

  return { visible, atmStrike };
}
