import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge the project's custom theme keys so e.g. `text-caption` (a size) does not
// cancel `text-ink-2` (a colour), while a caller's `rounded-none` correctly overrides `rounded-control`.
const merge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["title", "body", "caption"],
      radius: ["control", "panel", "hero"],
      shadow: ["card", "pop"],
    },
  },
});

export function cn(...parts: (string | false | null | undefined)[]): string {
  return merge(...parts);
}
