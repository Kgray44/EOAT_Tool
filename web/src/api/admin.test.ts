import { afterEach, describe, expect, it, vi } from "vitest";

import { adminFetch, AdminApiError } from "./admin";

describe("adminFetch", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the browser session and surfaces a safe request-correlated denial", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ message: "Administrator access required.", error_code: "PERMISSION_DENIED", request_id: "req-42" }), { status: 403 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(adminFetch("/api/v1/admin/audit/events")).rejects.toEqual(
      new AdminApiError("Administrator access required.", 403, "req-42", "PERMISSION_DENIED"),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/audit/events",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
