# Restore LitWatch on a New PC

This guide restores the tracked project framework from the private GitHub backup:

```text
https://github.com/HQY-qianqiuwu/dify-literature-search-workflow
```

The repository must remain private. Sign in to the GitHub account that has access before cloning.

## 1. Install prerequisites

Install the following software on the new Windows PC:

1. Git
2. Python 3.11 or newer
3. Visual Studio Code

Docker Desktop is **not** a prerequisite for the v2.0 Python-default runtime.
Install it only if the explicit legacy Dify rollback path must be restored.

Verify the command-line tools:

```powershell
git --version
python --version
```

For an explicitly authorized legacy rollback, also verify `docker version`.

## 2. Clone the private repository

Authenticate with GitHub through Git Credential Manager, GitHub CLI, or another approved
token-based method. Do not use a GitHub account password for Git operations.

```powershell
git clone https://github.com/HQY-qianqiuwu/dify-literature-search-workflow.git
cd dify-literature-search-workflow
git branch -a
git tag
```

## 3. Select a branch or recovery point

The v2.0 Python-native work is currently in implementation / release-candidate
preparation and is **not Stable**. Restore the reviewed v2.0 branch or commit
supplied with the backup; do not invent or move a `v2.0` Stable tag. In this
worktree the development branch is:

```powershell
git switch feat/v2.0-python-native-runtime
```

For an accepted Stable recovery point, select the required existing `dify-v1.x`
tag from `docs/RELEASE_MATRIX.md`; v1.7 is the latest accepted Stable Stack.
The stable Dify v1.0 baseline remains preserved by the `dify-v1.0` annotated
tag. To create an isolated v1.0 recovery branch:

```powershell
git switch -c recovery/dify-v1.0 dify-v1.0
```

Do not move or overwrite the `dify-v1.0` tag.

## 4. Recreate the Python environment

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
```

Run the verification suite:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q
& ".\.venv\Scripts\ruff.exe" check src tests
```

## 5. Recreate local configuration and secrets

Copy the tracked example file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally and enter the required API keys and credentials again. Never commit `.env`.
The private GitHub repository intentionally does not contain live secrets.

If a runtime topics file is missing, copy and customize the example:

```powershell
Copy-Item config\topics.example.yaml config\topics.yaml
```

## 6. Start LitWatch

The default Windows lifecycle is Python-only:

```text
启动科研文献系统.cmd
停止科研文献系统.cmd
```

Check it without changing state:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\status-stack.ps1
```

These commands do not probe, start, or require Docker, Dify, Compose, or the
Dify SSRF proxy. They never fall back to Dify after a Python startup failure.

For direct local browser access without the lifecycle wrapper:

```powershell
& ".\.venv\Scripts\litwatch.exe" serve --host 127.0.0.1 --port 8000
```

Only for the explicit legacy Dify rollback workflow, LitWatch must be reachable
from containers:

```powershell
& ".\.venv\Scripts\litwatch.exe" serve --host 0.0.0.0 --port 8000
```

Verify the API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 7. Optional legacy rollback: restore Dify separately

Skip this section for normal v2.0 operation. Dify is retained only as an
explicit rollback path during manual acceptance; it is never an automatic
fallback.

Install or clone the official Dify Community Edition deployment, configure its `.env`, and start
its Docker Compose stack from the Dify `docker` directory:

```powershell
docker compose up -d
docker compose ps
```

Do not modify Dify's PostgreSQL database directly. Docker volumes and Dify runtime data require a
separate data backup; they are not restored by this Git repository.

### Restore the Dify 1.16.1 LitWatch SSRF exception

The local Dify HTTP Request node requires a narrow Squid exception for
`host.docker.internal:8000`. Reapply the version-controlled integration from the LitWatch root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\apply-dify-ssrf-integration.ps1 `
  -RestartProxy
```

This script is restricted to Dify 1.16.1 and allows only the LitWatch host and port combination.
It does not open other Docker-host ports or private networks. See
`docs/DIFY_SSRF_INTEGRATION.md` for the security checks and upgrade boundary.

## 8. Optional legacy rollback: import the frozen Dify workflow

The frozen stable legacy workflows are:

```text
dify/workflows/literature-search-v1.0.yml
dify/workflows/literature-search-v1.1.yml
```

Import the selected legacy DSL through the authenticated Dify console. The v1.1
workflow calls:

```text
http://host.docker.internal:8000/api/v1/literature/search
```

Run the v1.1 smoke test after LitWatch and Dify are running:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\smoke-v1.1.ps1
```

An imported legacy workflow still requires a real runtime test on the restored
machine. Its success validates only that selected v1.x rollback; it does not
make the Python-native v2.0 implementation Stable.

The historical Dify repository, volumes, integration patch, and v1.0/v1.1 DSL
files are retained and frozen until v2.0 manual acceptance completes and a
separate deletion or migration action is authorized. Do not rewrite these DSL
files as part of restoring or validating the Python-default runtime.

## 9. GitHub connector access

The Codex GitHub connector may require its repository installation scope to be updated after this
private repository is created. Add `HQY-qianqiuwu/dify-literature-search-workflow` to the
connector's selected repositories if Codex reports `404 Not Found` while GitHub CLI access works.

## What GitHub restores

The private repository restores:

- Source code and Git commit history
- Branches and annotated Git tags
- Dify workflow DSL files
- Prompts, tests, documentation, and deployment scripts
- `.env.example` and other non-secret configuration examples

## What GitHub does not restore

The private repository does not restore:

- `.env` secrets or API keys
- Docker volumes
- Dify PostgreSQL runtime data
- PDF attachments
- Zotero local attachment cache
- Ignored SQLite runtime databases
- Other ignored or untracked local-only files

Back up those data sources separately before replacing or retiring the original PC.

## Daily start and stop after recovery

After the new PC has completed the repository, Python environment, and local
configuration steps above, normal daily operation uses the Python-only stack
management commands in the LitWatch project root. Dify Docker, workflow import,
and volume recovery are not prerequisites for this default path.

Start only Python LitWatch:

```text
启动科研文献系统.cmd
```

Stop only the managed Python LitWatch process:

```text
停止科研文献系统.cmd
```

Check the system without changing its state:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\status-stack.ps1
```

There is no automatic Dify fallback. For an explicitly chosen legacy rollback,
use `启动旧版 Dify 科研文献系统.cmd` and
`停止旧版 Dify 科研文献系统.cmd`; only those legacy commands discover
`dify\docker`, start or stop Compose, and validate the SSRF proxy. If Dify is
installed elsewhere, set `DIFY_DOCKER_DIR` only for that legacy action.

Port 8000 must either be unused or owned by this repository's fully validated
LitWatch process. The default scripts report the owning PID, executable,
creation identity, and command line instead of terminating an unrelated or
provisional process.
