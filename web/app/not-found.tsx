import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-6">
      <div className="text-center">
        <h1 className="text-[28px] font-bold tracking-[-0.03em]">Page not found</h1>
        <p className="mt-2 text-ink-2">The page does not exist or you do not have access to it.</p>
        <Link href="/projects" className="mt-6 inline-flex min-h-9 items-center rounded-full border border-accent px-4 font-semibold text-accent">Go to projects</Link>
      </div>
    </main>
  );
}
