"use client";

import { ExclamationTriangleIcon } from "@heroicons/react/20/solid";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "./button";
import { Dialog } from "./dialog";
import { Field, Input } from "./field";

export interface ConfirmOptions {
  title: ReactNode;
  body?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Destructive actions get a red confirm button and a warning icon. */
  destructive?: boolean;
  /** Require typing this exact text (e.g. a project name) before the confirm button enables. */
  typeToConfirm?: string;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

/** One shared confirmation dialog; `await confirm({...})` resolves true only on explicit confirmation. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState("");
  const resolver = useRef<((ok: boolean) => void) | null>(null);
  const confirm = useCallback<Confirm>((options) => {
    resolver.current?.(false);
    setTyped("");
    setOpts(options);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);
  const close = (ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setOpts(null);
  };
  const value = useMemo(() => confirm, [confirm]);
  const blocked = !!opts?.typeToConfirm && typed !== opts.typeToConfirm;
  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Dialog
        open={!!opts}
        onClose={() => close(false)}
        title={
          <span className="flex items-center gap-2.5">
            {opts?.destructive ? (
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-crit/[var(--tint)] text-crit">
                <ExclamationTriangleIcon className="size-4" aria-hidden="true" />
              </span>
            ) : null}
            {opts?.title}
          </span>
        }
        footer={
          <>
            <Button variant="secondary" data-dialog-cancel onClick={() => close(false)}>{opts?.cancelLabel ?? "Cancel"}</Button>
            <Button variant={opts?.destructive ? "destructive" : "primary"} disabled={blocked} onClick={() => close(true)}>
              {opts?.confirmLabel}
            </Button>
          </>
        }
      >
        {opts?.body ? <div className="flex flex-col gap-2 text-[13.5px] text-ink-2 [&_strong]:text-ink">{opts.body}</div> : null}
        {opts?.typeToConfirm ? (
          <div className="mt-4">
            <Field label={<>Type <span className="mono font-semibold text-ink">{opts.typeToConfirm}</span> to confirm</>} htmlFor="confirm-text">
              <Input id="confirm-text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
            </Field>
          </div>
        ) : null}
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): Confirm {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used inside ConfirmProvider");
  return ctx;
}
