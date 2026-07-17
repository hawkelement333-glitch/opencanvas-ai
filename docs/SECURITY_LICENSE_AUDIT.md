# Security, privacy, and dependency-license audit

Audit date: July 17, 2026

Scope: OpenCanvas AI working tree in `Project Mobius Cartographer`

Conclusion: no high-confidence secret, incompatible direct license, or known production JavaScript
advisory found after remediation; manual legal and Python reproducibility follow-up remains

This is an engineering audit, not legal advice, a penetration test, or a guarantee that every
secret, vulnerability, or license obligation has been identified.

## Repository state and method

- Git reported `No commits yet on master`; every project file was untracked at audit time.
- Because `HEAD` does not exist, there was no Git history to scan or rewrite.
- The working tree, including relevant untracked files, was scanned by secret/token/private-key
  patterns and by sensitive filename/extension inventory.
- Candidate credential assignments were reviewed in redacted form. Values were not copied into
  this report.
- Direct JavaScript manifests and the lockfile, direct Python requirements, official npm/PyPI
  metadata, container definitions, local storage code, environment configuration, bundled
  assets, and sample fixtures were reviewed.
- JavaScript production advisories were queried from the pnpm registry audit endpoint.

## Secret and privacy findings

### No detected release secret

No high-confidence OpenAI key, AWS key, GitHub token, Google key, JWT, private-key block,
certificate/key file, private dataset, personal email address, log dump, local environment file,
or local database file was found. The only environment file present was `.env.example`.

Thirteen generic credential-assignment matches were reviewed. They were configuration plumbing,
synthetic test values, or the documented local PostgreSQL development credential. No production
secret was identified. The local credential must not be reused outside an isolated development
environment.

The URL-host inventory contained only local/test endpoints and public framework documentation.
No private service URL was identified. These pattern checks can produce false negatives; a human
review remains required before publication.

### Privacy boundary

The database can retain uploaded files' metadata and extracted text, document chunks and
embeddings, notes, exact user instructions, selected-node snapshots, retrieval rankings,
responses, citations, and Trace evidence. That is sensitive knowledge-work data even when it
does not match a conventional PII pattern.

When an OpenAI key is configured and either provider is `auto`/`openai`, selected content,
instructions, retrieved passages, or document chunks can leave the local machine for generation
or embedding. Mock mode avoids those external model calls. This behavior is now explicit in
`.env.example` and `SECURITY.md`.

### Hosted-deployment risk: high until authentication exists

The application has no authentication or authorization. Any network client that can reach the
API can operate on stored content. This is not a blocker for an isolated, single-user Build Week
demo, but it blocks representing the current build as an internet-facing or multi-user production
service. Required next controls include authentication, workspace authorization, tenant
isolation, stronger abuse/rate controls, TLS, network policy, retention governance, and backup
handling.

### Existing positive controls observed

- OpenAI calls remain server-side and the API key is not exposed through `NEXT_PUBLIC_*`.
- Production API documentation is disabled, CORS origins are configurable, and credentialed
  cross-origin requests are disabled.
- Upload validation includes extension/content checks and size/archive/page limits.
- Local document storage uses opaque names and resolved-root containment checks.
- Model instructions treat uploaded and selected content as untrusted data and reject embedded
  instruction override attempts.
- Document deletion attempts to remove both application records and the active stored file.

These controls reduce risk but do not replace authentication, malware scanning, a sandboxed
extractor, or a formal privacy/retention program.

## Repository hygiene changes

`.gitignore` now excludes all local environment variants except `.env.example`, generated build
and coverage output, logs, caches, temporary paths, local runtime/uploads/data, common local
database forms, IDE state, and common private-key/credential filenames. `.env.example` contains
placeholder/local-development values only and now labels optional, production-sensitive, and
browser-visible settings.

## Dependency advisory finding

`corepack pnpm audit --prod --audit-level=moderate` completed with exit code 0 and reported
`No known vulnerabilities found`.

The earlier moderate
[GHSA-qx2v-qp2m-jg93](https://github.com/advisories/GHSA-qx2v-qp2m-jg93) finding in Next.js'
transitive PostCSS dependency is remediated. The requested root `package.json` override and the
effective pnpm workspace override pin `next>postcss` to patched `8.5.14`; the regenerated lockfile
contains `postcss@8.5.14` and Vite's `postcss@8.5.19`, not vulnerable `8.4.31`.

Remediation was verified with frozen installation, the production audit, the canonical validation
suite, production build, deterministic demo checks, and source-only clean-clone reproduction:

```powershell
corepack pnpm install --lockfile-only
corepack pnpm install --frozen-lockfile
corepack pnpm audit --prod --audit-level=moderate
corepack pnpm validate
corepack pnpm validate:clean-clone
```

The lockfile was regenerated by pnpm rather than hand-edited. No production JavaScript advisory is
known from the final registry audit; this does not replace future dependency monitoring.

A resolved Python advisory scan was not performed because the repository has no Python lockfile
or repository-defined Python advisory tool. The validation environment's exact installed
versions were recorded in `THIRD_PARTY_NOTICES.md`, and `python -m pip check` reported no broken
requirements. That consistency check is not a vulnerability scan. The missing lock remains a
reproducibility and audit gap, not evidence that a particular Python package is vulnerable.

## Direct dependency-license result

The complete inventory is in `THIRD_PARTY_NOTICES.md`.

- JavaScript runtime: MIT and ISC.
- JavaScript development: MIT and Apache-2.0.
- Python runtime: MIT, Apache-2.0, BSD-3-Clause, `MIT OR Apache-2.0`, and the `orjson` expression
  `MPL-2.0 AND (Apache-2.0 OR MIT)`.
- Python build/development: MIT and Apache-2.0.
- No direct GPL, AGPL, noncommercial, unknown, or custom license was found.
- No material third-party asset or dataset with unclear rights was found.

An installed JavaScript production-tree scan also identified material transitive licenses:
`sharp` platform packages at 0.34.5 include an
`Apache-2.0 AND LGPL-3.0-or-later` expression for bundled native/libvips components, and
`caniuse-lite` 1.0.30001806 declares CC-BY-4.0. Neither is automatically incompatible with a
proprietary application, but both impose redistribution conditions. The exact Linux/Alpine
artifacts in the release image need their own SBOM, notices, attribution, and LGPL compliance
review.

The `orjson` expression is not considered an incompatibility with a proprietary application,
but shipped binaries and modifications need review for MPL file-level obligations and included
Apache/MIT components. No modified or vendored `orjson` source was found.

The final API and web Docker image stages now copy `COPYRIGHT`, `NOTICE`, and
`THIRD_PARTY_NOTICES.md` into the release images. This preserves the project-level inventory in
the packaged artifacts. It does not replace a complete transitive SBOM or the full upstream
copyright and license texts generated from the exact resolved packages for each target image;
those remain required before binary/container redistribution.

## Copyright and project-license status

`COPYRIGHT` and `NOTICE` reserve the project owner's rights without claiming registration.
No open-source `LICENSE` was created. `LICENSE_RECOMMENDATION.md` recommends All Rights Reserved
for the private-submission path and presents MIT and Apache-2.0 alternatives. The verified rules
allow a private repository shared with `testing@devpost.com` and
`build-week-event@openai.com`; that path does not require an open-source license. A public release
or Apache-2.0 selection still requires the owner's explicit approval.

## Commands and focused results

The audit used read-only Git status/history checks, `rg` file and pattern inventories, redacted
PowerShell pattern review, official npm/PyPI metadata queries, lockfile inspection, and:

```powershell
corepack pnpm audit --prod --audit-level=moderate
pnpm licenses list --prod --json
\.venv\Scripts\python.exe -m pip check
corepack pnpm validate
corepack pnpm validate:clean-clone
```

Result: the moderate production advisory gate, complete local validation, and clean-clone
reproduction passed. The final hygiene scan checked 159 commit-eligible source files.

After documentation changes, a focused trailing-whitespace/final-newline scanner and the ignore
behavior checks passed:

```powershell
git check-ignore -v .env .env.local opencanvas.db data/documents/private.pdf
```

The ignore behavior check used representative nonexistent paths and did not create secret or
runtime files.

## Required release actions

1. Add reproducible Python dependency resolution and audit the exact set.
2. Include full third-party license texts/notices in distributed images and bundles.
3. Keep the current build isolated until authentication and authorization are implemented.
4. Keep the repository private and share it with both required judging addresses unless Patrick
   explicitly approves Apache-2.0 and a public release.
5. Perform a final human secret/privacy review immediately before commit and publication.
