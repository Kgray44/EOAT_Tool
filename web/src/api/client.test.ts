import { apiClient } from "@/api/client";

const health = {
  api_version: "1.4.0",
  application_version: "0.17.2",
  compatible: true,
  writes_enabled: false,
  expected_schema_revision: "20260717_0007",
  api_contract_version: "1.4.0",
  current_schema_revision: "20260717_0007",
};

describe("apiClient", () => {
  it("uses a relative URL and never sends a device-token header", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(health), { status: 200 }));
    await apiClient.getHealth(fetcher);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty(
      "X-EOAT-Device-Token",
    );
  });

  it("reports unavailable API responses distinctly", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ message: "offline" }), { status: 503 }),
      );
    await expect(apiClient.getHealth(fetcher)).rejects.toMatchObject({
      kind: "unavailable",
      status: 503,
    });
  });

  it("rejects malformed successful responses", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("not-json", { status: 200 }));
    await expect(apiClient.getHealth(fetcher)).rejects.toMatchObject({
      kind: "malformed-response",
    });
  });
});
