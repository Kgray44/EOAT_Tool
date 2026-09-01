import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import * as qrApi from "@/api/qr";
import { QrLabel } from "./QrLabel";

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,QR") },
}));

describe("QrLabel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens the server-generated print-ready PDF instead of printing HTML", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    vi.spyOn(qrApi, "isUnsafeQrOrigin").mockReturnValue(false);

    render(<QrLabel category="eoat" identifier="CL-EOAT-0047" />);
    const button = await screen.findByRole("button", { name: "Print label" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    expect(open).toHaveBeenCalledWith(
      "/api/v1/eoats/CL-EOAT-0047/qr-label.pdf",
      "_blank",
      "noopener,noreferrer",
    );
  });
});
