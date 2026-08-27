import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
} from "@/api/client";

const editPermissions = [
  "eoat.edit",
  "machine.edit",
  "tool.edit",
  "relationship.edit",
  "document.edit",
  "photo.edit",
  "assignment.edit",
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
  const [actionOpen, setActionOpen] = useState(false);
  const [panelPosition, setPanelPosition] = useState<CSSProperties>();
  const toggle = useRef<HTMLButtonElement>(null);

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
      if (event.key === "Escape") {
        setOpen(false);
        setActionOpen(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const mayEdit = editPermissions.some((permission) =>
    sessionHasPermission(session, permission),
  );
  if (!mayEdit) return null;

  const closeMenu = () => {
    setOpen(false);
    setActionOpen(false);
  };

  const panel = open ? (
    <section
      className="profile-edit-menu__panel"
      data-expanded={actionOpen || undefined}
      style={actionOpen ? undefined : panelPosition}
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
          onClick={closeMenu}
        >
          ×
        </button>
      </header>
      <div
        className="profile-edit-menu__content"
        onClickCapture={(event) => {
          if (
            event.target instanceof Element &&
            event.target.closest(".profile-edit-button")
          )
            setActionOpen(true);
        }}
      >
        {children}
      </div>
    </section>
  ) : null;

  return (
    <div className="profile-edit-menu">
      <button
        ref={toggle}
        className="profile-edit-menu__toggle"
        type="button"
        aria-label={
          open
            ? `Close edit actions for ${identifier}`
            : `Open edit actions for ${identifier}`
        }
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          if (open) {
            closeMenu();
            return;
          }
          const bounds = toggle.current?.getBoundingClientRect();
          setPanelPosition(
            bounds
              ? {
                  top: `${bounds.bottom + 10}px`,
                  right: `${Math.max(18, window.innerWidth - bounds.right)}px`,
                }
              : undefined,
          );
          setActionOpen(false);
          setOpen(true);
        }}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M4 16.5V20h3.5L18.3 9.2l-3.5-3.5L4 16.5Z" />
          <path d="m13.8 6.7 3.5 3.5" />
        </svg>
      </button>
      {panel ? createPortal(panel, document.body) : null}
    </div>
  );
}
