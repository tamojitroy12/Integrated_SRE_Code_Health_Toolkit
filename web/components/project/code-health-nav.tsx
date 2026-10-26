import { SegmentedNav } from "@/components/ui/misc";

export function CodeHealthNav({ projectId }: { projectId: string }) {
  const base = `/projects/${projectId}/code-health`;
  return (
    <SegmentedNav
      items={[
        { href: base, label: "Findings", exact: true },
        { href: `${base}/scans`, label: "Scans" },
        { href: `${base}/fix-proposals`, label: "Fix proposals" },
      ]}
    />
  );
}
