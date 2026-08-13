import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi, adminFetch, AdminApiError } from "./admin";

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

describe("admin data discovery", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("requests archived records only when an administrator explicitly opts in", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await adminApi.assets("eoats", "EOAT-42", true);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/data/eoats?search=EOAT-42&include_archived=true",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
