import { Navigate, useLocation } from "react-router-dom";

export function SearchPage() {
  const location = useLocation();
  return <Navigate replace to={`/library${location.search}`} />;
}
