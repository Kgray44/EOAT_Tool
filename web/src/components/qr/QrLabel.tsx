import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { canonicalQrPayload, isUnsafeQrOrigin } from "@/api/qr";
import type { EntityCategory } from "@/api/routes";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    };
    return entities[character];
  });
}

function printLabel(identifier: string, image: string): void {
  // Printing the application document leaves hidden profile content in the
  // pagination flow. Use a new, label-only document with physical dimensions.
  const printWindow = window.open(
    "",
    "eoat-atlas-print-label",
    "popup,width=460,height=360",
  );
  if (!printWindow) return;

  const labelIdentifier = escapeHtml(identifier);
  const qrImage = escapeHtml(image);
  printWindow.document.open();
  printWindow.document.write(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>EOAT Atlas label — ${labelIdentifier}</title>
    <style>
      @page { size: 4in 3in; margin: 0; }
      * { box-sizing: border-box; }
      html, body { width: 4in; height: 3in; margin: 0; background: #fff; }
      body { color: #0d2038; font-family: Arial, Helvetica, sans-serif; }
      .print-label { display: grid; grid-template-columns: 1fr 2.35in; gap: 0.16in; width: 4in; height: 3in; padding: 0.25in; align-items: center; }
      .print-label__identity { display: grid; gap: 0.08in; min-width: 0; }
      .print-label__product { font-size: 13pt; font-weight: 700; letter-spacing: 0.01em; }
      .print-label__identifier { font-size: 18pt; font-weight: 800; overflow-wrap: anywhere; }
      .print-label__description { font-size: 9pt; line-height: 1.3; }
      .print-label__qr { display: block; width: 2.35in; height: 2.35in; padding: 0.05in; background: #fff; }
    </style>
  </head>
  <body>
    <main class="print-label" aria-label="EOAT Atlas QR label">
      <div class="print-label__identity">
        <div class="print-label__product">EOAT Atlas</div>
        <div class="print-label__identifier">${labelIdentifier}</div>
        <div class="print-label__description">Scan for the EOAT profile, compatibility, documents, and history.</div>
      </div>
      <img class="print-label__qr" src="${qrImage}" alt="QR code for EOAT ${labelIdentifier}" />
    </main>
  </body>
</html>`);
  printWindow.document.close();

  const qr =
    printWindow.document.querySelector<HTMLImageElement>(".print-label__qr");
  const beginPrint = () => {
    printWindow.focus();
    printWindow.print();
  };
  if (qr && !qr.complete) {
    qr.addEventListener("load", beginPrint, { once: true });
    qr.addEventListener("error", beginPrint, { once: true });
  } else {
    beginPrint();
  }
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
              onClick={() => image && printLabel(identifier, image)}
              disabled={unsafe || !image || !payload}
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
