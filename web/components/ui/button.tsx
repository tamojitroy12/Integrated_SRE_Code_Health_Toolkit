"use client";

import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export type Variant = "primary" | "secondary" | "destructive" | "ghost";
type Size = "md" | "sm";

const base =
  "chrome hit inline-flex items-center justify-center gap-1.5 rounded-control font-medium whitespace-nowrap select-none " +
  "transition-[background-color,border-color,color,box-shadow] duration-150 ease-out " +
  "disabled:opacity-50 disabled:cursor-not-allowed aria-disabled:opacity-50 aria-disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  // One primary action per screen.
  primary: "bg-primary text-on-primary shadow-card hover:bg-primary-hover",
  secondary: "border border-line-strong bg-surface text-ink shadow-card hover:bg-surface-2",
  destructive: "bg-danger text-on-crit shadow-card hover:brightness-110",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
};

const sizes: Record<Size, string> = {
  md: "h-8 px-3 text-[13px]",
  sm: "h-7 px-2.5 text-[12.5px]",
};

export function buttonClass(variant: Variant = "secondary", size: Size = "md", className?: string): string {
  return cn(base, variants[variant], sizes[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  /** Render as aria-disabled (keeps focus + tooltip) instead of the native disabled attribute. */
  softDisabled?: boolean;
}

export function Button({ variant = "secondary", size = "md", icon, softDisabled, className, children, onClick,
  type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClass(variant, size, className)}
      aria-disabled={softDisabled || undefined}
      onClick={(e) => {
        if (softDisabled) {
          e.preventDefault();
          return;
        }
        onClick?.(e);
      }}
      {...rest}
    >
      {icon ? <span className="size-4 shrink-0 [&>svg]:size-4" aria-hidden="true">{icon}</span> : null}
      {children}
    </button>
  );
}

export function ButtonLink({ href, variant = "secondary", size = "md", className, children, icon,
  ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; variant?: Variant; size?: Size; icon?: ReactNode }) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)} {...rest}>
      {icon ? <span className="size-4 shrink-0 [&>svg]:size-4" aria-hidden="true">{icon}</span> : null}
      {children}
    </Link>
  );
}
