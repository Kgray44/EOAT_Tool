import { describe, expect, it } from "vitest";

import { createQueryClient } from "./queryClient";

describe("EOAT browser refresh query behavior", () => {
  it("refreshes active data queries on focus and reconnect", () => {
    const queries = createQueryClient().getDefaultOptions().queries;

    expect(queries?.refetchOnWindowFocus).toBe("always");
    expect(queries?.refetchOnReconnect).toBe("always");
    expect(queries?.refetchInterval).toBeUndefined();
  });
});
