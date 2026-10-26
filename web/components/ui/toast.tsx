"use client";

import { CheckCircleIcon, InformationCircleIcon, XCircleIcon, XMarkIcon } from "@heroicons/react/20/solid";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

interface Toast {
  id: number;
  message: ReactNode;
  tone: "info" | "error" | "success";
  undo?: () => void;
  sticky: boolean;
}

interface ToastApi {
  show: (message: ReactNode, opts?: { tone?: Toast["tone"]; undo?: () => void; sticky?: boolean }) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const UNDO_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const show = useCallback<ToastApi["show"]>(
    (message, opts = {}) => {
      const id = ++seq.current;
      const tone = opts.tone ?? "info";
      // Error toasts are sticky until dismissed (UI_UX_SPEC §9).
      const sticky = opts.sticky ?? tone === "error";
      setToasts((t) => [...t.slice(-3), { id, message, tone, undo: opts.undo, sticky }]);
      if (!sticky) setTimeout(() => dismiss(id), opts.undo ? UNDO_MS : 4000);
    },
    [dismiss],
  );
  const value = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(400px,calc(100vw-32px))] flex-col gap-2 max-sm:left-1/2 max-sm:right-auto max-sm:-translate-x-1/2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={cn(
              "pop-in pointer-events-auto flex items-center justify-between gap-3 rounded-panel border border-line-strong bg-surface py-2 pl-3.5 pr-2 shadow-pop",
              t.tone === "error" && "border-crit/50",
            )}
          >
            <div className="flex min-w-0 items-start gap-2.5">
              {t.tone === "success" ? <CheckCircleIcon className="mt-px size-4 shrink-0 text-ok" aria-hidden="true" />
                : t.tone === "error" ? <XCircleIcon className="mt-px size-4 shrink-0 text-crit" aria-hidden="true" />
                  : <InformationCircleIcon className="mt-px size-4 shrink-0 text-ink-2" aria-hidden="true" />}
              <div className="min-w-0 text-[13px]">{t.message}</div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {t.undo ? (
                <button
                  type="button"
                  className="chrome hit h-7 rounded-control px-2.5 text-[13px] font-medium text-accent hover:bg-accent/10"
                  onClick={() => {
                    t.undo?.();
                    dismiss(t.id);
                  }}
                >
                  Undo
                </button>
              ) : null}
              <button type="button" aria-label="Dismiss" className="chrome hit grid size-7 place-items-center rounded-control text-ink-2 hover:bg-surface-2 hover:text-ink" onClick={() => dismiss(t.id)}>
                <XMarkIcon className="size-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
