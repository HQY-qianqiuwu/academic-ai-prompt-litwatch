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

Docker Desktop is not a prerequisite for the v2.0 Python-only runtime. Dify
content has been removed from the working tree by user decision; no Dify
rollback entry point is provided.

Verify the command-line tools:

```powershell
git --version
python --version
```

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

The v1.0/v1.1 workflow DSL files were removed from the working tree by user
decision. They remain available in the `dify-v1.0` / `dify-v1.1` tags if a
historical v1.x review is ever required.

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

Verify the API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 7. Dify content removal

Dify content in this repository (legacy launchers, lifecycle scripts, and
`dify/workflows/` DSL files) has been removed by user decision. The default
and only runtime is Python LitWatch. The v1.x DSL files remain recoverable
from the `dify-v1.x` Git tags, and the external Dify deployment and its Docker
volumes were not part of this repository and require a separate data backup if
they are ever restored.

## 9. GitHub connector access

The Codex GitHub connector may require its repository installation scope to be updated after this
private repository is created. Add `HQY-qianqiuwu/dify-literature-search-workflow` to the
connector's selected repositories if Codex reports `404 Not Found` while GitHub CLI access works.

## What GitHub restores

The private repository restores:

- Source code and Git commit history
- Branches and annotated Git tags
- Historical Dify workflow DSL files (recoverable from Git tags)
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

There is no automatic Dify fallback and no legacy Dify entry points. The
repository root exposes only the Python-only launchers
`启动科研文献系统.cmd` and `停止科研文献系统.cmd`.

Port 8000 must either be unused or owned by this repository's fully validated
LitWatch process. The default scripts report the owning PID, executable,
creation identity, and command line instead of terminating an unrelated or
provisional process.
