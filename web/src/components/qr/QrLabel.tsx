import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { canonicalQrPayload, isUnsafeQrOrigin } from "@/api/qr";
import { entityPath, type EntityCategory } from "@/api/routes";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";

function qrLabelPdfPath(identifier: string): string | undefined {
  const path = entityPath("eoat", identifier);
  return path ? `/api/v1${path}/qr-label.pdf` : undefined;
}

export function QrLabel({
  category,
  identifier,
}: {
  category: EntityCategory;
  identifier: string;
}) {
  const origin = window.location.origin;
  const routable = isRoutableAuthoritativeIdentifier(identifier);
  const labelPdfPath = qrLabelPdfPath(identifier);
  const payload = routable
    ? canonicalQrPayload(category, identifier, origin)
    : undefined;
  const unsafe = isUnsafeQrOrigin(origin);
  const [image, setImage] = useState<string>();

  useEffect(() => {
    if (!payload) return;
    QRCode.toDataURL(payload, {
      errorCorrectionLevel: "M",
      margin: 3,
      width: 320,
    })
      .then(setImage)
      .catch(() => setImage(undefined));
  }, [payload]);

  return (
    <section className="qr-label" aria-labelledby="qr-label-title">
      <h2 id="qr-label-title">QR label</h2>
      <div className="qr-label__body">
        <div className="qr-label__content">
          <div className="qr-label__identity">
            <strong>EOAT Atlas</strong>
            <span>{presentationText(identifier)}</span>
            <small>
              Scan for profile, compatibility, documents &amp; history
            </small>
          </div>
          <div className="qr-label__actions">
            <small>{category}</small>
            {unsafe && (
              <p className="qr-warning" role="alert">
                This origin is not suitable for a durable production label.
                Printing is disabled.
              </p>
            )}
            <button
              type="button"
              onClick={() => labelPdfPath && window.open(labelPdfPath, "_blank", "noopener,noreferrer")}
              disabled={unsafe || !image || !payload || !labelPdfPath}
            >
              Print label
            </button>
          </div>
        </div>
        {image && payload ? (
          <img
            className="qr-label__code"
            src={image}
            alt={`QR code for ${payload}`}
          />
        ) : (
          <p role="status">Generating QR code…</p>
        )}
      </div>
    </section>
  );
}
