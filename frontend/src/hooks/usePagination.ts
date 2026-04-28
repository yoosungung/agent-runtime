import { useState, useCallback } from "react";

export function usePagination(defaultLimit = 50) {
  const [limit, setLimit] = useState(defaultLimit);
  const [offset, setOffset] = useState(0);

  const goToPage = useCallback(
    (page: number) => setOffset(page * limit),
    [limit],
  );
  const reset = useCallback(() => setOffset(0), []);

  return { limit, offset, setLimit, setOffset, goToPage, reset };
}
