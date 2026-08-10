import { apiClient, sessionHasPermission } from "@/api/client";

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
  it("uses server-issued effective permissions only for UI affordances", () => {
    expect(
      sessionHasPermission(
        { authenticated: true, permissions: ["asset.write"] },
        "asset.write",
      ),
    ).toBe(true);
    expect(
      sessionHasPermission(
        { authenticated: true, permissions: ["asset.write"] },
        "settings.edit",
      ),
    ).toBe(false);
    expect(sessionHasPermission(null, "asset.write")).toBe(false);
  });

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

  it("reads truthful freshness metadata through the read-only data-status endpoint", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "available",
          data_revision: 7,
          data_last_modified_at: "2026-07-27T12:00:00Z",
          server_time: "2026-07-27T12:01:00Z",
          source: "mysql",
          environment: "fixture",
        }),
        { status: 200 },
      ),
    );
    await expect(apiClient.getDataStatus(fetcher)).resolves.toMatchObject({
      data_revision: 7,
      status: "available",
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/data-status",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("rejects malformed successful responses", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("not-json", { status: 200 }));
    await expect(apiClient.getHealth(fetcher)).rejects.toMatchObject({
      kind: "malformed-response",
    });
  });

  it("encodes EOAT identifiers and distinguishes a timeout", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValue(new DOMException("aborted", "AbortError"));
    await expect(
      apiClient.getEoatProfile("EOAT / 1", fetcher),
    ).rejects.toMatchObject({
      kind: "timeout",
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/eoats/EOAT%20%2F%201",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("allows only the dedicated non-persisting Fit Check POST", async () => {
    const fitResult = {
      overall_result: "COMPATIBLE",
      machine_tool_result: {
        pair: "machine_tool",
        result: "COMPATIBLE",
        reason: "fixture",
      },
      machine_eoat_result: {
        pair: "machine_eoat",
        result: "COMPATIBLE",
        reason: "fixture",
      },
      tool_eoat_result: {
        pair: "tool_eoat",
        result: "COMPATIBLE",
        reason: "fixture",
      },
      reasons: [],
      warnings: [],
      unknown_relationships: [],
      alternative_compatible_eoats: [],
      stored: false,
    };
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(fitResult), { status: 200 }),
      );
    await apiClient.evaluateWebFitCheck(
      { machine_number: "M/1", tool_number: "T1", eoat_identifier: "E1" },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/web-fit-checks/evaluate",
      expect.objectContaining({
        method: "POST",
        headers: expect.not.objectContaining({
          "X-EOAT-Device-Token": expect.anything(),
        }),
      }),
    );
  });

  it("gets compatibility-filtered Fit Check options with encoded selection parameters", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          machines: [],
          tools: [],
          eoats: [],
          warnings: [],
          unresolved_inputs: [],
        }),
        { status: 200 },
      ),
    );

    await apiClient.getWebFitCheckOptions(
      { plant_code: "Plant 4", machine_number: "M/1", tool_number: "T1" },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/web-fit-checks/options?plant_code=Plant+4&machine_number=M%2F1&tool_number=T1",
      expect.objectContaining({ method: "GET" }),
    );
  });
});
