import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import * as qrApi from "@/api/qr";
import { QrLabel } from "./QrLabel";

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,QR") },
}));

describe("QrLabel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("prints an isolated physical label surface", async () => {
    const printDocument = document.implementation.createHTMLDocument("label");
    const printWindow = {
      document: printDocument,
      focus: vi.fn(),
      print: vi.fn(),
    };
    vi.spyOn(qrApi, "isUnsafeQrOrigin").mockReturnValue(false);
    vi.spyOn(window, "open").mockReturnValue(printWindow as unknown as Window);

    render(<QrLabel category="eoat" identifier="CL-EOAT-0047" />);
    const button = await screen.findByRole("button", { name: "Print label" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    const label = printDocument.querySelector(".print-label");
    const qr =
      printDocument.querySelector<HTMLImageElement>(".print-label__qr");
    expect(label).not.toBeNull();
    expect(label?.textContent).toContain("EOAT Atlas");
    expect(label?.textContent).toContain("CL-EOAT-0047");
    expect(qr?.src).toContain("data:image/png;base64,QR");
    expect(printDocument.querySelectorAll("button")).toHaveLength(0);
    expect(printDocument.querySelector("style")?.textContent).toContain(
      "@page { size: 4in 3in; margin: 0; }",
    );

    qr?.dispatchEvent(new Event("load"));
    expect(printWindow.print).toHaveBeenCalledOnce();
  });
});
