import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import { EntityEditor } from "./EntityEditor";

function renderEditor() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <EntityEditor
        kind="machine"
        identifier="M-42"
        rowVersion={3}
        onSaved={vi.fn()}
        fields={[
          { key: "machine_name", label: "Machine name", value: "Press 42" },
          {
            key: "status",
            label: "Status",
            value: "ACTIVE",
            catalog: "status",
          },
        ]}
      />
    </QueryClientProvider>,
  );
}

describe("EntityEditor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not render a mutation affordance for a viewer", async () => {
    const session = vi
      .spyOn(apiClient, "getAuthenticatedSession")
      .mockResolvedValue({ authenticated: true, permissions: [] });
    renderEditor();
    await waitFor(() => expect(session).toHaveBeenCalled());
    expect(
      screen.queryByRole("button", { name: "Edit machine" }),
    ).not.toBeInTheDocument();
  });

  it("submits only changed server-confirmed values for an engineer", async () => {
    const saved = vi.fn();
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["machine.edit"],
    });
    vi.spyOn(apiClient, "getCatalogOptions").mockResolvedValue([
      { value: "active", label: "Active" },
    ]);
    const patch = vi
      .spyOn(apiClient, "patchMachine")
      .mockResolvedValue({ row_version: 4 });
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <EntityEditor
          kind="machine"
          identifier="M-42"
          rowVersion={3}
          onSaved={saved}
          fields={[
            { key: "machine_name", label: "Machine name", value: "Press 42" },
          ]}
        />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Edit machine" }),
    );
    await user.clear(screen.getByRole("textbox", { name: "Machine name" }));
    await user.type(
      screen.getByRole("textbox", { name: "Machine name" }),
      "Press 42A",
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(patch).toHaveBeenCalledWith("M-42", {
      expected_row_version: 3,
      machine_name: "Press 42A",
    });
    expect(saved).toHaveBeenCalledTimes(1);
  });

  it("keeps the editor open and reports a rejected update without pretending it saved", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["machine.edit"],
    });
    vi.spyOn(apiClient, "getCatalogOptions").mockResolvedValue([]);
    vi.spyOn(apiClient, "patchMachine").mockRejectedValue(
      new ApiError("validation", "Press capacity must be positive."),
    );
    renderEditor();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Edit machine" }),
    );
    await user.clear(screen.getByRole("textbox", { name: "Machine name" }));
    await user.type(
      screen.getByRole("textbox", { name: "Machine name" }),
      "Rejected name",
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Press capacity must be positive.",
    );
    expect(screen.getByRole("textbox", { name: "Machine name" })).toHaveValue(
      "Rejected name",
    );
  });
});
