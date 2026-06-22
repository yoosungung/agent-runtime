import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  computeViewportPageLimit,
  type ViewportPageLimitOptions,
} from "../lib/viewportPageLimit";

export function useViewportPagination({
  min = 10,
  max = 50,
  rowHeight = 44,
  chromeHeight = 100,
  bottomMargin = 16,
}: ViewportPageLimitOptions = {}) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const [limit, setLimit] = useState(min);
  const [offset, setOffset] = useState(0);
  const prevLimitRef = useRef(limit);

  const measure = useCallback(() => {
    const anchor = anchorRef.current;
    if (!anchor) {
      return;
    }
    const next = computeViewportPageLimit(
      window.innerHeight,
      anchor.getBoundingClientRect().top,
      { min, max, rowHeight, chromeHeight, bottomMargin },
    );
    setLimit((current) => (current === next ? current : next));
  }, [min, max, rowHeight, chromeHeight, bottomMargin]);

  useLayoutEffect(() => {
    measure();
  }, [measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);

    const anchor = anchorRef.current;
    const observer = anchor ? new ResizeObserver(measure) : null;
    if (anchor && observer) {
      observer.observe(anchor);
    }

    return () => {
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [measure]);

  useEffect(() => {
    if (prevLimitRef.current !== limit) {
      setOffset(0);
      prevLimitRef.current = limit;
    }
  }, [limit]);

  const reset = useCallback(() => setOffset(0), []);

  return { anchorRef, limit, offset, setOffset, reset };
}
