# Observability and Incident Operations Runbook

Version: `mobius-observability-runbook-v1`

Owner: platform operations

Primary escalation: incident commander

Security escalation: security owner

Privacy escalation: privacy owner

## Universal response contract

1. Confirm the environment, deployment, release, alert ID, safe correlation,
   first observation, and current closed dependency state.
2. Never paste raw logs, payloads, prompts, source text, tokens, identifiers,
   URLs, filenames, SQL parameters, or provider responses into tickets.
3. Declare an incident for a critical integrity, isolation, malware-gate,
   authorization, or evidence-continuity finding.
4. Freeze nonessential product mutation when continued operation could broaden
   impact. Use only server-owned kill switches.
5. Product-state mitigation requires existing authorization, audit, event,
   activity, and product Trace evidence.
6. Operational monitors do not repair, replay, delete, or forge evidence.
7. Capture signal versions, dashboard windows, alert transitions, safe
   correlations, decisions, owners, and timestamps.
8. Verify recovery through the alert's recovery rule and dependency readiness.
9. Record limitations, evidence expiration, follow-up owner, and review.

## API degradation

Use `service-overview-v1`. Confirm readiness separately from liveness, latency,
error rate, saturation, database acquisition, limiter decisions, and provider
status. Shed optional work and retain protected `429`/`503` behavior. Never
disable authentication, authority, scanner, shared limits, or mandatory
evidence. Recover after three ready probes and the alert recovery window.

## Database saturation or outage

Use `database-v1`. Confirm pool acquisition, timeouts, lock waits, transaction
outcomes, schema compatibility, and the dedicated runtime role. Stop new
expensive work before connection exhaustion. Do not increase pools beyond the
server budget or run ad hoc SQL from application credentials. Escalate
deadlocks, failover, or evidence-transaction failures immediately.

## Storage outage

Use `object-storage-v1`. Keep upload, retrieval, and Indexer publication
fail-closed. Do not substitute local or public storage. Confirm only safe
operation/failure classes. Preserve immutable object/version/checksum evidence
inside the product transaction.

## Scanner outage

Use `scanner-quarantine-v1`. Keep all unverified objects quarantined and block
parsing, retrieval, models, downloads, promotion, and Indexer publication.
Never treat missing, unavailable, pending, or ambiguous results as clean.
Escalate any malware-gate bypass as critical.

## Queue backlog, retry storm, or dead-letter growth

Use `durable-work-v1`. Compare depth, oldest age, claim latency, lease loss,
retry classifications, poison/dead-letter growth, cancellation, deadlines,
and stale-result suppression. Do not manually mutate attempts. Replay requires
current authority, an explicit reason, idempotency, audit, event, and Trace
evidence.

## Lost or stale worker

Confirm heartbeat freshness and lease generation. Stop the stale instance if
authorized; never extend or forge its lease. Recovery must fence the stale
worker before claim and commit. Confirm a replacement claims with a new
attempt and the stale result remains suppressed.

## Limiter saturation or outage

Use `shared-limiter-v1`. Protected operations remain `429` when denied and
`503` when authoritative shared state is unavailable. Never switch production
to process-local limits. An emergency ceiling is server owned, bounded, and
audited. Confirm atomic shared decisions before recovery.

## Indexer backlog, drift, or freshness failure

Use `indexer-v1`. Stop publication for drift, dirty sources, source changes,
lease loss, cancellation, or manifest mismatch. Rebuild only through the
deterministic staged Indexer contract. Never edit published revision evidence.

## Provider degradation or cost spike

Use `providers-v1` and `cost-capacity-v1`. Apply server-owned provider and cost
ceilings. Do not silently substitute a model/provider or weaken evidence,
privacy, authority, latency, or output limits. Capture only safe outcome,
latency, usage, and cost units.

## Domain-event or outbox backlog

Use `events-outbox-v1`. Inspect backlog age, attempts, terminal classifications,
and integrity. Do not mark an undelivered event complete. Recovery uses the
existing idempotent outbox delivery contract and lease fencing.

## Audit or product Trace integrity alert

Use `evidence-integrity-v1`. Declare a critical incident for sequence gaps,
unexpected mutation, duplicate durable identities, or event/outbox orphans.
Preserve database and operational evidence. The monitor must not repair.
Privileged investigation or remediation requires existing authority and
append-only evidence.

## Telemetry exporter outage, backpressure, or cardinality breach

Use `telemetry-pipeline-v1`. Confirm bounded buffer usage, rejected/dropped
signals, timeouts, retries, and last successful export. Do not dump buffered
payloads, add a disk spool, expand cardinality, or silently enable a no-op
exporter. Production readiness remains false after the configured sustained
failure threshold. Restore verified TLS/authentication and confirm three
successful exports with an empty buffer.

## Alert storm

Confirm alert grouping is only `alertId` plus environment or deployment.
Suppress repeated notification, not the underlying signal. Do not group or
route by tenant or raw resource identity. Correct the query or cardinality
source through reviewed configuration, then prove both firing and recovery.

## Liveness or readiness failure

Liveness proves only event-loop service. If liveness fails, restart through the
deployment controller. If readiness alone fails, use authorized operator
health to identify only the closed dependency class. Never expose operator
detail publicly.

## Backup freshness alert

Treat the Milestone 7.5 signal as a recovery prerequisite only. Do not claim a
valid backup or restoration. Keep the alert open until provider evidence is
fresh; Milestone 7.6 owns restore, rollback, and disaster-recovery proof.

## Capacity exhaustion

Use `cost-capacity-v1`. Stop optional intake before the server-owned threshold.
Do not raise database, buffer, retry, concurrency, token, storage, provider, or
cost limits without review. Milestone 7.7 owns measured capacity and soak
evidence.

## Incident declaration, evidence, recovery, and review

An incident record contains:

- incident ID and severity;
- environment, deployment, release, and signal schema versions;
- alert ID and bounded query window;
- first/last observation and firing/recovery timestamps;
- safe correlation values and closed failure classes;
- affected capability without tenant enumeration;
- commander, operations, security, privacy, and product owners as applicable;
- authorized mitigation, authority/evidence references, and rollback;
- confirmed recovery rule;
- remaining risk and evidence-expiration trigger;
- review date and action owners.

Incident records never contain raw telemetry payloads or private content.
Sensitive operational evidence uses the approved incident destination and
retention policy. Critical/high incidents cannot be waived permanently.

## Safe observability disablement and recovery

Production cannot start with telemetry disabled, a memory/no-op sink,
unverified transport, missing authentication secret reference, placeholder
release/deployment identity, or an empty operator allowlist. If telemetry
itself risks disclosure, stop export through an authorized server-owned
configuration change, declare an incident, preserve mandatory product
evidence, and keep production readiness false. Rotate affected credentials and
pseudonymization material where approved, validate redaction with synthetic
data, restore the bounded exporter, prove firing/recovery, and reapprove
readiness.
