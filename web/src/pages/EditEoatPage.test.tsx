import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { apiClient } from "@/api/client";
import { EditEoatPage } from "./EditEoatPage";

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/eoats/P4-EOAT-0101/edit"]}>
        <Routes>
          <Route path="/eoats/:identifier/edit" element={<EditEoatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EditEoatPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not expose the dedicated editor while onboarding is disabled", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({ enabled: false });
    const profile = vi.spyOn(apiClient, "getEoatProfile");

    renderPage();

    expect(
      await screen.findByText("EOAT onboarding and the dedicated editor are not enabled in this environment."),
    ).toBeInTheDocument();
    expect(profile).not.toHaveBeenCalled();
  });
});
