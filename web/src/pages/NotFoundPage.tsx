import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="state">
      <h2>Page not found</h2>
      <p>
        This address is not part of EOAT Atlas.{" "}
        <Link to="/">Return to the status page</Link>.
      </p>
    </section>
  );
}
