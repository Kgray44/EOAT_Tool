import { useEffect, useState, type PropsWithChildren } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserFreshnessProvider } from "@/app/BrowserFreshnessProvider";
import { createQueryClient } from "@/app/queryClient";

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(createQueryClient);
  useEffect(() => () => queryClient.clear(), [queryClient]);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserFreshnessProvider>{children}</BrowserFreshnessProvider>
    </QueryClientProvider>
  );
}
