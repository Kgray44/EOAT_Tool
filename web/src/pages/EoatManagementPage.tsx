import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiClient, sessionHasPermission } from "@/api/client";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

const draftPermissions = [
  "onboarding.draft.view",
  "onboarding.draft.edit",
  "onboarding.draft.review",
  "onboarding.draft.finalize",
];

export function EoatManagementPage() {
  const status = useQuery({
    queryKey: ["onboarding", "status"],
    queryFn: () => apiClient.getOnboardingStatus(),
  });
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => apiClient.getAuthenticatedSession(),
    retry: false,
  });

  if (status.isPending || session.isPending)
    return <LoadingState label="Loading EOAT management…" />;
  if (status.isError) return <ErrorState error={status.error} />;
  const mayCreate = sessionHasPermission(
    session.data,
    "onboarding.draft.create",
  );
  const mayAccessDrafts = draftPermissions.some((permission) =>
    sessionHasPermission(session.data, permission),
  );

  if (!status.data?.enabled)
    return (
      <section className="eoat-management-page">
        <p className="eyebrow">EOAT management</p>
        <h1>EOAT Management</h1>
        <p>Onboarding is not enabled in this environment.</p>
      </section>
    );

  if (!mayCreate && !mayAccessDrafts)
    return (
      <section className="eoat-management-page">
        <p className="eyebrow">EOAT management</p>
        <h1>EOAT Management</h1>
        <p>You do not have permission to manage EOAT onboarding work.</p>
      </section>
    );

  return (
    <section
      className="eoat-management-page"
      aria-labelledby="eoat-management-title"
    >
      <header>
        <p className="eyebrow">EOAT management</p>
        <h1 id="eoat-management-title">EOAT Management</h1>
        <p>Add new EOATs and review drafts.</p>
      </header>
      <div className="eoat-management-actions">
        {mayCreate ? (
          <Link className="eoat-management-card is-primary" to="/eoats/new">
            <span aria-hidden="true">＋</span>
            <strong>Add New EOAT</strong>
            <small>Start a new draft.</small>
          </Link>
        ) : null}
        {mayAccessDrafts ? (
          <Link className="eoat-management-card" to="/eoats/onboarding-drafts">
            <span aria-hidden="true">▤</span>
            <strong>Onboarding Drafts</strong>
            <small>Resume or review drafts.</small>
          </Link>
        ) : null}
      </div>
    </section>
  );
}
