import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { apiClient } from "@/api/client";
import { EoatManagementPage } from "./EoatManagementPage";

function renderPage() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <EoatManagementPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EoatManagementPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("exposes governed creation and drafts to a granular Technician-level grant", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create", "onboarding.draft.edit"],
    });

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "EOAT Management" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add New EOAT/ })).toHaveAttribute(
      "href",
      "/eoats/new",
    );
    expect(
      screen.getByRole("link", { name: /Onboarding Drafts/ }),
    ).toHaveAttribute("href", "/eoats/onboarding-drafts");
  });

  it("does not expose management actions without an onboarding grant", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: [],
    });

    renderPage();

    expect(
      await screen.findByText(
        "You do not have permission to manage EOAT onboarding work.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Add New EOAT/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Onboarding Drafts/ }),
    ).not.toBeInTheDocument();
  });
});
