# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/security/advisories/new)
rather than opening a public issue.

Include what you did, what happened, and what you expected. A proof of concept helps but is
not required. We aim to acknowledge within a week.

## Scope

This repository holds the code that downloads, indexes and serves the Kansallisarkisto
Sisältöhaku corpora. It holds **no archival records** — those belong to
[Kansallisarkisto](https://kansallisarkisto.fi/) and are fetched from its
[Sisältöhaku service](https://sisaltohaku.demo.kansallisarkisto.fi/). Issues with the
archival data or that service belong to Kansallisarkisto, not here.

In scope: the MCP server and its tools, the ingest and harvest scripts, the container image,
and the release pipeline.

## What the automated checks already cover

Before reporting, it may help to know these run continuously:

- **Trivy** scans the published image weekly and gates every release
  (`.github/workflows/security.yml`). Its full report, including the base image's standing
  set of unfixed OS CVEs, is in the Security tab — see
  [docs/development/security.md](docs/development/security.md#what-the-security-tab-shows-and-why-it-is-not-an-emergency)
  for why those are expected rather than actionable.
- **pip-audit** fails the build on any known-vulnerable Python dependency.
- **TruffleHog** scans the full git history for leaked credentials on every push.
- **Dependabot** opens updates weekly; patch and minor bumps merge automatically once tests pass.

## Releases

Images are built with SBOM and SLSA Build L3 provenance, signed keylessly with cosign, and
verifiable with `slsa-verifier`. See
[docs/development/security.md](docs/development/security.md).
