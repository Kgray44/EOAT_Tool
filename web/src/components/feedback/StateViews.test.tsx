import { render, screen } from "@testing-library/react";
import { ApiError } from "@/api/errors";
import {
  ErrorState,
  LoadingState,
  StatusValue,
} from "@/components/feedback/StateViews";

describe("foundation states", () => {
  it("has an accessible loading status", () => {
    render(<LoadingState />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });
  it("labels unavailable API responses honestly", () => {
    render(<ErrorState error={new ApiError("unavailable", "API offline")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("API unavailable");
  });
  it("does not invent missing data", () => {
    render(<StatusValue value={null} />);
    expect(screen.getByText("Unknown / unavailable")).toBeInTheDocument();
  });
});
