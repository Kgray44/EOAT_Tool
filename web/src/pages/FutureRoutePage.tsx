import { Link, useLocation } from "react-router-dom";
import { EmptyState } from "@/components/feedback/StateViews";

export function FutureRoutePage({ title }: { title: string }) {
  const location = useLocation();
  return (
    <EmptyState title={`${title} is planned for a later phase`}>
      The route <code>{location.pathname}</code> is registered and safe to
      bookmark, but this Phase 0 foundation does not provide its operational
      workflow yet. <Link to="/">Return to status</Link>.
    </EmptyState>
  );
}
