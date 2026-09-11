import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "@/api/client";
import { OnboardingDraftsPage } from "./OnboardingDraftsPage";

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <OnboardingDraftsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OnboardingDraftsPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lets a finalizer resume a prepared draft without exposing create or discard controls", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.finalize"],
    });
    vi.spyOn(apiClient, "listOnboardingDrafts").mockResolvedValue([
      {
        draft_uuid: "draft-1",
        proposed_identifier: "P4-EOAT-0102",
        plant_code: "P4",
        area_code: "Assembly",
        created_by_display_name: "Draft Preparer",
        lifecycle_state: "DRAFT",
        completion_state: "READY_FOR_REVIEW",
        payload: {},
        row_version: 3,
        updated_at: "2026-09-04T00:00:00Z",
        staged_media: [],
      },
    ]);

    renderPage();

    expect(await screen.findByText("P4-EOAT-0102")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add New EOAT" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
  });
});
