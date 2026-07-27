import { Link } from "react-router-dom";

type BoundaryKind = "standards" | "data-health" | "setup-packet";

const content: Record<
  BoundaryKind,
  { title: string; subtitle: string; body: string }
> = {
  standards: {
    title: "Standards & WI",
    subtitle: "Standards and work instructions will be added later.",
    body: "The desktop authority currently exposes this as a coming-later surface. No browser document source is available, so EOAT Atlas does not simulate a library or link to unverified files.",
  },
  "data-health": {
    title: "Data Health",
    subtitle: "Data validation tools will be added later.",
    body: "The browser continues to show the API freshness status where it is used. There is no browser-safe equivalent for desktop validation controls until the service exposes an authenticated read-only report.",
  },
  "setup-packet": {
    title: "Setup Packet",
    subtitle: "Setup packets begin with a valid Fit Check.",
    body: "Generating a packet is a desktop-local file workflow. The browser exposes the same non-persisting compatibility evaluation, but does not simulate a local PDF export or write a packet.",
  },
};

export function DesktopBoundaryPage({ kind }: { kind: BoundaryKind }) {
  const page = content[kind];
  return (
    <section className="simple-page" aria-labelledby="simple-page-title">
      <header className="simple-page-heading">
        <h1 id="simple-page-title">{page.title}</h1>
        <span aria-hidden="true" />
        <p>{page.subtitle}</p>
      </header>
      <section className="simple-page-card">
        <h2>
          {kind === "setup-packet"
            ? "Read-only browser boundary"
            : "Coming later"}
        </h2>
        <p>{page.body}</p>
        {kind === "setup-packet" && (
          <Link className="simple-page-action" to="/fit-check">
            Run a read-only Fit Check
          </Link>
        )}
      </section>
    </section>
  );
}
