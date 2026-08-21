import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { apiClient, type WebPhoto } from "@/api/client";

type Props = {
  photo: WebPhoto | null;
  onClose: () => void;
};

/** A browser-safe full-resolution photo viewer for profile and gallery media. */
export function PhotoLightbox({ photo, onClose }: Props) {
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!photo) return;
    const previousOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);
    closeButton.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, photo]);

  if (!photo) return null;
  const label = photo.caption || photo.title || photo.file_name;
  return createPortal(
    <div
      className="photo-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`Photo viewer: ${label}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="photo-lightbox__frame">
        <button
          ref={closeButton}
          type="button"
          className="photo-lightbox__close"
          aria-label="Close photo viewer"
          onClick={onClose}
        >
          ×
        </button>
        <img src={apiClient.photoContentUrl(photo.document_uuid)} alt={label} />
      </div>
    </div>,
    document.body,
  );
}
