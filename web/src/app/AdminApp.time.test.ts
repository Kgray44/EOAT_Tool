import { describe, expect, it } from "vitest";

import { formatTime } from "../lib/time";

describe("Admin timestamp display", () => {
  it("renders an explicit UTC audit instant in the browser's Eastern timezone", () => {
    const rendered = formatTime("2026-08-20T17:09:20Z", "America/New_York");

    expect(rendered).toContain("1:09:20 PM");
    expect(rendered).toMatch(/EDT|GMT-4/);
  });
});
