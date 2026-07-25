# Milestone 5.3 Graph-Aware Retrieval Handoff

Status: complete locally on 2026-07-25

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Starting SHA: `dcf9650cb0d7ed65d78127cd79931f1461c9af58`

Migration and sole Alembic head: `20260725_0018`

## Delivered authority boundary

Graph-aware retrieval extends the completed canonical graph, document
chunk/embedding retrieval, Trace, domain event, outbox, authentication, CSRF,
and safe serialization boundaries. It does not create a second graph, source,
citation, Trace, audit, or authority system.

The client supplies a bounded query, selected canonical object IDs, seed IDs
within that selection, and a scoped idempotency key. The server derives the
authenticated user, validates workspace/canvas ownership and canonical
bindings, captures graph revision and immutable versions, fixes traversal and
ranking contracts, derives citations/hashes/Trace/event/bundle identities, and
enforces all limits.

A relationship never authorizes a resource. Traversal records
`outside_selected_context` and does not visit an endpoint unless it is in the
explicit selected allowlist. Created and active canonical resources are
readable; archived/deleted/historical-only sources fail closed.

## Graph traversal and ranking

Registry and algorithm: `graph-retrieval-v1`.

Relationship semantics:

- forward: `references`, `derived_from`, `cites`, `supports`, `produced_by`,
  `affected_by`
- bidirectional: `related_to`, `contradicts`

Only the latest active relationship history participates. Inactive,
superseded, unsupported, out-of-selection, malformed, or scope-invalid
evidence is excluded with a closed reason. Cycles terminate through a visited
set. Stable ordering uses score descending, graph distance, canonical object
ID, and passage identity.

Server bounds:

- selected objects: 50
- seed objects: 50
- traversal depth: 3
- visited entities: 250
- considered relationships: 500
- candidate passages: 200
- returned passages/citations: 50
- serialized evidence text: 60,000 characters
- query: 4,000 characters
- bundle: 5 MiB and 100 members

Canonical notes use a deterministic lexical overlap score. Legacy-linked
canonical documents reuse the repository's existing versioned chunks,
embeddings, and deterministic mock provider. No external search, web
retrieval, vector database, paid provider, or silent embedding regeneration
was added.

## Outcomes and decisions

Outcomes are closed to:

- `supported`
- `conflicting_evidence`
- `insufficient_evidence`
- `bounded_result`

Every considered traversal or passage stores an append-only, closed inclusion
or exclusion reason, graph distance, optional relationship, deterministic
rank/score, and relationship path. Supported/conflicting results require at
least one exact citation. Insufficient evidence stores no false citation.
Contradictory paths remain visible and produce the conflict outcome.

## Exact citations and APA 7

Schema `graph-citation-v1` retains the server-derived citation ID, retrieval
ID, canonical object/version, immutable source version/hash, exact passage
identity, excerpt/hash, page/chunk/heading/character locator where supported,
relationship path, graph revision, ordinal, Trace, and optional applicable
audit linkage.

Citation verification occurs while resolving the immutable source. Missing
versions/content, scope mismatch, altered source state, malformed locators, or
unsupported types fail closed. Citation rows and retrieval evidence are
protected by ORM listeners and SQLite/PostgreSQL append-only triggers.

Renderer `apa7-repository-sources-v1` is presentation only. Repository source
metadata lacks verified author/date/publisher/URL fields, so the renderer:

- preserves and safely escapes the exact source title;
- uses title-first `n.d.` forms;
- labels internal notes and uploaded source types;
- includes a verified page locator when present;
- never invents an author, date, publisher, DOI, or URL;
- rejects unsupported source types; and
- maps every display string to its canonical citation ID.

Completed and failed rendering have real domain-event producers.

## Trace Evidence Bundle

Schema: `trace-evidence-bundle-v1`.

Canonical deterministic layout:

```text
trace-evidence-bundle.zip
├── README.md
├── manifest.json
├── trace-report.md
├── references.md
├── citations.json
├── excerpts/
│   └── source-NNN-excerpt.txt
└── integrity/
    └── sha256sums.txt
```

`authorized-sources/` is omitted because the current repository has no general
complete-source export-authority contract. A request for complete sources
fails closed, emits `evidence.bundle.export_denied`, and records
`export_not_authorized` without exposing a storage key or path.

ZIP names are fixed and safe; ordering, JSON serialization, UTF-8, LF line
endings, archive timestamps, permissions, compression, and checksums are
deterministic. The archive contains only exact cited excerpts and safe
metadata. SHA-256 covers each member except the checksum file itself. Bundle
bytes are bounded, verified, and stored as an opaque `LargeBinary` database
artifact in the same transaction as completed metadata and outbox events.
Managed object storage, signed URLs, retention, encryption, and streaming are
future production-hardening work.

## Events, Trace, and transactions

All eight 5.2 reserved contracts now have real 5.3 producers:

- `evidence.bundle.requested`
- `evidence.bundle.generation_started`
- `evidence.bundle.completed`
- `evidence.bundle.failed`
- `evidence.bundle.accessed`
- `evidence.bundle.export_denied`
- `citation.rendering.completed`
- `citation.rendering.failed`

Each uses exact authenticated scope, retrieval/bundle/citation identity,
Trace, safe payload, deterministic idempotency, and a transactional outbox.
No success event exists before verified artifact/citation completion.

Retrieval started Trace evidence is written before the mutation savepoint.
The immutable run, decisions, citations, successful Trace completion, and
applicable evidence commit atomically. Failure injection after run, decisions,
or citations rolls everything back; only truthful started/failed Trace
evidence remains.

The repository has no general human-operation audit table; its existing audit
records are authority-bound to controlled executions. Human retrieval
therefore uses authenticated scope, Trace, immutable evidence, and domain-event
provenance with nullable audit linkage rather than inventing a parallel audit
system. Future controlled workflow/agent callers must supply their applicable
Milestone 4 audit identity.

## APIs

Authenticated, exact-scope, allowlist-serialized routes support:

- starting one graph retrieval;
- reading one result, citations, and safe Trace summary;
- deterministic APA rendering;
- requesting and reading one evidence bundle;
- fail-closed complete-source export requests; and
- CSRF-protected bundle download with access-event evidence.

There is no public bundle route, arbitrary path, unbounded search, browser
outbox dispatcher, workflow trigger, or autonomous action.

## Validation

The affected backend suite passed 105 tests. The focused 5.3 plus affected
graph/event suite passed 39 tests. Coverage includes closed registries,
selected-context non-bypass, direction rules, supported and insufficient
outcomes, replay/conflict, exact hashes and locators, APA output, ZIP layout and
checksums, source-export denial, safe APIs, append-only evidence, transactional
failure injection, migration cycling, SQLite triggers, and PostgreSQL offline
DDL compilation.

Ruff passed. Strict mypy passed all 69 source files. Compilation, imports,
mapper configuration, sole-head and `0018 → 0017 → 0018` migration validation,
deterministic bundle verification, ZIP-path safety, secret/prohibited-scope
scans, documentation formatting, whitespace, repository hygiene, and Git
object integrity passed.

SQLite validates local constraints, triggers, deterministic ordering, and
transaction rollback. It does not prove PostgreSQL row locking, isolation,
deadlock behavior, query plans, or concurrent inserts. PostgreSQL runtime was
not configured; only offline DDL compilation is claimed. No external provider
or managed object-storage validation occurred.

## Preserved and deferred scope

Milestone 5.4–5.7 and future Milestones 6–9 remain deferred. No workflow
definition/execution, automatic trigger, adaptive agent, training, Academy,
English rewriting, quarantine, rehabilitation, tribunal, Agent Studio,
Dynamic Universe, federation, recurring job, external queue, or frontend code
was implemented.

All Adaptive Agent Architect, Adaptive Training and Evaluation Agent,
governed-improvement, Adaptive English Communication Expert, Evidence Bundle,
APA 7, SolarPlexus Academy, School of Language, Agent Justice, Quarantine
Center, Rehabilitation Center, and Review Tribunal requirements remain
unchanged authoritative future acceptance criteria.

Milestone 5 is not complete.

Next authorized checkpoint:
`MILESTONE 5.4 STARTED LOCALLY — CONTROLLED AI WORKFLOWS`
