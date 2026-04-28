import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, err: unknown) => {
        const status = (err as { status?: number })?.status;
        return status !== 401 && status !== 403 && count < 2;
      },
    },
  },
});
