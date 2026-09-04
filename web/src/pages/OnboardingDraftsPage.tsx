import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { apiClient, sessionHasPermission } from "@/api/client";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

export function OnboardingDraftsPage() {
  const navigate = useNavigate();
  const drafts = useQuery({
    queryKey: ["onboarding", "drafts"],
    queryFn: () => apiClient.listOnboardingDrafts(),
  });
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => apiClient.getAuthenticatedSession(),
  });
  const mayCreate = sessionHasPermission(session.data, "onboarding.draft.create");
  const mayDiscard = sessionHasPermission(session.data, "onboarding.draft.discard");
  if (drafts.isPending)
    return <LoadingState label="Loading onboarding drafts…" />;
  if (drafts.isError) return <ErrorState error={drafts.error} />;
  return (
    <section className="onboarding-page">
      <header>
        <p className="eyebrow">Governed workspace</p>
        <h1>Onboarding Drafts</h1>
        <p>
          Drafts are not Library assets and cannot be used by Fit Check or QR
          labels until finalization.
        </p>
      </header>
      {mayCreate && (
        <p>
          <Link className="profile-edit-button" to="/eoats/new">
            Add New EOAT
          </Link>
        </p>
      )}
      <section className="onboarding-card">
        <div className="onboarding-draft-list">
          {drafts.data?.length ? (
            drafts.data.map((draft) => (
              <article key={draft.draft_uuid}>
                <div>
                  <strong>
                    {draft.proposed_identifier || "Identifier not proposed"}
                  </strong>
                  <span>
                    {draft.completion_state} · Updated{" "}
                    {new Date(draft.updated_at).toLocaleString()}
                  </span>
                  <span>
                    {[draft.plant_code, draft.area_code].filter(Boolean).join(" · ") || "Plant / area not recorded"}
                    {draft.created_by_display_name ? ` · Prepared by ${draft.created_by_display_name}` : ""}
                  </span>
                </div>
                <div>
                  <button
                    type="button"
                    onClick={() => navigate(`/eoats/new/${draft.draft_uuid}`)}
                  >
                    Resume
                  </button>
                  {mayDiscard && (
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm("Discard this onboarding draft?"))
                          void apiClient
                            .discardOnboardingDraft(
                              draft.draft_uuid,
                              draft.row_version,
                            )
                            .then(() => void drafts.refetch());
                      }}
                    >
                      Discard
                    </button>
                  )}
                </div>
              </article>
            ))
          ) : (
            <p>No active onboarding drafts.</p>
          )}
        </div>
      </section>
    </section>
  );
}
