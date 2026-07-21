import { canonicalQrPayload, isUnsafeQrOrigin } from "@/api/qr";
import { decodeRouteIdentifier, entityPath } from "@/api/routes";

describe("entity paths and QR payloads", () => {
  it("encodes immutable entity path segments without accepting a nested path", () => {
    expect(entityPath("tool", "Tool / A+1")).toBe("/tools/Tool%20%2F%20A%2B1");
    expect(decodeRouteIdentifier("/tools/Tool%20A%2B1", "tool")).toBe(
      "Tool A+1",
    );
    expect(decodeRouteIdentifier("/tools/Tool%2FA", "tool")).toBeUndefined();
  });
  it("builds an absolute QR payload and flags unsafe label origins", () => {
    expect(canonicalQrPayload("eoat", "E A", "https://atlas.example")).toBe(
      "https://atlas.example/eoats/E%20A",
    );
    expect(isUnsafeQrOrigin("http://localhost:5173")).toBe(true);
    expect(isUnsafeQrOrigin("https://atlas.example")).toBe(false);
  });
});
