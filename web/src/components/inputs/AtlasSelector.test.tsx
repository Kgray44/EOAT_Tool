import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AtlasSelector } from "./AtlasSelector";

function Harness() {
  const [value, setValue] = useState("");
  return (
    <AtlasSelector
      label="Machine"
      value={value}
      options={[{ value: "DEMO-P4::040", label: "Machine 040" }]}
      onChange={setValue}
    />
  );
}

describe("AtlasSelector", () => {
  it("keeps a selected option visible immediately after a pointer selection", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const input = screen.getByRole("combobox", { name: "Machine" });
    await user.click(input);
    await user.click(screen.getByRole("option", { name: "Machine 040" }));

    expect(input).toHaveValue("Machine 040");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
