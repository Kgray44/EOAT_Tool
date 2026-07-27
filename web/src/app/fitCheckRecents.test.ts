import { afterEach, describe, expect, it } from "vitest";
import { readFitCheckRecents, rememberFitCheck } from "./fitCheckRecents";

describe("Fit Check browser recents", () => {
  afterEach(() => localStorage.clear());

  it("keeps an in-browser, de-duplicated read-only history", () => {
    rememberFitCheck({
      machine: "52",
      tool: "6201510010",
      eoat: "P4-EOAT-0052",
      result: "COMPATIBLE",
    });
    const current = rememberFitCheck({
      machine: "52",
      tool: "6201510010",
      eoat: "P4-EOAT-0052",
      result: "NEEDS_REVIEW",
    });

    expect(current).toHaveLength(1);
    expect(readFitCheckRecents()[0]).toMatchObject({
      machine: "52",
      result: "NEEDS_REVIEW",
    });
  });
});
