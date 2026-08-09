# Dify 1.16.1 LitWatch SSRF Integration

## Purpose

Dify's HTTP Request node sends outbound traffic through the `ssrf_proxy` Squid
service. Squid correctly blocks private and local destinations by default, which
also blocks the local LitWatch endpoint exposed through Docker Desktop as:

```text
http://host.docker.internal:8000/api/v1/literature/search
```

This repository stores a version-controlled, minimal exception for Dify 1.16.1.
It permits only the conjunction of:

- destination domain `host.docker.internal`
- destination port `8000`

It does not enable Dify's broad private-IP or private-domain allowlists and does
not allow other ports on the Docker host.

## Reapply on a new PC

Place the official Dify repository beside this LitWatch repository so the default
layout is:

```text
<parent>\academic-ai-prompt-litwatch
<parent>\dify
```

Confirm that Dify is exactly version 1.16.1, then run from the LitWatch root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\apply-dify-ssrf-integration.ps1 `
  -RestartProxy
```

For a non-sibling Dify checkout, provide its repository root explicitly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\apply-dify-ssrf-integration.ps1 `
  -DifyRoot "D:\path\to\dify" `
  -RestartProxy
```

The script is idempotent. It stops without changing files when the Dify version
is not 1.16.1, the patch cannot apply cleanly, or only part of the expected ACL
is present. It recreates only `ssrf_proxy` when `-RestartProxy` is supplied and
does not remove Docker volumes.

The exact source patch is:

```text
integrations/dify/1.16.1/litwatch-ssrf.patch
```

## Verification

After LitWatch and Dify are running, the following must hold:

| Target | Expected result |
|---|---|
| `host.docker.internal:8000` | allowed |
| `host.docker.internal:80` | blocked by Squid with HTTP 403 |
| `host.docker.internal:8001` | blocked by Squid with HTTP 403 |
| another private service such as `db_postgres:5432` | blocked by Squid with HTTP 403 |

Run the normal stack status check:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\status-stack.ps1
```

Then run the Dify workflow with two different topics and confirm both return
real OpenAlex papers while producing different result sets.

## Upgrade boundary

Do not apply this patch to another Dify version. Review that version's current
SSRF implementation and regenerate a version-specific integration asset. Never
replace this exception with `allow all`, a global SSRF disable switch, or a
blanket private-network CIDR allowlist.
