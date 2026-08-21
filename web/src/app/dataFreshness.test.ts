import { describe, expect, it } from "vitest";

import { formatLastUpdated, freshnessState } from "./dataFreshness";

const current = {
  status: "available" as const,
  data_revision: 3,
  data_last_modified_at: "2026-08-21T19:27:18Z",
  server_time: "2026-08-21T19:28:00Z",
};

describe("data freshness presentation", () => {
  it("uses the server timestamps for healthy and stale state", () => {
    expect(freshnessState(current)).toBe("healthy");
    expect(
      freshnessState({
        ...current,
        data_last_modified_at: "2026-08-19T19:27:18Z",
      }),
    ).toBe("stale");
  });

  it("uses a compact date and time separated by a middle dot", () => {
    expect(formatLastUpdated(current.data_last_modified_at)).toContain(" · ");
  });
});
