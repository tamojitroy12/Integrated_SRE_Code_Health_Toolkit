import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ConfirmProvider, useConfirm, type ConfirmOptions } from "@/components/ui/confirm";
import { cn } from "@/lib/cn";

function Harness({ options }: { options: ConfirmOptions }) {
  const confirm = useConfirm();
  const [result, setResult] = useState("none");
  return (
    <>
      <button type="button" onClick={async () => setResult(String(await confirm(options)))}>Open</button>
      <output>{result}</output>
    </>
  );
}

describe("confirmation dialog", () => {
  it("resolves false on cancel and true only on explicit confirmation", async () => {
    render(<ConfirmProvider><Harness options={{ title: "Delete rule?", confirmLabel: "Delete rule", destructive: true }} /></ConfirmProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("false")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete rule" }));
    await waitFor(() => expect(screen.getByText("true")).toBeInTheDocument());
  });

  it("keeps the confirm button disabled until the exact text is typed", async () => {
    render(<ConfirmProvider><Harness options={{ title: "Archive?", confirmLabel: "Archive project", destructive: true, typeToConfirm: "checkout" }} /></ConfirmProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    const confirmButton = await screen.findByRole("button", { name: "Archive project" });
    expect(confirmButton).toBeDisabled();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Checkout" } });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(input, { target: { value: "checkout" } });
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);
    await waitFor(() => expect(screen.getByText("true")).toBeInTheDocument());
  });
});

describe("cn", () => {
  it("lets later classes override earlier ones without dropping custom size or colour tokens", () => {
    expect(cn("rounded-control", "rounded-none")).toBe("rounded-none");
    expect(cn("p-5 max-md:p-4", "p-0 max-md:p-0")).toBe("p-0 max-md:p-0");
    expect(cn("text-caption text-ink-2")).toBe("text-caption text-ink-2");
  });
});
