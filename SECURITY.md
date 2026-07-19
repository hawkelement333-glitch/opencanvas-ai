# Security policy

## Supported release

SolarPlexus Mobius, formerly developed under the working name OpenCanvas AI, is currently a Build
Week competition release candidate. Until a supported production release is published, security
fixes apply only to the current repository state. Published version-support promises must be added
explicitly when the first supported release is approved.

## Report a vulnerability privately

Do not disclose suspected vulnerabilities, exposed credentials, private documents, or user data in
a public issue. Use **Report a vulnerability** on this repository's GitHub Security page; private
vulnerability reporting is the approved disclosure channel. If that control is temporarily
unavailable, contact the repository owner through the GitHub profile without including sensitive
details in a public message.

Include a concise impact description, affected version or commit, reproduction steps, and a safe
proof of concept. Do not access data that is not yours, disrupt a service, or retain copied data.
Receipt or response times are not guaranteed until a formal disclosure process exists.

## Current deployment boundary

The current application has **no authentication or authorization**. It is suitable only for a trusted
local, isolated demo environment. Do not expose the API, database, or document storage to the public
internet or use it for multiple untrusted users. Authentication, workspace-level authorization,
abuse controls, and tenant isolation are required before hosted production use.

The checked-in PostgreSQL username and password are local-development placeholders. They must not be
reused outside an isolated development environment.

## Secrets and configuration

- Copy `.env.example` to `.env`; never commit `.env` or real credentials.
- Keep `OPENAI_API_KEY` server-side. Never place a credential in `NEXT_PUBLIC_*`, client code,
  screenshots, logs, demo fixtures, or issue reports.
- Use a dedicated, least-privilege database account and a secret manager in production.
- Rotate a credential immediately if it is committed, logged, pasted into a report, or shared
  outside its intended audience. Removing a file does not revoke the credential.
- Set explicit production CORS origins, terminate TLS at a trusted proxy, and restrict database and
  API network access.

## Data and privacy behavior

SolarPlexus Mobius can persist uploaded files, extracted document text, chunks and embeddings, canvas
content, user instructions, selected-node snapshots, retrieval rankings, AI responses, citations,
and Trace records. Treat the database, storage volume, backups, and exported logs as sensitive.

With `OPENCANVAS_AI_PROVIDER=auto` and a configured OpenAI key, the selected context and user
instruction are sent to the configured OpenAI service. With
`OPENCANVAS_EMBEDDING_PROVIDER=auto` and a configured key, document chunks may be sent for embedding.
Set both providers to `mock` when content must remain local. Review the provider's current data-use
and retention terms before processing confidential, regulated, or personal information.

Document deletion removes the active stored file and associated application records through the
document API, but it cannot erase independent backups, provider-side data, external logs, or
previously exported copies. Canonical lifecycle deletion is a soft-deletion/audit mechanism and may
intentionally retain records. Define and test a retention policy before real user data is accepted.

## Untrusted content

Uploaded documents and node text are untrusted input. The application validates supported file
formats, size and archive limits, uses opaque non-public storage keys with root-containment checks,
and instructs the model not to follow embedded prompt instructions. These controls do not make
arbitrary content risk-free. Keep extraction libraries patched, scan uploads where deployment risk
requires it, render text without executing embedded content, and do not treat model prompt boundaries
as a complete security boundary.

## Dependency and release hygiene

- Install from the committed JavaScript lockfile with the repository's documented pnpm version.
- Python dependencies currently use bounded ranges rather than a resolved lock; regenerate the
  dependency/license audit for every release until reproducible locking is added.
- Run the canonical validation gate and dependency advisory checks before release.
- Preserve third-party license notices when distributing containers, binaries, or browser bundles.
  See `THIRD_PARTY_NOTICES.md`.

## Known release security findings

The July 17, 2026 release audit and pre-publication history scan found no high-confidence committed
secret, private key, database, upload, runtime artifact, or real environment file. The production
PostCSS advisory was remediated by the lockfile-backed `8.5.14` override, and the final production
dependency audit reported no known vulnerabilities at moderate severity or higher. See
`docs/SECURITY_LICENSE_AUDIT.md` for scope and caveats.
