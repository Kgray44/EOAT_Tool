import type { PropsWithChildren } from "react";
import { Navigation } from "@/components/navigation/Navigation";

export function AppShell({ children }: PropsWithChildren) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div>
          <p className="eyebrow">Nolato EOAT systems</p>
          <h1>EOAT Atlas</h1>
        </div>
        <Navigation />
      </header>
      <main id="main-content" className="site-main">
        {children}
      </main>
      <footer className="site-footer">
        Read-only web foundation · Data is authoritative only when confirmed by
        EOAT Atlas API.
      </footer>
    </div>
  );
}
