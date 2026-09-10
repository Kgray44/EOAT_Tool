import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { apiClient } from "@/api/client";
import { EoatOnboardingPage } from "./EoatOnboardingPage";

function renderPage(path = "/eoats/new") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/eoats/new" element={<EoatOnboardingPage />} />
          <Route
            path="/eoats/new/:draftUuid"
            element={<EoatOnboardingPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EoatOnboardingPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not expose an off-environment onboarding workflow", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: false,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create"],
    });

    renderPage();

    expect(
      await screen.findByText(
        "This feature is not enabled in the current environment.",
      ),
    ).toBeInTheDocument();
  });

  it("presents canonical profile and QR actions after finalization", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
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
    const finalize = vi
      .spyOn(apiClient, "finalizeOnboardingDraft")
      .mockResolvedValue({
        eoat: { business_identifier: "P4-EOAT-0101" },
        warnings: [],
      });

    renderPage();
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Plant code *" }),
      "P4",
    );
    await user.type(
      screen.getByRole("textbox", { name: "EOAT identifier *" }),
      "P4-EOAT-0101",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "EOAT type *" }),
      "vacuum",
    );
    await user.click(
      screen.getByRole("button", { name: "Start Draft & Continue →" }),
    );
    for (let step = 0; step < 4; step += 1) {
      await user.click(
        await screen.findByRole("button", { name: "Continue →" }),
      );
    }
    await waitFor(() =>
      expect(
        screen.getByText("No current blocking errors."),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Finalize EOAT" }));

    await waitFor(() => expect(finalize).toHaveBeenCalledWith("draft-1", 1));
    expect(
      await screen.findByRole("link", { name: "View profile" }),
    ).toHaveAttribute("href", "/eoats/P4-EOAT-0101");
    expect(
      screen.getByRole("link", { name: "Add another EOAT" }),
    ).toHaveAttribute("href", "/eoats/new");
  });

  it("hides inapplicable hardware detail without treating unknown as no", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create"],
    });

    renderPage();
    const rail = await screen.findByRole("navigation", {
      name: "Onboarding sections",
    });
    await user.click(
      within(rail).getByRole("button", { name: /Step 2: Hardware/ }),
    );
    expect(
      screen.getByRole("textbox", { name: "Vacuum cup type" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("spinbutton", { name: "Cylinder count" }),
    ).toBeInTheDocument();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Vacuum present" }),
      "false",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Cylinders present" }),
      "false",
    );

    expect(
      screen.queryByRole("textbox", { name: "Vacuum cup type" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("spinbutton", { name: "Cylinder count" }),
    ).not.toBeInTheDocument();
  });

  it("carries Command Center defaults and controlled choices into a new draft", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({ enabled: true });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create"],
    });
    const create = vi.spyOn(apiClient, "createOnboardingDraft").mockResolvedValue({
      draft_uuid: "draft-command-center",
      proposed_identifier: "",
      plant_code: "P4",
      area_code: null,
      lifecycle_state: "DRAFT",
      completion_state: "INCOMPLETE",
      payload: {},
      row_version: 1,
      updated_at: "2026-09-10T00:00:00Z",
      staged_media: [],
    });

    renderPage();
    expect(await screen.findByRole("combobox", { name: "Status" })).toHaveValue("In Progress");
    const rail = screen.getByRole("navigation", { name: "Onboarding sections" });
    await user.click(within(rail).getByRole("button", { name: /Step 5: Photos & Documents/ }));
    const moves = screen.getByRole("combobox", { name: "EOAT moves" });
    expect(within(moves).getByRole("option", { name: "Part" })).toBeInTheDocument();
    expect(within(moves).getByRole("option", { name: "Sprue" })).toBeInTheDocument();
    expect(within(moves).getByRole("option", { name: "Both" })).toBeInTheDocument();
    await user.selectOptions(moves, "Both");
    await user.click(within(rail).getByRole("button", { name: /Step 1: Identity/ }));
    await user.click(screen.getByRole("button", { name: "Start Draft & Continue →" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          payload: expect.objectContaining({
            command_center: expect.objectContaining({
              status: "In Progress",
              pneumatic_quick_disconnect_type: "PTC",
              external_vacuum_circuits: "N/A",
              eoat_moves: "Both",
            }),
          }),
        }),
      ),
    );
  });

  it("persists the selected plant before reserving the next identifier", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.edit"],
    });
    vi.spyOn(apiClient, "getOnboardingDraft").mockResolvedValue({
      draft_uuid: "draft-1",
      proposed_identifier: null,
      plant_code: "P4",
      area_code: null,
      lifecycle_state: "DRAFT",
      completion_state: "INCOMPLETE",
      payload: { identity: { business_identifier: "", eoat_type: "" } },
      row_version: 1,
      updated_at: "2026-09-10T00:00:00Z",
      staged_media: [],
    });
    const save = vi.spyOn(apiClient, "saveOnboardingDraft").mockResolvedValue({
      draft_uuid: "draft-1",
      proposed_identifier: "",
      plant_code: "P7",
      area_code: null,
      lifecycle_state: "DRAFT",
      completion_state: "INCOMPLETE",
      payload: { identity: { business_identifier: "", eoat_type: "" } },
      row_version: 2,
      updated_at: "2026-09-10T00:00:00Z",
      staged_media: [],
    });
    const generate = vi
      .spyOn(apiClient, "generateOnboardingIdentifier")
      .mockResolvedValue({
        draft_uuid: "draft-1",
        proposed_identifier: "P7-EOAT-0001",
        plant_code: "P7",
        area_code: null,
        lifecycle_state: "DRAFT",
        completion_state: "INCOMPLETE",
        payload: { identity: { business_identifier: "", eoat_type: "" } },
        row_version: 3,
        updated_at: "2026-09-10T00:00:00Z",
        staged_media: [],
      });

    renderPage("/eoats/new/draft-1");

    const plant = await screen.findByRole("combobox", {
      name: "Plant code *",
    });
    expect(within(plant).getByRole("option", { name: "Plant 4" })).toHaveValue(
      "P4",
    );
    expect(within(plant).getByRole("option", { name: "Plant 7" })).toHaveValue(
      "P7",
    );
    expect(
      within(plant).getByRole("option", { name: "Cleanroom" }),
    ).toHaveValue("CL");
    await user.selectOptions(plant, "P7");
    await user.click(
      screen.getByRole("button", { name: "Generate next identifier" }),
    );

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        "draft-1",
        expect.objectContaining({ plant_code: "P7", expected_row_version: 1 }),
      ),
    );
    await waitFor(() => expect(generate).toHaveBeenCalledWith("draft-1", 2));
    expect(
      screen.getByRole("textbox", { name: "EOAT identifier *" }),
    ).toHaveValue("P7-EOAT-0001");
  });

  it("lets an authorized finalizer review a prepared draft without exposing draft mutation", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.finalize"],
    });
    vi.spyOn(apiClient, "getOnboardingDraft").mockResolvedValue({
      draft_uuid: "draft-1",
      proposed_identifier: "P4-EOAT-0101",
      plant_code: "P4",
      area_code: null,
      lifecycle_state: "DRAFT",
      completion_state: "READY_FOR_REVIEW",
      payload: {
        identity: { business_identifier: "P4-EOAT-0101", eoat_type: "vacuum" },
      },
      row_version: 1,
      updated_at: "2026-09-04T00:00:00Z",
      staged_media: [],
    });

    renderPage("/eoats/new/draft-1");

    expect(
      await screen.findByText(/You can review this draft/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "EOAT identifier *" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save Draft" })).toBeDisabled();
  });

  it("uses a semantic vertical step rail and a compact mobile step control", async () => {
    vi.spyOn(apiClient, "getOnboardingStatus").mockResolvedValue({
      enabled: true,
    });
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      permissions: ["onboarding.draft.create"],
    });

    renderPage();

    const rail = await screen.findByRole("navigation", {
      name: "Onboarding sections",
    });
    expect(rail).toBeInTheDocument();
    expect(
      within(rail).getByRole("button", {
        name: /Step 1: Identity\. Needs attention/,
      }),
    ).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Step 1 of 6")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Start Draft & Continue →" }),
    ).toBeInTheDocument();
  });
});
