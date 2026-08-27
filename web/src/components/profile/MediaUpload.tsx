import { useEffect, useState } from "react";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
} from "@/api/client";
import { ApiError } from "@/api/errors";

export function MediaUpload({
  entityType,
  identifier,
  onSaved,
}: {
  entityType: "eoat" | "machine" | "tool";
  identifier: string;
  onSaved: () => void;
}) {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [mediaKind, setMediaKind] = useState<"document" | "photo">("document");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
  const mayCreateDocument = sessionHasPermission(session, "document.create");
  const mayCreatePhoto = sessionHasPermission(session, "photo.create");
  const mayWrite = mayCreateDocument || mayCreatePhoto;
  const mayUploadCurrent =
    mediaKind === "document" ? mayCreateDocument : mayCreatePhoto;
  useEffect(() => {
    if (!mayCreateDocument && mayCreatePhoto) setMediaKind("photo");
  }, [mayCreateDocument, mayCreatePhoto]);
  async function upload() {
    if (!file || !title || !mayUploadCurrent) return;
    setBusy(true);
    setError("");
    try {
      await apiClient.uploadWebMedia({
        entityType,
        entityIdentifier: identifier,
        file,
        title,
        mediaKind,
        description: description || undefined,
      });
      setOpen(false);
      setFile(null);
      setTitle("");
      setDescription("");
      onSaved();
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "The media was not uploaded. The displayed media list is unchanged.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!mayWrite) return null;
  if (!open)
    return (
      <button
        className="profile-edit-button"
        type="button"
        onClick={() => setOpen(true)}
      >
        Add document / photo
      </button>
    );
  return (
    <section
      className="entity-editor"
      aria-label={`Add media to ${identifier}`}
    >
      <header>
        <h2>Add document or photo</h2>
        <p>
          The browser sends file content only. EOAT Atlas chooses a controlled
          server location and never returns its filesystem path.
        </p>
      </header>
      <div className="entity-editor-grid">
        <label>
          <span>Media type</span>
          <select
            value={mediaKind}
            onChange={(event) =>
              setMediaKind(event.target.value as "document" | "photo")
            }
          >
            {mayCreateDocument && <option value="document">Document</option>}
            {mayCreatePhoto && <option value="photo">Photo</option>}
          </select>
        </label>
        <label>
          <span>Title</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
          />
        </label>
        <label className="wide">
          <span>File</span>
          <input
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </label>
        <label className="wide">
          <span>Description</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
      </div>
      {error && (
        <p className="entity-editor-error" role="alert">
          {error}
        </p>
      )}
      <footer>
        <button type="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void upload()}
          disabled={busy || !file || !title || !mayUploadCurrent}
        >
          {busy ? "Uploading…" : "Upload media"}
        </button>
      </footer>
    </section>
  );
}
