import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiClient, type WebPhoto } from "@/api/client";

type Props = {
  photo: WebPhoto | null;
  onClose: () => void;
};

/** A browser-safe full-resolution photo viewer for profile and gallery media. */
export function PhotoLightbox({ photo, onClose }: Props) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);

  const fit = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  useEffect(() => {
    if (!photo) return;
    const previousOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);
    closeButton.current?.focus();
    setScale(1);
    setOffset({ x: 0, y: 0 });
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
        if (event.target === event.currentTarget && !drag.current?.moved)
          onClose();
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
        <button type="button" className="photo-lightbox__fit" onClick={fit}>
          Fit image
        </button>
        <img
          src={apiClient.photoContentUrl(photo.document_uuid)}
          alt={label}
          draggable={false}
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          }}
          className={scale > 1 ? "is-zoomed" : ""}
          onWheel={(event) => {
            event.preventDefault();
            setScale((current) =>
              Math.min(
                4,
                Math.max(1, current + (event.deltaY < 0 ? 0.25 : -0.25)),
              ),
            );
          }}
          onClick={() => {
            if (!suppressClick.current) {
              if (scale === 1) setScale(2);
              else fit();
            }
            suppressClick.current = false;
          }}
          onPointerDown={(event) => {
            if (scale <= 1) return;
            drag.current = { x: event.clientX, y: event.clientY, moved: false };
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (!drag.current) return;
            const dx = event.clientX - drag.current.x;
            const dy = event.clientY - drag.current.y;
            if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
            drag.current.x = event.clientX;
            drag.current.y = event.clientY;
            setOffset((current) => ({
              x: Math.max(-500, Math.min(500, current.x + dx)),
              y: Math.max(-500, Math.min(500, current.y + dy)),
            }));
          }}
          onPointerUp={() => {
            suppressClick.current = Boolean(drag.current?.moved);
            drag.current = null;
          }}
        />
      </div>
    </div>,
    document.body,
  );
}
