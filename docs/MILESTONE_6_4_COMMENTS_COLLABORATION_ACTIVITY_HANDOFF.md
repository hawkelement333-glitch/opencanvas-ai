# Milestone 6.4 — Comments and Collaboration Activity Handoff

Date: 2026-07-26

Branch: `milestone-6-4-comments-collaboration-activity-local`

Starting commit: `0e4535f5b65eb0718dd1613902705569da7629f9`

Starting parent: `5d139c2a9e4a96279e94c863a63a138124dc0def`

Status: complete locally; ready for a separately authorized Milestone 6.5 run

## Completion boundary

This checkpoint implements only bounded comments and collaboration activity.
It does not add frontend components, collaboration administration, shared
workflow or agent governance, real-time delivery, presence, live cursors,
CRDT/OT state, offline merge behavior, Indexer work, Librarian work,
deployment, or release behavior.

Migration `20260725_0024` is the sole Alembic head. Its direct parent is
`20260725_0023`. Committed migrations `20260725_0021`, `20260725_0022`, and
`20260725_0023` were not modified, and no later migration was created.

## Persistence

Migration `20260725_0024` adds:

- `collaboration_comment_threads`;
- `collaboration_comment_thread_transitions`;
- `collaboration_comments`;
- `collaboration_comment_revisions`;
- `collaboration_comment_transitions`.

Every table binds exact workspace, typed resource, author or actor membership,
authority generation, request identity, Trace identity, audit identity, and
sequence information appropriate to the record. Composite foreign keys bind
threads, comments, revisions, parents, actors, authors, and resources to the
same server-owned scope.

Closed checks cover the four supported resource kinds; thread states
`open`, `resolved`, and `reopened`; comment states `active`, `edited`,
`hidden_by_moderation`, and `removed_by_author`; revision kinds `created` and
`edited`; positive generations and sequences; parent/depth shape; bounded
revision content; and tombstone visibility shape.

Indexes cover resource thread order, thread creator, thread state, comment
thread order, author, parent, revision history, revision author, current
comment state, and lifecycle time. SQLite and PostgreSQL guards enforce exact
thread/resource/canvas scope, same-thread parents, parent depth plus one,
terminal tombstoned parents, maximum thread count, revision successor shape,
visible-revision state, and thread lifecycle. All five identity/history tables
reject update and delete. Existing domain-event, request-identity, and audit
closed checks are extended without adding a second ledger.

Downgrade refuses destructive removal when append-only comment evidence
exists. An empty `0024` database downgrades to `0023` and re-upgrades to
`0024`. PostgreSQL offline DDL compiles the tables, functions, triggers, and
closed-check changes.

## Comment and thread contracts

`CommentService` supports canvases, canonical objects, workflow identities,
and agent identities. It derives user, membership, workspace, resource,
ownership/share visibility, permission, and authority generation on the
server.

Server-owned limits are:

- 5,000 Unicode code points per revision;
- four reply levels;
- 500 comments per thread;
- 30 comment creations per active membership per minute;
- page size 50 by default and 100 maximum.

Content is normalized to NFC with normalized newlines and stored as plain
text. Empty content, control characters, HTML, raw Markdown, embeds, unsafe
schemes, and plain HTTP links fail closed. Bare HTTPS URLs remain plain text
for safe client rendering.

A top-level create atomically creates one thread, open transition, comment,
first immutable revision, active transition, request identity, audit record,
Trace, domain event, provenance, and outbox record. Replies must name a
non-tombstoned parent in the exact same resource and thread. Stable
`thread_sequence` values provide deterministic ordering.

Only the active original author may revise a comment. Every edit supplies the
expected visible revision, creates exactly one successor revision and state
transition, and preserves all earlier content. Stale and concurrent writers
receive a safe conflict. Exact replay returns the original result without a
second revision or evidence record.

Author removal and authorized moderation append terminal tombstone
transitions. Ordinary output retains comment/thread structure and attribution
but returns no visible content or revision identity. Historical content
remains available only to the original author or a currently authorized
moderator. Tombstoned parents reject new replies; existing descendants remain
ordered and intact. Thread resolve/reopen changes only append-only thread
state and requires `comment.resolve`.

## Authority and revocation

The central collaboration evaluator now maps exact actions for create,
revision, author tombstone, moderation, thread resolution, and activity
listing. Viewer visibility permits safe comment listing but does not grant
comment creation or any write. Author identity and authority generation are
not accepted from request bodies.

Every operation checks the current active membership, role ceiling, workspace
lifecycle, typed-resource visibility, and authority generation. Write
operations capture the existing Milestone 6.3 revocation fence and revalidate
it before publication. Removed membership, revoked share, stale generation,
foreign workspace/resource, unsupported resource, and hidden-resource
substitution fail closed without revealing existence.

## Events, activity, Trace, and audit

The closed domain-event registry adds:

- `comment.created`;
- `comment.reply.created`;
- `comment.revised`;
- `comment.tombstoned`;
- `comment.thread.resolved`;
- `comment.thread.reopened`.

Comment and thread subject kinds are also closed. Event payloads contain only
bounded resource kind, state, revision sequence, reply depth, and reason-code
facts; comment text and private authority details are excluded. Event scope
requires the actor's latest membership transition to remain active.

`CollaborationActivityService` reads the existing delivered domain-event,
transactional-outbox, and `activity-v1` projection. It creates no activity
table, event bus, feed, or audit system. Reads require current collaboration
activity permission and re-evaluate exact current resource visibility for
every returned event. Resource and event filters, deterministic newest-first
ordering, offset pagination, and 50/100 page limits are supported. Replayed
outbox delivery retains one projection.

All meaningful transitions share one database transaction with comment state,
request identity, audit, Trace, event provenance, and outbox state. Focused
failure injection proves a post-mutation event failure leaves none of those
records behind.

## Backend APIs

- `GET /workspaces/{workspace_id}/resources/{resource_kind}/{resource_id}/comments`
- `POST /workspaces/{workspace_id}/resources/{resource_kind}/{resource_id}/comments`
- `GET /workspaces/{workspace_id}/comments/{comment_id}/revisions`
- `POST /workspaces/{workspace_id}/comments/{comment_id}/revisions`
- `POST /workspaces/{workspace_id}/comments/{comment_id}/moderate`
- `POST /workspaces/{workspace_id}/comment-threads/{thread_id}/resolve`
- `GET /workspaces/{workspace_id}/collaboration-activity`

Routes remain thin and use existing authentication, CSRF, safe error,
transaction, schema aliasing, and pagination conventions.

## Focused tests

`test_collaboration_comments.py` covers safe/unsafe content, exact author
binding, exact replay, simultaneous duplicate create, simultaneous edit
conflict, four-level replies, depth rejection, stale edit rejection, immutable
revision history, resolve/reopen, resolved-thread rejection, author tombstone,
moderator tombstone, viewer authority boundaries, tombstoned-content
non-disclosure, cross-workspace denial, removed-membership denial, activity
projection/filtering/pagination/no-sensitive-payload behavior, duplicate
projection protection, and atomic failure rollback.

`test_collaboration_6_4_migration.py` covers the sole direct head, migration
tables and guards, closed event registry, upgrade/downgrade/re-upgrade, and
PostgreSQL offline DDL. Established migration tests now recognize `0024` as
the sole current head while retaining historical direct-parent/range checks.

## Validation record

Final validation passed:

- full backend: 510 passed, 1 skipped PostgreSQL-only test, 0 failed, and 36
  existing deprecation warnings;
- explicit integration suite: 22 passed with 1 existing FastAPI deprecation
  warning;
- explicit security suite: 38 passed;
- focused comments/domain-events/6.4 migration suite: 17 passed;
- frontend unit suite: 15 files and 66 tests passed;
- Chromium smoke: 6 passed and 2 real-service scenarios skipped as designed;
- frontend ESLint and TypeScript: passed with zero warnings/errors;
- Next.js 16.2.10 production build: passed with all eight routes generated;
- repository Prettier check and Python formatting/lint: passed;
- strict mypy: 82 source files passed;
- ORM mapper validation: 121 tables passed;
- production import and Python compilation checks: passed;
- migration validator: upgrade to `0024`, downgrade to `0023`, and re-upgrade
  to `0024` passed;
- focused PostgreSQL offline DDL compilation: passed;
- local demo reset, persisted-provenance/isolation check, and API/runtime/web
  startup smoke: passed;
- repository hygiene: 341 source files passed;
- `git diff --check`, immutable-migration diff, prohibited-scope,
  dependency/lockfile, frontend-boundary, and protected-reference checks:
  passed;
- Git object integrity: passed.

The first full backend run exposed one stale registry-enumeration expectation,
not a product defect. It did not classify the new comment subjects with the
existing scoped collaboration subjects and therefore generated a synthetic
unscoped command. The expectation was corrected, the focused set passed, and
the final full backend rerun passed.

The top-level `pnpm` wrapper stopped at its documented ignored-build policy for
`sharp` and `unrs-resolver`. Dependency approval policy was not changed. Its
temporary suggested workspace-policy text was removed, and the locked
workspace executables were run directly for formatting, lint, type checking,
tests, production build, and Playwright. No dependency or lockfile changed.

## Handoff constraints

Milestone 6.5 remains unstarted. It requires a new explicit request and fresh
verification from the clean committed 6.4 SHA. Any later persistence uses the
next unused revision and does not rewrite `0021`–`0024`.

No remote operation, deployment, publication, or protected-reference mutation
is part of this checkpoint.
