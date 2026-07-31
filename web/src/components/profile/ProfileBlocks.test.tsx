import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { EoatRelationship } from "@/api/client";
import { RelationshipList } from "./ProfileBlocks";
import {
  deduplicateRelationships,
  presentRelationship,
  relationshipDisplayLabel,
} from "./relationshipPresentation";

const relationship = (
  relationship_type: string,
  identifier: string,
  display_name: string | null,
): EoatRelationship => ({
  relationship_type,
  identifier,
  display_name,
  status: "Observed in legacy source",
  reason: null,
});

describe("RelationshipList", () => {
  it("renders Machine 27 EOAT and Tool relationships without redundant type or identifier text", () => {
    render(
      <MemoryRouter>
        <RelationshipList
          relationships={[
            relationship("eoat", "P4-EOAT-0026", "P4-EOAT-0026"),
            relationship("tool", "6920150021", "Tool 6920150021"),
          ]}
        />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("link", { name: "P4-EOAT-0026" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "6920150021" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Tool Tool 6920150021")).not.toBeInTheDocument();
    expect(
      screen.queryByText("6920150021 — Tool 6920150021"),
    ).not.toBeInTheDocument();
  });

  it("preserves a genuine display name while collapsing only redundant type-plus-identifier names", () => {
    expect(
      relationshipDisplayLabel(
        relationship("tool", "6920150021", "Tool 6920150021"),
      ),
    ).toBe("6920150021");
    expect(
      relationshipDisplayLabel(
        relationship("tool", "6920150021", "Mold cavity assembly"),
      ),
    ).toBe("6920150021 — Mold cavity assembly");
    expect(
      relationshipDisplayLabel(relationship("tool", "6920150021", null)),
    ).toBe("6920150021");
  });

  it("deduplicates only identical stable relationship identities", () => {
    const unique = deduplicateRelationships([
      relationship("tool", "6920150021", "Tool 6920150021"),
      relationship("tool", "6920150021", "Tool 6920150021"),
      relationship("tool", "6920150022", "Tool 6920150022"),
      relationship("eoat", "6920150021", "6920150021"),
    ]);
    expect(unique).toHaveLength(3);
    expect(
      unique.map((item) => `${item.relationship_type}:${item.identifier}`),
    ).toEqual(["tool:6920150021", "tool:6920150022", "eoat:6920150021"]);
  });

  it.each([
    ["ASSIGNED", null, "current-assignment", "Current assignment"],
    ["COMPATIBLE", null, "verified-compatibility", "Verified compatibility"],
    ["INCOMPATIBLE", null, "incompatible", "Incompatible"],
    [
      "INFERRED_COMPATIBLE",
      null,
      "inferred-compatibility",
      "Inferred compatibility",
    ],
    [
      "Observed in legacy source",
      null,
      "historical-observation",
      "Historical observation",
    ],
    ["NEEDS_REVIEW", null, "unverified-assignment", "Unverified assignment"],
    [
      "UNRECOGNIZED_LEGACY_VALUE",
      null,
      "unknown-relationship",
      "Unknown relationship",
    ],
  ])(
    "maps %s to a truthful business meaning",
    (status, reason, state, label) => {
      expect(presentRelationship({ status, reason }).state).toBe(state);
      expect(presentRelationship({ status, reason }).primaryLabel).toBe(label);
    },
  );

  it("does not expose raw legacy semantics and keeps evidence expandable", () => {
    render(
      <MemoryRouter>
        <RelationshipList
          relationships={[
            {
              ...relationship("machine", "27", "Press 27"),
              reason: "OBSERVATION_OR_LATER_LIFECYCLE_EVENT",
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Historical observation")).toBeInTheDocument();
    expect(
      screen.queryByText("Observed in legacy source"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Evidence details")).toBeInTheDocument();
  });
});
