"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/ui/card";
import { SegmentedNav } from "@/components/ui/misc";
import { EmptyState } from "@/components/ui/states";
import { useAuth } from "@/lib/auth";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { can } = useAuth();
  if (!can("admin")) return <EmptyState title="Admins only.">Your role does not include administration.</EmptyState>;
  return (
    <>
      <PageHeader title="Admin" subtitle="Users, notification channels and the audit log." />
      <SegmentedNav items={[{ href: "/admin", label: "Users", exact: true }, { href: "/admin/channels", label: "Notification channels" },
        { href: "/admin/audit", label: "Audit log" }]} />
      {children}
    </>
  );
}
