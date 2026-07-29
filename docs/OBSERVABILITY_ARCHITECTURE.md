# Operational Observability Architecture

Status: Milestone 7.5 local implementation

Schema: `mobius-operational-v1`

Signal catalog: `mobius-signals-v1`

Objective catalog: `mobius-internal-slos-v1`

## Boundary

`OperationalTelemetry` is the single provider-neutral operational telemetry
boundary. HTTP, worker, limiter, provider, storage, scanner, Indexer, durable
work, domain-event, and outbox boundaries may submit validated signals to it.
Domain logic does not call a vendor exporter directly.

Operational telemetry is non-authoritative. It does not replace, mutate, or
repair:

- product Trace;
- audit evidence;
- collaboration activity;
- domain events or their outbox;
- durable job attempts, results, or dead letters.

A valid business transaction remains committed when operational export fails.
Mandatory audit, product Trace, domain-event, outbox, or security evidence
remains inside the protected application transaction; failure to commit that
evidence still fails the transaction.

No Milestone 7.5 product table or migration exists. Operational data belongs
in bounded external destinations. Product-facing mitigation continues through
existing authorization, audit, event, activity, and Trace contracts.

## Signal path

```text
existing service boundary
  -> closed event/span/metric schema
  -> allowlist, redaction, bounds, pseudonymization
  -> bounded in-memory batch
  -> provider-neutral HTTPS exporter
  -> isolated operational destination
```

The buffer has a configured finite size. Export attempts, timeouts, retries,
batches, shutdown flush, span depth, attributes, events, baggage, metric
series, and field sizes are bounded. There is no disk spool and no production
fallback to an in-process no-op or process-local telemetry authority.

Development and test may explicitly select the in-memory sink. Staging and
production require enabled HTTP export, verified HTTPS, an environment-backed
authentication secret reference, a distinct pseudonymization secret, explicit
release/deployment identities, and an operator identity allowlist. Missing
authentication material fails application or worker startup.

## Structured logs

Application and security log records contain:

- closed event name and schema version;
- server timestamp and severity;
- runtime mode, service, component, release, and deployment;
- bounded operational trace and span correlation;
- allowlisted operation, route template, outcome, failure, count, size,
  duration, and status fields;
- opaque HMAC correlations where an entity link is operationally necessary.

Unknown event names, components, or field names are rejected. User-controlled
field names cannot reach the exporter. Control characters are removed and
bounded string values are escaped by structured serialization.

The source and exporter boundary exclude or redact passwords, tokens,
authorization, cookies, sessions, credentials, connection strings, signed
queries, storage keys, physical paths, queue payloads, receipt handles,
managed-identity headers, invitation/grant/approval/recovery tokens, raw IP
addresses, email addresses, filenames, private identifiers, source text,
document/note/canvas content, prompts, responses, provider payloads, SQL
parameters, raw exception text, and chain-of-thought.

## Metrics and cardinality

[signals-v1.json](observability/signals-v1.json) is the versioned signal
catalog. Each signal declares purpose, type, unit, aggregation, labels,
cardinality boundary, owner, objective, dashboard, and runbook. Histograms use
explicit bounds.

Metric submission requires the exact allowlisted label set. Unknown bounded
values normalize only to an explicit `other`; unknown labels, negative or
non-finite values, unknown signal names, and series beyond the smaller of the
signal and runtime cardinality budgets are rejected and counted. Raw user,
workspace, canvas, document, resource, request, job, network, URL, object,
prompt, or provider identifiers are prohibited labels.

The catalog covers API, database, object storage, scanner/quarantine, durable
queue/workers, shared limiter, deterministic Indexer, providers, events and
outbox, evidence integrity, backup freshness prerequisites, cost, capacity,
and exporter health. Backup freshness is explicitly a prerequisite signal;
it is not Milestone 7.6 restoration proof.

## Operational tracing and correlation

Operational spans use W3C-compatible `traceparent` formatting, closed span
names, deterministic sampling, bounded attributes/events/links, and explicit
async span links. Public client request identifiers are never trusted as
server correlation. Each request receives a server-derived request ID and an
environment/deployment-scoped HMAC operational correlation.

Asynchronous job, delivery, attempt, worker, execution, event, and outbox
boundaries use opaque scoped correlations or span links. The HMAC input binds
environment, deployment, correlation kind, scope, and identity. The same raw
identity in another workspace, canvas, environment, or deployment cannot be
joined through the exported value.

Allowed baggage is restricted to `operation` and `component` by default.
Prompts, responses, private data, credentials, authority material, and raw
resource identities cannot be baggage or span attributes.

Product Trace identity may be represented only by a scoped opaque operational
correlation. Operational spans never update Trace rows and Trace never depends
on exporter success.

## Dashboards, objectives, and alerts

- [dashboards-v1.json](observability/dashboards-v1.json) contains bounded
  internal dashboard manifests.
- [slos-v1.json](observability/slos-v1.json) contains internal SLIs and
  conservative provisional objectives.
- [alerts-v1.json](observability/alerts-v1.json) contains exact signals,
  queries, thresholds, evaluation windows, firing and recovery rules,
  missing-data policy, severity, grouping, ownership, objective, and runbook.

The objectives are not measurements, public SLAs, or contractual commitments.
They expire for review at the first approved staging telemetry campaign, any
material topology/signal change, or Milestone 7.7 capacity evidence.

Dashboard queries use fixed windows of five minutes through 24 hours. They
contain no tenant dimensions, distinguish missing data from healthy zero, and
declare units and aggregation. Alerts group only by alert identity and
environment or deployment. State transitions notify once on fire and once on
recovery, preventing per-series alert storms.

## Health and operational controls

Public liveness reports only process liveness and service name. It performs no
dependency call. Public readiness performs bounded database, schema, storage,
limiter, worker, and telemetry checks, then returns only `ready` or a generic
`service_not_ready`. Public worker health returns no deployment topology,
version, provider, credential, or internal identifier.

`GET /api/v1/health/operator` uses existing authenticated principals plus a
server-owned operator-user allowlist. An unlisted user receives the same
not-found response regardless of topology. The operator response contains
only closed dependency states, release/deployment identity, expected schema
revision, and bounded buffer/drop/rejection counts.

Sustained exporter failure changes telemetry health from `degraded` to
`unavailable`; production readiness then fails. Disablement is allowed only by
server configuration and is rejected in staging/production. A mitigation that
changes product state must use the existing authorization, audit, event, and
product Trace path.

## Integrity monitoring

Integrity snapshots classify:

- audit sequence gaps;
- product Trace parent gaps;
- event/outbox orphans;
- evidence-link orphans;
- impossible lifecycle transitions;
- stale backlog;
- duplicate durable identities;
- detected append-only mutation;
- telemetry gaps or exporter loss.

The monitor returns closed findings and emits a bounded signal. It cannot
rewrite, repair, replay, delete, or forge evidence. Investigation and any
authorized repair remain separate privileged operations.

## Privacy, retention, access, and deletion

Operational fields are confidential operational data. Security logs and
incident evidence may be restricted further. Access belongs to the named
platform-operations owner and incident commander through the destination's
least-privilege read roles. Application and worker identities receive only
export authority.

Default maximum retention:

| Class             | Days |
| ----------------- | ---: |
| Application logs  |   30 |
| Security logs     |   90 |
| Metrics           |   30 |
| Operational spans |   14 |
| Incident evidence |  365 |

Runtime settings may shorten these limits within their validated ranges.
Operational pseudonyms are not a product user export and cannot be reversed.
Deletion follows destination retention and approved incident/legal holds.
Product deletion never relies on telemetry deletion. Environment destinations,
keys, secret references, dashboards, and operator access must remain isolated.

This system does not implement product analytics, advertising analytics,
behavior profiling, session replay, user surveillance, or prompt/source
capture.

## Destination evidence

No approved isolated telemetry destination or credential was available during
the local Milestone 7.5 implementation. The in-memory sink and synthetic
bounded HTTP-exporter contracts were validated locally. No live exporter,
Azure Monitor, Log Analytics, application-to-Azure, deployment, retention,
dashboard rendering, or alert-delivery claim is made.

Before production enablement or Milestone 7.8, revalidate the exact release
candidate against an approved isolated destination, including authentication,
TLS, batching, timeout, retry, loss/readiness behavior, retention, role
revocation, dashboard queries, alert delivery/recovery, and cleanup.
