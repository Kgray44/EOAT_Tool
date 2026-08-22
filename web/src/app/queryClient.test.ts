import { describe, expect, it } from "vitest";

import {
  BROWSER_DATA_REFRESH_INTERVAL_MS,
  createQueryClient,
} from "./queryClient";

describe("EOAT browser refresh query behavior", () => {
  it("refreshes active data queries on focus, reconnect, and a bounded interval", () => {
    const queries = createQueryClient().getDefaultOptions().queries;

    expect(queries?.refetchOnWindowFocus).toBe("always");
    expect(queries?.refetchOnReconnect).toBe("always");
    expect(queries?.refetchInterval).toBe(BROWSER_DATA_REFRESH_INTERVAL_MS);
  });
});
