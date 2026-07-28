import { afterEach, describe, expect, it } from "vitest";
import { readRecentItems, rememberItem } from "./recent";

const key = "eoat-atlas-web-recent-v1";

afterEach(() => localStorage.clear());

describe("recent entity safety", () => {
  it("does not persist semantic sentinels and discards stale unsafe entries", () => {
    expect(
      rememberItem({
        category: "tool",
        identifier: "UNKNOWN_NOT_VERIFIED",
        label: "unsafe",
      }),
    ).toEqual([]);
    localStorage.setItem(
      key,
      JSON.stringify([
        {
          category: "tool",
          identifier: "NONE_OBSERVED",
          label: "unsafe",
          viewedAt: "2026-01-01T00:00:00Z",
        },
      ]),
    );
    expect(readRecentItems()).toEqual([]);
  });
});
