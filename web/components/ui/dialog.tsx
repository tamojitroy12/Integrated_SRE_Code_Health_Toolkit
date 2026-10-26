"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/** Native modal dialog: Esc closes the topmost layer, focus is trapped. */
export function Dialog({ open, onClose, title, children, footer, className, initialFocus = "cancel" }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  initialFocus?: "cancel" | "first";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      const target =
        initialFocus === "cancel"
          ? el.querySelector<HTMLElement>("[data-dialog-cancel]")
          : el.querySelector<HTMLElement>("input, select, textarea, button");
      target?.focus();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open, initialFocus]);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onKeyDown={(e) => {
        // Enter never auto-confirms a destructive dialog.
        if (e.key === "Enter" && (e.target as HTMLElement).tagName === "BUTTON") e.stopPropagation();
      }}
      className={cn(
        "pop-in m-auto w-[min(520px,calc(100vw-32px))] rounded-panel border border-line-strong bg-surface p-0 text-ink shadow-pop " +
          "backdrop:bg-black/50",
        className,
      )}
    >
      {open ? (
        <div className="p-5 max-md:p-4">
          <h2 className="text-[16px] font-semibold">{title}</h2>
          <div className="mt-3">{children}</div>
          {footer ? <div className="-mx-5 -mb-5 mt-5 flex flex-wrap justify-end gap-2 border-t border-line bg-surface-2/50 px-5 py-3 max-md:-mx-4 max-md:-mb-4 max-sm:flex-col-reverse">{footer}</div> : null}
        </div>
      ) : null}
    </dialog>
  );
}
