import { useEffect, useState, type ReactNode } from "react";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
} from "@/api/client";

const editPermissions = [
  "asset.write",
  "compatibility.write",
  "document.write",
  "installation.write",
];

export function ProfileActionMenu({
  identifier,
  children,
}: {
  identifier: string;
  children: ReactNode;
}) {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const refresh = () =>
      void apiClient
        .getAuthenticatedSession()
        .then(setSession)
        .catch(() => setSession(null));
    refresh();
    window.addEventListener("atlas-authentication-changed", refresh);
    return () =>
      window.removeEventListener("atlas-authentication-changed", refresh);
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const mayEdit = editPermissions.some((permission) =>
    sessionHasPermission(session, permission),
  );
  if (!mayEdit) return null;

  return (
    <div className="profile-edit-menu">
      <button
        className="profile-edit-menu__toggle"
        type="button"
        aria-label={
          open
            ? `Close edit actions for ${identifier}`
            : `Open edit actions for ${identifier}`
        }
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((current) => !current)}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M4 16.5V20h3.5L18.3 9.2l-3.5-3.5L4 16.5Z" />
          <path d="m13.8 6.7 3.5 3.5" />
        </svg>
      </button>
      {open && (
        <section
          className="profile-edit-menu__panel"
          role="dialog"
          aria-label={`Edit actions for ${identifier}`}
        >
          <header>
            <div>
              <p className="eyebrow">Authenticated editing</p>
              <h2>Profile actions</h2>
            </div>
            <button
              className="profile-edit-menu__close"
              type="button"
              aria-label="Close edit actions"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </header>
          <div className="profile-edit-menu__content">{children}</div>
        </section>
      )}
    </div>
  );
}
