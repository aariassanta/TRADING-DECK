/**
 * Tooltip flip logic — no dependencies.
 *
 * computeTooltipFlip(anchorRect, tooltipHeight, viewportPadding?)
 * returns { placement: 'top'|'bottom', style: React.CSSProperties }
 *
 * Logic:
 * - If space above anchor >= tooltipHeight → open upward (placement='top')
 * - Else if space below anchor >= tooltipHeight → flip open downward (placement='bottom')
 * - Else → default to 'top' (safer for score-breakdown tooltips that are tall)
 */
export type Placement = 'top' | 'bottom';

export interface TooltipFlipResult {
  placement: Placement;
  style: React.CSSProperties;
}

export function computeTooltipFlip(
  anchorRect: DOMRect,
  tooltipHeight: number,
  viewportPadding = 8,
): TooltipFlipResult {
  const spaceAbove = anchorRect.top - viewportPadding;
  const spaceBelow = window.innerHeight - anchorRect.bottom - viewportPadding;

  // Prefer upward if there's room
  if (spaceAbove >= tooltipHeight) {
    return { placement: 'top', style: { bottom: 'calc(100% + 8px)' } };
  }

  // Flip to downward if there's room below
  if (spaceBelow >= tooltipHeight) {
    return { placement: 'bottom', style: { top: 'calc(100% + 8px)' } };
  }

  // Default: open downward — upward fallback gets clipped by fixed-position headers (trade drawer)
  return { placement: 'bottom', style: { top: 'calc(100% + 8px)' } };
}
