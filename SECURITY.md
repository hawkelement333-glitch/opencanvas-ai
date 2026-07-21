# Security policy

## Supported release

OpenCanvas AI is an unreleased Build Week project. Until a supported release is published,
security fixes apply only to the current repository state. Published version-support promises
must be added explicitly when the first release is approved.

## Report a vulnerability privately

Do not disclose suspected vulnerabilities, exposed credentials, private documents, or user data
in a public issue. Use **Report a vulnerability** on this repository's GitHub Security page; private
vulnerability reporting is the approved disclosure channel. If that control is temporarily
unavailable, contact the repository owner through the GitHub profile without including sensitive
details in a public message.

Include a concise impact description, affected version or commit, reproduction steps, and a
safe proof of concept. Do not access data that is not yours, disrupt a service, or retain copied
data. Receipt or response times are not guaranteed until a formal disclosure channel exists.

## Current deployment boundary

Milestone 3.5 provides individual accounts, database-backed sessions, CSRF protection, multiple
owned workspaces, and server-side authorization for workspace data, private files, executions,
citations, and Trace records. Staging and production fail closed unless PostgreSQL, SMTP password
reset, explicit live AI/embedding providers, private S3-compatible storage, and the durable worker
are configured. These controls have automated coverage but are not a certification or substitute
for a deployment-specific threat assessment and penetration test.

The checked-in PostgreSQL username and password are local-development placeholders. They must
not be reused outside an isolated development environment.

## Secrets and configuration

- Copy `.env.example` to `.env`; never commit `.env` or real credentials.
- Keep `OPENAI_API_KEY` server-side. Never place a credential in `NEXT_PUBLIC_*`, client code,
  screenshots, logs, demo fixtures, or issue reports.
- Use a dedicated, least-privilege database account and a secret manager in production.
- Rotate a credential immediately if it is committed, logged, pasted into a report, or shared
  outside its intended audience. Removing a file does not revoke the credential.
- Set explicit production CORS origins, terminate TLS at a trusted proxy, and restrict database
  and API network access.

## Data and privacy behavior

OpenCanvas can persist uploaded files, extracted document text, chunks and embeddings, canvas
content, user instructions, selected-node snapshots, retrieval rankings, AI responses,
citations, and Trace records. Treat the database, storage volume, backups, and exported logs as
sensitive.

With `OPENCANVAS_AI_PROVIDER=openai`, the selected context and user instruction are sent to the
configured OpenAI service. With `OPENCANVAS_EMBEDDING_PROVIDER=openai`, document chunks are sent
for embedding. Provider selection is explicit and failures never fall back to mock results. Set
both providers to `mock` only in demo, test, or intentional local development. Review the
provider's current data-use and retention terms before processing confidential, regulated, or
personal information.

Document deletion removes the active stored file and associated application records through
the document API, but it cannot erase independent backups, provider-side data, external logs,
or previously exported copies. Canonical lifecycle deletion is a soft-deletion/audit mechanism
and may intentionally retain records. Define and test a retention policy before real user data
is accepted.

## Untrusted content

Uploaded documents and node text are untrusted input. The application validates supported file
formats, size and archive limits, uses opaque non-public storage keys with root-containment
checks, and instructs the model not to follow embedded prompt instructions. These controls do
not make arbitrary content risk-free. Keep extraction libraries patched, scan uploads where the
deployment risk requires it, render text without executing embedded content, and do not treat
model prompt boundaries as a complete security boundary.

## Dependency and release hygiene

- Install from the committed JavaScript lockfile with the repository's documented pnpm version.
- Python dependencies currently use bounded ranges rather than a resolved lock; regenerate the
  dependency/license audit for every release until reproducible locking is added.
- Run the canonical validation gate and dependency advisory checks before release.
- Preserve third-party license notices when distributing containers, binaries, or browser
  bundles. See `THIRD_PARTY_NOTICES.md`.

## Known release security findings

The July 21, 2026 Milestone 3.5 review found no committed live credential or generated runtime
artifact. Fresh production JavaScript and third-party Python advisory audits reported no known
vulnerabilities; the local editable application package is not a published PyPI distribution and
was excluded from the Python registry lookup. See `docs/MILESTONE_3_5_COMPLETION_REPORT.md` and
`docs/SECURITY_LICENSE_AUDIT.md` for scope and caveats.
