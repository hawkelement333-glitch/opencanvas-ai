# Trace and answer provenance

OpenCanvas Trace answers “what operation happened, to which object, under which workspace, and with what outcome?” Structured AI execution evidence answers “what exact context and retrieval result produced this answer?” The two are related but not interchangeable.

## Trace event model

Each append-only event records:

- `eventId` and `traceId`;
- optional `parentTraceId`;
- actor type and optional actor ID;
- optional workspace ID;
- optional logical object type and ID;
- event type and operation;
- `started`, `succeeded`, or `failed` status;
- safe structured metadata;
- structured error code/message for failures;
- occurrence timestamp.

Trace identifiers are logical associations rather than foreign keys to lifecycle-deletable records. This preserves provenance even if the current object is later hidden or removed.

## Trace lifecycle

Canonical services record a start event before significant mutations. A successful domain mutation and succeeded event share the same savepoint/transaction boundary. A rejected or storage-failed mutation rolls back its domain savepoint before the API commits a structured failed event.

Trace persistence failure is not ignored: the canonical mutation fails rather than creating untraced state.

## Read API

Base path: `/api/v1`.

```http
GET /traces/{traceId}
GET /trace-events?traceId=&parentTraceId=&workspaceId=&objectId=&eventType=&actorType=&status=&limit=
```

Results are chronological by occurrence time and event ID. These endpoints are read-only. Because authentication is not implemented, they must not be exposed to an untrusted network.

## AI execution evidence

An AI request persists structured fields instead of relying on one rendered prompt string:

| Evidence       | Stored detail                                                                                                         |
| -------------- | --------------------------------------------------------------------------------------------------------------------- |
| Request        | Execution ID, exact instruction, provider/model, configuration snapshot, prompt version, status/error, timestamps.    |
| Selected nodes | Order, node ID/type/revision, title/content snapshots, referenced document.                                           |
| Retrieval      | Document/chunk IDs, rank, score, inclusion decision, exclusion reason, stable source ID, location and text snapshots. |
| Response       | Generated text, provider response ID, grounding and insufficient-evidence flags, token usage when available.          |
| Citations      | Validated citation sequence, claim, excerpt, source IDs, page/heading/offset snapshots.                               |
| Source graph   | Immutable response/source-node association snapshots and live graph relationships where present.                      |

Deleting live source or canvas records removes current references as required while preserving the immutable execution evidence designed for later audit.

## Citation integrity

The server constructs the source ID allow-list from retrieved chunks. Provider output is rejected if it cites an unknown source. A response cannot claim grounding without at least one valid citation, and an insufficient-evidence response cannot carry citations.

Editing an AI-response node invalidates its live grounding presentation because changed prose is no longer the original cited answer. Historical execution output and citation snapshots remain separate evidence.

## Trace is not logging

Application logs support operations and diagnostics. Trace is product provenance with stable schemas, IDs, workspace/object correlation, and query semantics. Prompts and source bodies are not copied into every Trace event; detailed AI context belongs in execution records.

## Trace is not domain-event delivery

Canonical domain events notify replaceable in-process subscribers. Subscribers are failure-isolated and do not provide durable delivery. Trace remains queryable persistence. External side effects eventually require a transactional outbox.

## Current inspection workflow

1. Obtain a `traceId` from a canonical mutation response or known execution association.
2. Query `/api/v1/traces/{traceId}`.
3. Use `/api/v1/trace-events` to pivot by workspace, object, parent trace, type, actor, or status.
4. For an AI answer, inspect its structured request/response/execution records through controlled diagnostic access.
5. Verify displayed citations by opening their public source-passage endpoint.

There is no complete end-user Trace explorer, comparison, replay, export, or evaluation UI in this release.

## Deferred Trace work

- authenticated Trace views and redaction policy;
- retention and deletion governance;
- execution replay and side-by-side comparison;
- visual claim/evidence graphs;
- automatic inference and source-conflict classification;
- transactional outbox for durable external event delivery;
- workspace-wide retrieval Trace integrated with the canonical graph.
