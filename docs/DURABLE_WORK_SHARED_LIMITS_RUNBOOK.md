# Durable Work and Shared Limits Runbook

Status: Milestone 7.4 local operating contract

This runbook covers the PostgreSQL durable document queue and the shared
rate-limit dependency. It does not authorize production access, direct table
edits, provider-key fallback, replay without current authority, or disabling
evidence controls.

## Permanent safety rules

- PostgreSQL job state is authoritative; a delivery or worker claim is not.
- Never edit append-only attempts, deliveries, retry decisions, outcomes,
  dead letters, replay requests, audit records, Trace, or domain events.
- Never force a success, clean verdict, result link, or publication link.
- A worker that loses its lease, cancellation generation, authority
  generation, source version, or deadline must discard its work.
- Replay requires current workspace-settings authority, a closed reason, and
  a new request/job identity.
- Staging and production must use the shared Redis adapter. Store uncertainty
  fails protected requests with `503`; there is no process-local fallback.
- Do not put Redis tokens, raw IP addresses, private identifiers, payloads,
  source text, or HMAC secrets in logs, metrics, tickets, or evidence.

## Observe before acting

Use authorized, redacted telemetry and safe APIs to establish:

- queue depth and oldest queued age;
- claim rate and latency;
- current worker-heartbeat age;
- lease loss, recovery, retry, cancellation, deadline, dead-letter, replay,
  and stale-result-suppression counts;
- limiter health, latency, denials, saturation, `429`, and `503`;
- database, private DNS/TLS, managed-identity, and Redis health;
- the exact deployment and code/schema versions.

Do not diagnose from a browser-controlled lease field or raw Redis keys.

## Queue backlog or one-workspace starvation

1. Confirm database readiness and at least one fresh worker heartbeat.
2. Separate unavailable work from rate-limited, future-eligible, canceled,
   expired, revoked, and dead-lettered work.
3. Check the oldest age, workspace concurrency, global concurrency, and
   priority distribution.
4. Restore healthy workers or reduce admitted load using existing
   server-owned limits.
5. Do not raise concurrency until database, storage, scanner, embedding, and
   limiter capacity are verified.
6. Confirm the backlog drains fairly and no workspace exceeds its bound.

## Lost worker, lease loss, or stale worker

1. Treat an expired heartbeat as unavailable, not as proof the process died.
2. Let the recovery reconciler fence the expired lease and create one
   recovery delivery when attempts and deadline permit.
3. Verify the lease generation advances.
4. Verify the recovered worker cannot commit any result or evidence.
5. If the final attempt expired, verify one dead letter and no further
   delivery.
6. Do not delete or rewrite the prior running-attempt evidence.

## Graceful or forced shutdown

For graceful shutdown, stop new claims, allow bounded active work to finish,
record the worker as stopping, and terminate before the platform deadline.
For forced shutdown, restart capacity and let lease expiry/recovery reconcile
the abandoned claim. Never reuse a previous process's worker identity.

## Retry storm

1. Group by closed safe failure classification, never payload content.
2. Confirm exponential ceilings, full jitter, maximum attempts, and job
   deadlines remain unchanged.
3. Stabilize the failing dependency or reduce admitted work.
4. Do not bulk replay while the cause persists.
5. Verify attempts transition to one terminal dead letter when bounds expire.

## Poison job and dead letter

1. Confirm the terminal classification and immutable dead-letter identity.
2. Preserve the source object and malware gate; do not mark unsafe bytes clean.
3. Correct only the external dependency or policy defect that caused the
   failure.
4. Use the authorized redacted dead-letter list. Provider payloads and worker
   lease details are not operator API output.

## Replay

1. Require an active authorized operator and current workspace authority.
2. Choose one closed reason: `operator_retry`, `dependency_recovered`, or
   `policy_corrected`.
3. Supply a new idempotency identity.
4. Verify a new request, job run, delivery, Trace, audit, domain event, and
   replay record reference the original dead letter.
5. Verify duplicate submission returns the same new job and contradictory
   reuse fails.
6. Never replay indefinitely; normal attempt and deadline bounds apply.

## Cancellation or deadline

Cancellation increments the server-owned cancellation generation and clears
the lease. Deadline reconciliation also advances fencing generations and
records one terminal outcome. Confirm the prior worker cannot publish or add
material evidence. Do not revive the same job identity.

## Limiter saturation

1. Confirm `429` is backed by an authoritative Redis decision and has a
   bounded `Retry-After`.
2. Identify only the safe operation and opaque dimension class.
3. Check sustained versus burst consumption and the global emergency ceiling.
4. Reduce admitted load or wait for refill/expiry.
5. A limit change is a reviewed configuration change; there is no client
   bypass header.

## Limiter outage, authentication, or private-connectivity failure

1. Expect readiness degradation and `503` for protected operations.
2. Verify private DNS, TLS validation, managed-identity token acquisition,
   restricted Redis ACL, and bounded connection/operation timeout.
3. Do not add a password to the URL, enable access keys/public networking, or
   switch deployed modes to memory.
4. Restore the dependency, then prove health and one bounded synthetic
   decision without exposing keys.
5. Redis counters are ephemeral; do not attempt to reconstruct them from
   application business data.

## Safe disablement and recovery

If a protected capability must be paused, disable its admission or worker
deployment through the approved operational change process while leaving
durable state intact. Do not bypass rate limits or mutate queue evidence.
Recovery requires healthy dependencies, exact schema compatibility, fresh
workers, current authority, and a bounded observation window.

## Escalation and evidence

Escalate immediately for cross-workspace evidence, duplicate terminal
outcomes, mutation of append-only records, stale-worker publication, missing
Trace/audit/domain-event material evidence, unbounded retry/replay, exposed
credentials, or production local-limit fallback. Preserve redacted metrics,
correlation identities, configuration versions, schema head, and the exact
authorized remediation. Milestone 7.5 owns external telemetry, alerts, and
dashboard wiring.
