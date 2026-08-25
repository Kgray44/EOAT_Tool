import { describe, expect, it } from "vitest";
import {
  INTERNAL_SEMANTIC_SENTINELS,
  normalizeAuthoritativeValue,
  presentationText,
} from "./presentation";
import { canonicalQrPayload } from "./qr";
import { decodeRouteIdentifier, entityPath } from "./routes";

describe("authoritative presentation boundary", () => {
  it("keeps the known semantic sentinels distinct and non-routable", () => {
    expect(normalizeAuthoritativeValue("UNKNOWN_NOT_VERIFIED")).toMatchObject({
      kind: "sentinel",
      display: "Not verified",
      routable: false,
    });
    expect(normalizeAuthoritativeValue("NONE_OBSERVED")).toMatchObject({
      kind: "sentinel",
      display: "No assignment observed",
      routable: false,
    });
    expect(Object.keys(INTERNAL_SEMANTIC_SENTINELS)).toEqual([
      "UNKNOWN_NOT_VERIFIED",
      "NONE_OBSERVED",
    ]);
  });

  it("preserves legitimate uppercase identifiers but keeps absent values honest", () => {
    expect(normalizeAuthoritativeValue("TOOL-ABC-17")).toMatchObject({
      kind: "identifier",
      display: "TOOL-ABC-17",
      routable: true,
    });
    expect(normalizeAuthoritativeValue(null)).toMatchObject({
      kind: "unavailable",
    });
    expect(normalizeAuthoritativeValue(" ")).toMatchObject({
      kind: "unavailable",
    });
  });

  it("presents numeric and boolean profile values without treating them as identifiers", () => {
    expect(presentationText(0)).toBe("0");
    expect(presentationText(false)).toBe("No");
  });

  it("rejects known sentinels for routes and QR labels", () => {
    expect(entityPath("tool", "UNKNOWN_NOT_VERIFIED")).toBeUndefined();
    expect(
      decodeRouteIdentifier("/tools/NONE_OBSERVED", "tool"),
    ).toBeUndefined();
    expect(() =>
      canonicalQrPayload(
        "tool",
        "UNKNOWN_NOT_VERIFIED",
        "https://atlas.example",
      ),
    ).toThrow();
  });
});
