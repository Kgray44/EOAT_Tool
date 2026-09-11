import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient } from "@/api/client";
import { CompatibilityEditor } from "./CompatibilityEditor";

describe("CompatibilityEditor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses an authoritative machine selector and sends its canonical number", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["relationship.edit"],
    });
    vi.spyOn(apiClient, "getCatalogOptions").mockImplementation(async (kind) => {
      if (kind === "machine") return [{ value: "P4::M-42", label: "P4 · M-42 · Press 42" }];
      if (kind === "compatibility_status") return [{ value: "verified", label: "Verified" }];
      return [];
    });
    const create = vi
      .spyOn(apiClient, "createCompatibility")
      .mockResolvedValue({ id: 1, row_version: 1 });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <CompatibilityEditor kind="eoat" identifier="P4-EOAT-0101" onSaved={vi.fn()} />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Add compatibility" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Machine number" }), "P4::M-42");
    await user.selectOptions(screen.getByRole("combobox", { name: "Compatibility status" }), "verified");
    await user.click(screen.getByRole("button", { name: "Save compatibility" }));

    expect(create).toHaveBeenCalledWith(
      "eoat-machine",
      expect.objectContaining({
        eoat_identifier: "P4-EOAT-0101",
        machine_number: "M-42",
        compatibility_status: "verified",
      }),
    );
  });
});
