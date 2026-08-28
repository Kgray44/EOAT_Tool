import { QueryClient } from "@tanstack/react-query";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: "always",
        refetchOnReconnect: "always",
        staleTime: 15_000,
      },
    },
  });
}
