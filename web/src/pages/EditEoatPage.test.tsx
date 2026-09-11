import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { apiClient } from "@/api/client";
import { EditEoatPage, ProfilePhotoSelector } from "./EditEoatPage";

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

  it("selects an existing photo through the governed profile-photo endpoint", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["photo.edit"],
    });
    vi.spyOn(apiClient, "getEoatPhotos").mockResolvedValue([
      {
        document_uuid: "front-photo",
        title: "Front",
        file_name: "front.jpg",
        content_delivery_state: "AVAILABLE",
        is_profile_photo: true,
      },
      {
        document_uuid: "side-photo",
        title: "Side",
        file_name: "side.jpg",
        content_delivery_state: "AVAILABLE",
        is_profile_photo: false,
      },
    ]);
    const select = vi.spyOn(apiClient, "selectOnboardingProfilePhoto").mockResolvedValue({ row_version: 2 });

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProfilePhotoSelector identifier="P4-EOAT-0101" onSaved={vi.fn()} />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: /Side.*Set as profile photo/ }));
    expect(select).toHaveBeenCalledWith("P4-EOAT-0101", "side-photo");
    expect(await screen.findByText("Profile photo updated.")).toBeInTheDocument();
  });
});
