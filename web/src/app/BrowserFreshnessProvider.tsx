import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type PropsWithChildren,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import {
  reconcileBrowserFreshness,
  type BrowserFreshnessState,
  type ObservedQuery,
} from "@/app/browserFreshness";
import { BROWSER_DATA_REFRESH_INTERVAL_MS } from "@/app/queryClient";

function performanceNow(): number {
  return typeof performance === "undefined" ? 0 : performance.now();
}

class BrowserFreshnessStore {
  private listeners = new Set<() => void>();
  private state: BrowserFreshnessState = { latestRefreshFailed: false };

  getSnapshot = () => this.state;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  reconcile(queries: readonly ObservedQuery[]) {
    const next = reconcileBrowserFreshness(
      this.state,
      queries,
      performanceNow(),
    );
    if (next === this.state) return;
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }
}

const BrowserFreshnessContext = createContext<BrowserFreshnessStore | null>(
  null,
);

function isDataStatusKey(key: readonly unknown[]): boolean {
  return key.length === 1 && key[0] === "data-status";
}

function isAuthenticationKey(key: readonly unknown[]): boolean {
  return key.length === 1 && key[0] === "authentication-session";
}

function BrowserFreshnessObserver({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const store = useMemo(() => new BrowserFreshnessStore(), []);
  useQuery({
    queryKey: ["data-status"],
    queryFn: () => apiClient.getDataStatus(),
    refetchInterval: BROWSER_DATA_REFRESH_INTERVAL_MS,
  });

  useEffect(() => {
    const seenDataUpdates = new Map<string, number>();
    let scheduled = false;
    const refreshServerTimeAfterDataSuccess = () => {
      const queries = queryClient.getQueryCache().getAll();
      for (const query of queries) {
        if (
          !query.isActive() ||
          isDataStatusKey(query.queryKey) ||
          isAuthenticationKey(query.queryKey) ||
          query.state.status !== "success"
        )
          continue;
        const identity = query.queryHash;
        const previousUpdate = seenDataUpdates.get(identity) ?? 0;
        if (query.state.dataUpdatedAt > previousUpdate) {
          seenDataUpdates.set(identity, query.state.dataUpdatedAt);
          void queryClient.refetchQueries({
            queryKey: ["data-status"],
            exact: true,
          });
        }
      }
    };
    const reconcile = () => {
      scheduled = false;
      refreshServerTimeAfterDataSuccess();
      store.reconcile(
        queryClient
          .getQueryCache()
          .getAll()
          .map((query) => ({
            active: query.isActive(),
            data: query.state.data,
            dataUpdatedAt: query.state.dataUpdatedAt,
            fetching: query.state.fetchStatus !== "idle",
            key: query.queryKey,
            status: query.state.status,
          })),
      );
    };
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      queueMicrotask(reconcile);
    };
    schedule();
    return queryClient.getQueryCache().subscribe(schedule);
  }, [queryClient, store]);

  return (
    <BrowserFreshnessContext.Provider value={store}>
      {children}
    </BrowserFreshnessContext.Provider>
  );
}

export function BrowserFreshnessProvider({ children }: PropsWithChildren) {
  return <BrowserFreshnessObserver>{children}</BrowserFreshnessObserver>;
}

export function useBrowserFreshness(): BrowserFreshnessState {
  const store = useContext(BrowserFreshnessContext);
  if (!store)
    throw new Error(
      "useBrowserFreshness must be used within BrowserFreshnessProvider",
    );
  return useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  );
}
