export interface ViewportPageLimitOptions {
  min?: number;
  max?: number;
  /** Estimated table body row height in px */
  rowHeight?: number;
  /** Table header + paginator + padding below the list */
  chromeHeight?: number;
  bottomMargin?: number;
}

export function computeViewportPageLimit(
  viewportHeight: number,
  anchorTop: number,
  options: ViewportPageLimitOptions = {},
): number {
  const {
    min = 10,
    max = 50,
    rowHeight = 44,
    chromeHeight = 100,
    bottomMargin = 16,
  } = options;

  const available = viewportHeight - anchorTop - chromeHeight - bottomMargin;
  if (available <= 0) {
    return min;
  }

  return Math.min(max, Math.max(min, Math.floor(available / rowHeight)));
}
