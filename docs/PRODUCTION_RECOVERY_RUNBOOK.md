# Production Backup, Restore, Rollback, and Disaster Recovery Runbook

Version: `mobius-production-recovery-runbook-v1`

Date: 2026-07-30

Status: exercised in an isolated managed environment; production execution
requires a separately approved incident or exercise authorization

## Universal recovery contract

1. Declare the incident or exercise, owner, approver, exact environment,
   protected-resource denylist, effect-lock state, recovery point, and stop
   conditions.
2. Preserve the current database, object versions, image digests, deployment
   configuration references, audit, Trace, event/outbox, activity, queue,
   index, and telemetry evidence before mutation.
3. Use a dedicated, time-bounded recovery scope and short-lived identities.
   Do not use an ordinary owner identity as the recovery executor.
4. Keep restore targets, credentials, object prefixes, queues, telemetry,
   email, webhooks, providers, and user access isolated.
5. Lock external effects before restore. Deny general Internet, OpenAI, SMTP,
   webhooks, public storage, external queues/providers, and public application
   traffic. Private management paths remain explicit and bounded.
6. Never print, export, or place secret values or private signing keys in a
   dump, manifest, log, command transcript, or evidence archive.
7. Validate schema, mappings, scope, authority, append-only evidence, object
   checksums, queue eligibility, indexes, and isolation before an authorized
   traffic or effect unlock.
8. Sign and checksum recovery evidence outside the database being recovered.
9. Revoke temporary access, prove post-revocation denial, delete restore
   targets, purge authorized soft-deleted test resources, and verify zero
   residue.
10. Record unknowns as unknowns. A portal total, delayed meter, missing log
    row, or measured exercise duration must not be presented as an exact
    workload cost or production SLO.

## Backup and recovery-point preparation

- Require managed continuous backup and point-in-time recovery.
- Produce periodic encrypted portable PostgreSQL backups for provider-exit
  recovery.
- Keep object versioning and retention aligned with the database recovery
  window.
- Record a manifest binding:
  - recovery-point timestamp;
  - database server and backup identity;
  - object-version inventory digest;
  - application image digest and package version;
  - Alembic head and migration-file hashes;
  - configuration and secret-reference versions, never secret values;
  - evidence encryption and signing key versions;
  - operator, approver, authorization, and effect-lock identities.
- Hash plaintext before encryption and ciphertext after encryption. Sign the
  canonical manifest through a non-exportable managed key and verify the
  signature before relying on the backup.
- Store the encrypted artifact, manifest, signature, and report in a
  separately protected immutable evidence destination.

## Point-in-time restore

1. Select an exact UTC recovery point inside the provider retention window.
2. Record the newest transaction that must be present and the first later
   marker that must be absent.
3. Create a private isolated restore target with public access disabled.
4. Maintain the outbound effect lock throughout provisioning and validation.
5. Wait for provider readiness without widening authority or network access.
6. Verify TLS, expected PostgreSQL version, Alembic head, mapper
   configuration, application imports, and package/image identities.
7. Verify the expected pre-target marker is present and post-target marker is
   absent.
8. Run the cross-resource and authorization validation below.
9. Record submission, ready-observed, and validation-complete timestamps. The
   resulting duration is an exercise upper bound, not a production SLO.

## Full managed restore

1. Restore the selected managed backup into a new private isolated target.
2. Do not overwrite or connect the restored target to the active environment.
3. Verify database identity, encryption, private DNS, TLS, server settings,
   schema head, mapper configuration, application import, and expected marker
   count.
4. Verify every database reference to a protected object version and checksum.
5. Run evidence, queue, index, scope, authorization, and effect-lock checks.
6. Record the same measured upper-bound timestamps as PITR.

## Portable encrypted recovery and failback

1. Export from a private source connection with a dedicated backup identity.
2. Exclude ownership transfer and secret values; preserve schema, data,
   constraints, and append-only evidence.
3. Hash plaintext, encrypt it with a versioned managed key, hash ciphertext,
   generate the canonical manifest, and sign the manifest.
4. At the destination, verify signature, key version, manifest digest,
   ciphertext digest, decryption, and plaintext digest before import.
5. Import into an empty isolated target inside one controlled transaction.
   Any failed import must leave zero partial application tables.
6. Verify the imported schema and expected recovery markers.
7. For failback, add a bounded recovery-region validation marker, create and
   verify a new encrypted portable artifact, and atomically import it into a
   fresh source-region target.
8. Never call the portable exercise a live traffic failover unless routing,
   clients, and effects were separately authorized and tested.

## Object, queue, index, and evidence reconciliation

After any database restore:

1. enumerate referenced canonical object versions and compare exact checksum,
   version, and lifecycle evidence;
2. quarantine missing or mismatched objects and block affected retrieval
   heads;
3. reconstruct durable-job eligibility from nonterminal authoritative jobs;
4. do not replay a delivery merely because a queue message existed;
5. preserve request, attempt, retry, lease-generation, cancellation,
   dead-letter, replay, result, and publication identities;
6. reproject derivable activity from authoritative domain events/outbox;
7. reconstruct indexes only from clean canonical source versions and recorded
   manifests;
8. create new operational reconstruction attempts without rewriting original
   index or publication history;
9. verify audit, Trace, domain-event, outbox, activity, approval, action,
   retry, failure, and result references remain connected to their authority
   and evidence.

## Shared-limit recovery

- Shared counters are operational state and may be rebuilt, but deployed
  protected operations must never fall back silently to process-local limits.
- Validate two independent clients, atomic Lua execution, namespace and tenant
  isolation, all configured dimensions, burst behavior, expiry/reset, and
  limiter epochs.
- A limit denial returns `429`.
- Authentication, TLS, connection, or limiter-service failure returns `503`
  for protected operations.
- The recovery fixture remains loopback/private, TLS verified,
  ACL-authenticated, nonpersistent, bounded, and disposable.

## Migration failure, application rollback, and forward fix

Prefer application rollback with additive schema compatibility:

1. stop new rollout and incompatible workers;
2. preserve the failure, migration, image, schema, and authority evidence;
3. redeploy the last known-good immutable image digest;
4. retain compatible additive schema changes;
5. if the schema is incompatible, restore the rehearsed pre-change point into
   isolation and validate it before a controlled switch.

Routine production Alembic downgrade is prohibited. Downgrade is limited to
disposable migration validation unless a separately reviewed recovery plan
authorizes otherwise.

A forward fix is permitted only when it preserves authority, immutable
history, tenant isolation, and availability more safely than restore. Record
the comparison, decision owner, approver, commands, artifact digests, tests,
result, and rollback boundary.

## Cross-resource validation gate

Before traffic or external effects may be unlocked, prove:

- expected Alembic sole head and immutable migration hashes;
- application import and SQLAlchemy mapper configuration;
- exact server-derived user, workspace, canvas, and resource scope;
- current membership, role, action authority, and approval authority;
- no cross-workspace object, workflow, agent, approval, grant, or invocation;
- append-only audit, Trace, domain-event, outbox, and activity integrity;
- source object version and checksum consistency;
- durable-job generation fencing and idempotent eligibility;
- index manifest and active publication consistency;
- private DNS, verified TLS, public-access denial, and the outbound effect
  lock;
- safe `429` and fail-closed `503` behavior;
- no secret, credential, private key, or private model reasoning in evidence.

An authorized recovery decision is required after the gate. Passing technical
checks alone does not grant traffic-switch or effect-unlock authority.

## Evidence, telemetry, and cost

- Evidence records contain safe resource identities, timestamps, hashes,
  versions, measurements, decisions, operators, and approvals—not credentials
  or private model chain of thought.
- Route diagnostic and metric data through private monitored paths.
- Confirm both metric and category-log arrival where required. If category
  logs are delayed beyond cleanup, record that limitation and revalidate at
  the next approved isolated exercise.
- Treat cost-budget alerts as warnings, not hard enforcement.
- Track posted usage, delayed usage, remaining runtime, cleanup, and an
  uncertainty contingency. Stop before out-of-pocket billing could occur.
- Never use a global portal cost as the exact recovery-run cost unless the
  scope and posting period prove that attribution.

## Revocation and cleanup

1. Stop application and worker activity.
2. Close any bounded bootstrap-egress exception.
3. Delete runtime files and temporary evidence copies.
4. Revoke uploader, builder, operator, and recovery identities at their exact
   scopes.
5. Prove management-plane assignment absence and data-plane denial for each
   former identity.
6. Delete restore targets and private endpoints in provider-supported order.
   If a stopped service blocks endpoint deletion, restart only the exact
   service needed for cleanup, remove the endpoint, and delete the service.
7. Delete the recovery resource group and verify it is absent.
8. Purge only an explicitly authorized soft-deleted recovery key vault or
   equivalent test resource; never widen purge scope.
9. Verify protected source and staging inventories are unchanged.
10. Verify temporary local files and SSH key paths are absent. Do not claim
    secure erasure.
11. Verify the evidence report and signature before deleting their temporary
    validation destination.
12. Record residue queries, revocation time, deletion completion, protected
    inventory, known telemetry/cost delays, and the final decision.

## Exercise frequency and revalidation triggers

Repeat the controlled exercise before production enablement or Milestone 7.8,
and after a material change to database provider/SKU/region, backup retention,
object lifecycle, image build, migration chain, signing/encryption key policy,
private network, authorization model, queue/index recovery, limiter adapter,
or observability destination.

Milestone 7.7 owns load, capacity, resilience, and infrastructure-security
limits. This runbook neither starts that checkpoint nor promotes measured
recovery exercise durations into SLOs.
