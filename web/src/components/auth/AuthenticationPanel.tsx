import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "@/api/errors";
import { apiClient, type AuthenticatedSession } from "@/api/client";

export function AuthenticationPanel() {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void apiClient
      .getAuthenticatedSession()
      .then(setSession)
      .catch(() => setSession(null));
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setSession(await apiClient.kerberosFormLogin(username, password));
      setPassword("");
      setOpen(false);
      window.dispatchEvent(new Event("atlas-authentication-changed"));
    } catch (reason) {
      setPassword("");
      setError(
        reason instanceof ApiError
          ? "Sign-in failed. Check your credentials and try again."
          : "Sign-in is unavailable. Please try again shortly.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    try {
      await apiClient.logout();
    } finally {
      setSession(null);
      setBusy(false);
      window.dispatchEvent(new Event("atlas-authentication-changed"));
    }
  }

  const identity = session?.identity;
  if (identity) {
    return (
      <div className="atlas-auth-panel">
        <span className="atlas-auth-user">
          {identity.display_name || identity.username || "Authenticated user"}
        </span>
        <button
          type="button"
          className="atlas-auth-button"
          onClick={signOut}
          disabled={busy}
        >
          Sign out
        </button>
      </div>
    );
  }
  return (
    <div className="atlas-auth-panel">
      <button
        type="button"
        className="atlas-auth-button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        Sign in
      </button>
      {open && (
        <form
          className="atlas-auth-form"
          onSubmit={signIn}
          aria-label="EOAT Atlas sign in"
        >
          <header>
            <h2>Sign in to EOAT Atlas</h2>
            <p>
              Use your GW Plastics work account to unlock authorized editing.
            </p>
          </header>
          <label>
            <span>Username</span>
            <input
              name="username"
              placeholder="kgray or GWP\\kgray"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              maxLength={128}
            />
          </label>
          <label>
            <span>Password</span>
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && (
            <p className="atlas-auth-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="atlas-auth-button" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <p className="atlas-auth-note">
            Your password is used only for this Kerberos sign-in and is not
            stored by EOAT Atlas.
          </p>
        </form>
      )}
    </div>
  );
}
