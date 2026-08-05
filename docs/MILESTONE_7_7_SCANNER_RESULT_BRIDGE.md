# Milestone 7.7 Scanner-Result Bridge

## Status

The local bridge contract is complete; live Azure proof is required. The gate
remains fail-closed and `scannerResultBridgeResolved` must not be set from a
manual Boolean. The failed cleanup state recorded in
`MILESTONE_7_7_CLEANUP_SCANNER_BRIDGE_HANDOFF.md` is preserved and is not a
bridge-validation environment.

## Selected path

- Provider: Microsoft Defender for Storage malware scanning.
- Producer: a Defender result for the exact quarantine blob version, ETag, and
  SHA-256 recorded by the secure-ingestion request.
- Transport: one Event Grid system topic and filtered event subscription that
  writes to the private `scanner-results` Storage Queue. `scanner-results-
  deadletter` retains bounded failed deliveries.
- Consumer: the internal scan worker's private queue adapter calls
  `MalwareScanService.record_bridge_result`; the existing HMAC callback remains
  a legacy internal endpoint and is not transport authentication.
- Promotion: only a clean verdict tied to the immutable version, ETag,
  request, correlation ID, provider result, and current policy can promote.
  Every other verdict remains rejected or quarantined.

## Security and operations

Event Grid receives only `Storage Queue Data Message Sender` on the exact
scanner queue. The scan worker receives only `Storage Queue Data Message
Processor` on the two exact queues. Both identities, role-definition IDs,
provider event fields, and private queue reachability require live validation;
no Owner, Contributor, shared key, anonymous sender, public endpoint, or
catalog-wide permission is allowed.

The storage queue uses a private endpoint and
`privatelink.queue.core.windows.net` private DNS linked to the existing VNet.
TLS 1.2 or later is mandatory. Delivery retries are bounded to eight attempts,
30 seconds per delivery, and 24 hours total before dead-lettering. Duplicate
messages are idempotent by provider-result and immutable object-version pair;
an event ID cannot replay a final decision.

## Resolver and evidence

`preflight.milestone_7_7.scanner_result_bridge.resolve_bridge` accepts only
sanitized SHA-256 identifiers and requires provider, resources, identity,
RBAC, private-path, producer, transport, consumer, schema, correlation, and
revocation proof within 24 hours. It produces `RESOLVED` only after a clean or
rejected decision has a deterministic evidence integrity hash. Any missing,
stale, malformed, unknown, or non-private proof fails closed.

Evidence links upload request, blob version/ETag, storage alias, event ID,
provider result ID, delivery attempt, consumer receipt, verdict, decision, and
final integrity. It stores no secret, token, complete resource ID, private IP,
or raw provider output.

## Future live validation

Before a separately approved Azure run: resolve Microsoft.Security and Event
Grid capability/API versions for the approved region; validate the exact
Defender event schema and event filter; provision only the declared settings,
topic, subscription, queues, identities, roles, private endpoint, DNS, and
diagnostics; use one synthetic object and assert correlation through a clean
or rejected result; prove duplicate and replay handling; revoke temporary
proof authority; delete every bridge resource and confirm zero residue.

Local emulation does not prove the live bridge. A new lifecycle must not start
until the failed cleanup is separately reconciled, the bridge evidence is live
proved, cost/time are re-approved, and the resolver emits `RESOLVED`.
