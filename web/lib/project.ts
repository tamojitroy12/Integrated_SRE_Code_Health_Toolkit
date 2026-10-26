"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { api } from "./api";
import type { Project } from "./types";

export function useProjectParam(): string {
  const params = useParams<{ projectId: string }>();
  return params.projectId;
}

export function useProject(projectId: string) {
  return useQuery({ queryKey: ["project", projectId], queryFn: () => api<Project>(`/projects/${projectId}`) });
}
