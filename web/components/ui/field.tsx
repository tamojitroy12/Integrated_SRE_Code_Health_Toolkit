"use client";

import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const control =
  "w-full h-8 rounded-control border border-line-strong bg-surface px-2.5 text-[13.5px] text-ink shadow-card placeholder:text-ink-3 " +
  "transition-[border-color,box-shadow] duration-150 hover:border-ink-3/60 " +
  "focus:border-accent focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_22%,transparent)] disabled:opacity-60";

export function Field({ label, hint, error, children, htmlFor, optional }: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor: string;
  optional?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-medium">
        {label} {optional ? <span className="font-normal text-ink-2">(optional)</span> : null}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-caption font-medium text-crit">{error}</p>
      ) : hint ? (
        <p className="text-caption text-ink-2">{hint}</p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(control, className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cn(control, "h-auto min-h-24 py-2", className)} {...rest} />;
});

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(control, "pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

/** Whole line is clickable: the label wraps the checkbox (Fitts's law, UI_UX_SPEC §4). */
export function Checkbox({ label, checked, onChange, disabled, description }: {
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  description?: ReactNode;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className={cn("chrome hit flex min-h-9 cursor-pointer items-start gap-3 py-1",
      disabled && "cursor-not-allowed opacity-60")}>
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="text-[13.5px] font-medium">{label}</span>
        {description ? <span className="block text-caption text-ink-2">{description}</span> : null}
      </span>
    </label>
  );
}
