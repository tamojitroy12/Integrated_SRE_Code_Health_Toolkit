"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { ErrorState } from "@/components/ui/states";
import { api } from "@/lib/api";
import { normalizeRepo, sanitize } from "@/lib/parse";
import type { Repository } from "@/lib/types";

/** Connect or replace a repository. The token field is write-only (UI_UX_SPEC §9 "Secrets"). */
export function RepositoryForm({ projectId, existing, onDone, submitLabel = "Verify and connect" }: {
  projectId: string;
  existing?: Repository | null;
  onDone?: (repo: Repository) => void;
  submitLabel?: string;
}) {
  const qc = useQueryClient();
  const [url, setUrl] = useState(existing ? existing.url : "");
  const [token, setToken] = useState("");
  const [branch, setBranch] = useState("");
  const [testCommand, setTestCommand] = useState(existing?.test_command ?? "");
  const repo = normalizeRepo(url);
  const mutation = useMutation({
    mutationFn: () =>
      api<Repository>(`/projects/${projectId}/repository`, {
        method: "PUT",
        body: {
          url: repo?.url ?? url,
          token: token ? sanitize(token) : undefined,
          default_branch: branch ? sanitize(branch) : undefined,
          test_command: testCommand || null,
        },
      }),
    onSuccess: (data) => {
      setToken("");
      void qc.invalidateQueries({ queryKey: ["repository", projectId] });
      void qc.invalidateQueries({ queryKey: ["overview", projectId] });
      onDone?.(data);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Field
        label="GitHub repository"
        htmlFor="repo-url"
        hint={repo ? `Will connect to github.com/${repo.owner}/${repo.name}` : "Accepts org/repo, a GitHub URL, or git@github.com:org/repo.git"}
        error={url && !repo ? "Not a GitHub repository address." : undefined}
      >
        <Input id="repo-url" value={url} onChange={(e) => setUrl(e.target.value)} onBlur={() => setUrl(sanitize(url))}
          placeholder="example-org/example-repo" autoComplete="off" spellCheck={false} />
      </Field>
      <Field
        label="Access token"
        htmlFor="repo-token"
        optional
        hint={existing?.has_token ? "Token stored. Enter a new one to replace it." :
          "Fine-grained PAT. Needed for private repositories (Contents: read) and for fix PRs (Contents and Pull requests: write)."}
      >
        <Input id="repo-token" type="password" value={token} autoComplete="off"
          onChange={(e) => setToken(e.target.value)} onBlur={() => setToken(sanitize(token))} />
      </Field>
      <details className="rounded-control border border-line bg-surface-2/30 px-4 py-1.5">
        <summary className="chrome hit flex h-8 cursor-pointer items-center text-[13px] font-medium">Advanced options</summary>
        <div className="mt-3 flex flex-col gap-4 pb-2">
          <Field label="Default branch" htmlFor="repo-branch" optional hint="Leave empty to use the repository's default branch.">
            <Input id="repo-branch" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder={existing?.default_branch ?? "main"} />
          </Field>
          <Field label="Test command" htmlFor="repo-test" optional hint="Used to validate fix proposals in the sandbox.">
            <Select id="repo-test" value={testCommand} onChange={(e) => setTestCommand(e.target.value)}>
              <option value="">None (fix proposals will be unverified)</option>
              <option value="npm test">npm test</option>
              <option value="npm run test">npm run test</option>
              <option value="pytest">pytest</option>
              <option value="python -m pytest">python -m pytest</option>
            </Select>
          </Field>
        </div>
      </details>
      {mutation.isError ? <ErrorState error={mutation.error} title="The repository could not be connected." /> : null}
      <div>
        <Button type="submit" variant="secondary" disabled={!repo || mutation.isPending}>
          {mutation.isPending ? "Verifying with GitHub…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
