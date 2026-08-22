import { QueryClient } from "@tanstack/react-query";

export const BROWSER_DATA_REFRESH_INTERVAL_MS = 60_000;

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: "always",
        refetchOnReconnect: "always",
        refetchInterval: BROWSER_DATA_REFRESH_INTERVAL_MS,
        staleTime: 15_000,
      },
    },
  });
}
