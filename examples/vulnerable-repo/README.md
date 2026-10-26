# vulnerable-repo (test fixture)

Seeded fixture used for SM-02 (seeded-vulnerability recall), static-analysis tests, AI redaction
and prompt-injection tests, and fix-proposal demos. **Do not deploy or publish this code.**

| Path | Content |
|---|---|
| `npm-app/` | `package.json` + lockfile with 7 vulnerable/deprecated packages, insecure JS patterns, `node --test` suite |
| `python-app/` | pinned `requirements.txt` with 6 vulnerable packages, insecure Python patterns, `pytest` suite |
| `fixture-manifest.json` | Every seeded version with the advisory IDs returned by the live OSV API on 2026-10-26 |

Both apps contain the synthetic secret `FAKE_KEY_DO_NOT_USE_0000` and a prompt-injection comment.

To scan it with the Toolkit, push this directory to a GitHub repository you control (the Toolkit
only clones from GitHub), connect it to a project, and run a scan. Verify the manifest offline:

```bash
python tools/verify_manifest.py examples/vulnerable-repo/fixture-manifest.json
```
