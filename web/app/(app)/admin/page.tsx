"use client";

import { UserPlusIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/field";
import { TimeAgo } from "@/components/ui/misc";
import { Chip, StatusBadge } from "@/components/ui/status-badge";
import { ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { sanitize } from "@/lib/parse";
import type { AdminUser, Page, Role } from "@/lib/types";

export default function UsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [form, setForm] = useState({ email: "", display_name: "", role: "viewer" as Role, initial_password: "" });
  const [edit, setEdit] = useState<{ role: Role; is_active: boolean; password: string }>({ role: "viewer", is_active: true, password: "" });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<Page<AdminUser>>("/users", { query: { limit: 100 } }) });
  const create = useMutation({
    mutationFn: () => api<AdminUser>("/users", { method: "POST", body: { ...form, email: sanitize(form.email) } }),
    onSuccess: () => {
      setCreateOpen(false);
      setForm({ email: "", display_name: "", role: "viewer", initial_password: "" });
      toast.show(`User ${form.display_name || form.email} created. Share the initial password through a secure channel.`, { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const update = useMutation({
    mutationFn: (u: AdminUser) => api<AdminUser>(`/users/${u.id}`, { method: "PATCH", body: {
      role: edit.role, is_active: edit.is_active, ...(edit.password ? { password: edit.password } : {}) } }),
    onSuccess: (u) => { setEditing(null); toast.show(`${u.display_name} updated.`, { tone: "success" }); void qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  function submitCreate(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Card>
      <CardHeader title="Users" subtitle="Viewers can read everything; maintainers can change projects; admins also manage users and channels."
        action={<Button variant="primary" icon={<UserPlusIcon />} onClick={() => setCreateOpen(true)}>Create user</Button>} />
      {users.isPending ? <LoadingRows /> : users.isError ? <ErrorState error={users.error} onRetry={() => users.refetch()} /> : (
        <div className="scroll-thin -mx-5 -mb-5 overflow-x-auto border-t border-line max-md:-mx-4 max-md:-mb-4">
          <table className="w-full min-w-[640px] text-left text-[13.5px]">
            <thead className="chrome"><tr className="border-b border-line">
              <th className="px-4 py-2.5">User</th><th className="px-4 py-2.5">Role</th>
              <th className="px-4 py-2.5">State</th><th className="px-4 py-2.5">Last sign-in</th><th className="px-4 py-2.5" /></tr></thead>
            <tbody>
              {users.data.items.map((u) => (
                <tr key={u.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5"><div className="font-medium">{u.display_name}{u.id === me?.id ? <span className="ml-1.5 text-caption font-normal text-ink-2">(you)</span> : null}</div><div className="text-caption text-ink-2">{u.email}</div></td>
                  <td className="px-4 py-2.5"><Chip className="capitalize">{u.role}</Chip></td>
                  <td className="px-4 py-2.5"><StatusBadge tone={u.is_active ? "healthy" : "neutral"}>{u.is_active ? "Active" : "Deactivated"}</StatusBadge></td>
                  <td className="px-4 py-2.5 text-ink-2"><TimeAgo iso={u.last_login_at} /></td>
                  <td className="px-4 py-2.5 text-right"><Button size="sm" variant="ghost" onClick={() => { setEditing(u); setEdit({ role: u.role, is_active: u.is_active, password: "" }); }}>Edit</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Create user" initialFocus="first">
        <form onSubmit={submitCreate} className="flex flex-col gap-4">
          <Field label="Email" htmlFor="u-email"><Input id="u-email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Display name" htmlFor="u-name"><Input id="u-name" required maxLength={100} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></Field>
          <Field label="Role" htmlFor="u-role">
            <Select id="u-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="viewer">Viewer (read-only)</option><option value="maintainer">Maintainer</option><option value="admin">Admin</option>
            </Select>
          </Field>
          <Field label="Initial password" htmlFor="u-pass" hint="12–128 characters.">
            <Input id="u-pass" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={form.initial_password} onChange={(e) => setForm({ ...form, initial_password: e.target.value })} />
          </Field>
          {create.isError ? <ErrorState error={create.error} title="The user was not created." /> : null}
          <div className="-mx-5 -mb-5 mt-1 flex justify-end gap-2 border-t border-line bg-surface-2/50 px-5 py-3 max-md:-mx-4 max-md:-mb-4">
            <Button variant="secondary" data-dialog-cancel onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={create.isPending || form.initial_password.length < 12}>Create user</Button>
          </div>
        </form>
      </Dialog>
      <Dialog open={!!editing} onClose={() => setEditing(null)} title={`Edit ${editing?.display_name ?? ""}`}
        footer={<>
          <Button variant="secondary" data-dialog-cancel onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            if (!editing) return;
            const deactivating = editing.is_active && !edit.is_active;
            const selfRole = editing.id === me?.id && edit.role !== editing.role;
            if (deactivating || selfRole) {
              const ok = await confirm({
                title: deactivating ? `Deactivate ${editing.display_name}?` : "Change your own role?",
                destructive: true,
                confirmLabel: deactivating ? "Deactivate user" : "Change my role",
                body: deactivating
                  ? <p>{editing.display_name} is signed out everywhere and can no longer sign in. Their history is kept, and you can reactivate them later.</p>
                  : <p>You may lose access to this page immediately. Another admin would have to restore your role.</p>,
              });
              if (!ok) return;
            }
            update.mutate(editing);
          }} disabled={update.isPending || (!!edit.password && edit.password.length < 12)}>Save</Button>
        </>}>
        <div className="flex flex-col gap-4">
          <Field label="Role" htmlFor="e-role">
            <Select id="e-role" value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value as Role })}>
              <option value="viewer">Viewer</option><option value="maintainer">Maintainer</option><option value="admin">Admin</option>
            </Select>
          </Field>
          <Field label="State" htmlFor="e-state" hint="Deactivation signs the user out everywhere.">
            <Select id="e-state" value={edit.is_active ? "active" : "inactive"} onChange={(e) => setEdit({ ...edit, is_active: e.target.value === "active" })}>
              <option value="active">Active</option><option value="inactive">Deactivated</option>
            </Select>
          </Field>
          <Field label="Reset password" htmlFor="e-pass" optional hint="Leave empty to keep the current password.">
            <Input id="e-pass" type="password" autoComplete="new-password" value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} />
          </Field>
          {update.isError ? <ErrorState error={update.error} title="Not saved." /> : null}
        </div>
      </Dialog>
    </Card>
  );
}
