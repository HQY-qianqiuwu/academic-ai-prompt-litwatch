# Restore LitWatch on a New PC

This guide restores the tracked project framework from the private GitHub backup:

```text
https://github.com/HQY-qianqiuwu/dify-literature-search-workflow
```

The repository must remain private. Sign in to the GitHub account that has access before cloning.

## 1. Install prerequisites

Install the following software on the new Windows PC:

1. Git
2. Docker Desktop
3. Python 3.11 or newer
4. Visual Studio Code

Verify the command-line tools:

```powershell
git --version
python --version
docker version
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

Use the current v1.1 release-candidate development branch:

```powershell
git switch feat/dify-literature-workflow
```

The stable Dify v1.0 baseline is preserved by the `dify-v1.0` annotated tag. To create an
isolated v1.0 recovery branch:

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

For local browser access only:

```powershell
& ".\.venv\Scripts\litwatch.exe" serve --host 127.0.0.1 --port 8000
```

For the Dify Docker workflow, LitWatch must be reachable from containers:

```powershell
& ".\.venv\Scripts\litwatch.exe" serve --host 0.0.0.0 --port 8000
```

Verify the API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 7. Restore Dify separately

Install or clone the official Dify Community Edition deployment, configure its `.env`, and start
its Docker Compose stack from the Dify `docker` directory:

```powershell
docker compose up -d
docker compose ps
```

Do not modify Dify's PostgreSQL database directly. Docker volumes and Dify runtime data require a
separate data backup; they are not restored by this Git repository.

## 8. Import the Dify workflow

The stable workflow is:

```text
dify/workflows/literature-search-v1.0.yml
```

The v1.1 release candidate is:

```text
dify/workflows/literature-search-v1.1.yml
```

Import the required DSL through the authenticated Dify console. The v1.1 workflow calls:

```text
http://host.docker.internal:8000/api/v1/literature/search
```

Run the v1.1 smoke test after LitWatch and Dify are running:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\smoke-v1.1.ps1
```

Do not treat v1.1 as stable until the imported workflow has completed a real runtime test.

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

After the new PC has completed the prerequisite, repository, Python environment,
local configuration, Dify Docker, workflow import, and data-volume recovery steps
above, daily operation uses the stack management commands in the LitWatch project
root.

Start Docker Desktop when necessary, Dify, LitWatch, validate OpenAlex and the Dify
SSRF proxy, and then open Dify:

```text
启动科研文献系统.cmd
```

Stop LitWatch and the Dify Compose services while preserving all Docker volumes:

```text
停止科研文献系统.cmd
```

Check the system without changing its state:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\status-stack.ps1
```

The startup script discovers the sibling `dify\docker` directory automatically.
If Dify is installed elsewhere, set `DIFY_DOCKER_DIR` to the directory containing
its Compose file before running the command. Port 8000 must either be unused or
owned by this repository's LitWatch process; the scripts report the owning PID,
executable, and command line instead of terminating an unrelated process.
