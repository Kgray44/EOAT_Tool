import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "@/api/client";
import { EoatOnboardingPage } from "./EoatOnboardingPage";

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <EoatOnboardingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EoatOnboardingPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not expose an off-environment onboarding workflow", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({ enabled: false });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create"],
    });

    renderPage();

    expect(await screen.findByText("This feature is not enabled in the current environment.")).toBeInTheDocument();
  });

  it("presents canonical profile and QR actions after finalization", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({ enabled: true });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: [
        "onboarding.draft.create",
        "onboarding.draft.finalize",
        "onboarding.draft.discard",
      ],
    });
    vi.spyOn(apiClient, "createOnboardingDraft").mockResolvedValue({
      draft_uuid: "draft-1",
      proposed_identifier: "P4-EOAT-0101",
      plant_code: "P4",
      area_code: null,
      lifecycle_state: "DRAFT",
      completion_state: "READY_FOR_REVIEW",
      payload: {},
      row_version: 1,
      updated_at: "2026-09-04T00:00:00Z",
      staged_media: [],
    });
    vi.spyOn(apiClient, "reviewOnboardingDraft").mockResolvedValue({
      blocking_errors: [],
      warnings: [],
    });
    const finalize = vi.spyOn(apiClient, "finalizeOnboardingDraft").mockResolvedValue({
      eoat: { business_identifier: "P4-EOAT-0101" },
      warnings: [],
    });

    renderPage();
    await user.type(await screen.findByRole("textbox", { name: "Plant code *" }), "P4");
    await user.type(screen.getByRole("textbox", { name: "EOAT identifier *" }), "P4-EOAT-0101");
    await user.type(screen.getByRole("textbox", { name: "EOAT type *" }), "Vacuum");
    await user.click(screen.getByRole("button", { name: "Start draft" }));
    for (let step = 0; step < 5; step += 1) {
      await user.click(await screen.findByRole("button", { name: "Next" }));
    }
    await waitFor(() => expect(screen.getByText("No current blocking errors.")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Create EOAT" }));

    await waitFor(() => expect(finalize).toHaveBeenCalledWith("draft-1", 1));
    expect(await screen.findByRole("link", { name: "View profile" })).toHaveAttribute(
      "href",
      "/eoats/P4-EOAT-0101",
    );
    expect(screen.getByRole("link", { name: "Add another EOAT" })).toHaveAttribute("href", "/eoats/new");
  });

  it("hides inapplicable hardware detail without treating unknown as no", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({ enabled: true });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create"],
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /2\. Hardware/ }));
    expect(screen.getByRole("textbox", { name: "Vacuum cup type" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Cylinder count" })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Vacuum present" }), "false");
    await user.selectOptions(screen.getByRole("combobox", { name: "Cylinders present" }), "false");

    expect(screen.queryByRole("textbox", { name: "Vacuum cup type" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "Cylinder count" })).not.toBeInTheDocument();
  });
});
