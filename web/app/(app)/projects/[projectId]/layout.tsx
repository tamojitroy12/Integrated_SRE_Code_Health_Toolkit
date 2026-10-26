"use client";

import type { ReactNode } from "react";

import { Banner, ErrorState } from "@/components/ui/states";
import { useProject, useProjectParam } from "@/lib/project";

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const projectId = useProjectParam();
  const project = useProject(projectId);
  if (project.isError) return <ErrorState error={project.error} title="Project unavailable." onRetry={() => project.refetch()} />;
  return (
    <>
      {project.data?.archived_at ? (
        <div className="mb-6">
          <Banner tone="info">This project is archived and read-only. Its data stays available for review.</Banner>
        </div>
      ) : null}
      {children}
    </>
  );
}
