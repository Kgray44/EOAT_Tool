import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { canonicalQrPayload, isUnsafeQrOrigin } from "@/api/qr";
import type { EntityCategory } from "@/api/routes";

export function QrLabel({
  category,
  identifier,
}: {
  category: EntityCategory;
  identifier: string;
}) {
  const origin = window.location.origin;
  const payload = canonicalQrPayload(category, identifier, origin);
  const unsafe = isUnsafeQrOrigin(origin);
  const [image, setImage] = useState<string>();

  useEffect(() => {
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
        {image ? (
          <img src={image} alt={`QR code for ${payload}`} />
        ) : (
          <p role="status">Generating QR code…</p>
        )}
        <div>
          <strong>EOAT Atlas · {category}</strong>
          <span>{identifier}</span>
          <code>{payload}</code>
          {unsafe && (
            <p className="qr-warning" role="alert">
              This origin is not suitable for a durable production label.
              Printing is disabled.
            </p>
          )}
          <button
            type="button"
            onClick={() => window.print()}
            disabled={unsafe || !image}
          >
            Print label
          </button>
        </div>
      </div>
    </section>
  );
}
