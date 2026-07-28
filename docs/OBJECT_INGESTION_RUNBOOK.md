# Secure Object Ingestion Operations Runbook

Date: 2026-07-28

Owner: production operations, with application security as the scanner and
policy escalation owner.

This runbook covers the Milestone 7.3 upload, quarantine, scan, promotion,
retention, deletion, and recovery boundary. It does not authorize deployment,
public access, a safety override, or Milestone 7.4 work.

## Invariant and normal lifecycle

No uploaded object may reach parsing, retrieval, models, downloads, or Indexer
publication unless the exact immutable bytes have a current policy-valid
`clean` result and a checksum-verified clean promotion.

The normal lifecycle is:

```text
initiated -> uploaded -> completed -> scan_pending
  -> clean -> promoted -> retained
  -> infected | suspicious | unsupported | error | timeout
```

Cancellation, expiry, deletion request, and supersession are terminal fences.
They cannot be reversed by a late scanner or worker result. Rescan creates a
new immutable request and result; it does not edit earlier evidence.

## Configuration and capacity

- Staging and production require `OPENCANVAS_STORAGE_PROVIDER=azure` and
  `OPENCANVAS_OBJECT_INGESTION_MODE=trusted`.
- Quarantine, clean, rejected, and retained containers must be distinct,
  private, versioned, encrypted, and inaccessible by anonymous or shared-key
  access.
- Workload identity is the only deployed storage credential path.
- Upload capabilities are one-time, quarantine-only, and expire within
  60–900 seconds; the default is 300 seconds.
- The default file limit is 25 MiB and the request-body limit is 30 MiB.
- The default active-session limit is 10 per workspace.
- The default scanner callback limit is 120 requests per minute.
- The default scan deadline is 300 seconds and clean evidence expires after
  86,400 seconds.
- PDF input is limited by page count and active/encrypted content checks.
- DOCX input is limited by members, expanded bytes, compression ratio,
  macros, ActiveX, embedded content, and external relationships.
- Generic archives are unsupported.

Never log upload capabilities, scanner signatures, physical keys, provider
tokens, original filenames, document contents, or private provider errors.

## Readiness and kill switch

Readiness requires valid deployed configuration and access to the exact private
storage containers through the workload identity. Scanner unavailability,
unknown policy/scanner versions, stale evidence, or storage failure must keep
objects quarantined.

To disable new secure ingestion, set `OPENCANVAS_OBJECT_INGESTION_MODE=disabled`
and restart the affected service. This is a fail-closed kill switch: secure
upload endpoints reject work and existing objects do not become readable.
Never enable legacy upload or `private_legacy` Indexer publication in staging
or production as a fallback.

## Incident procedures

### Malware, suspicious, unsupported, or malformed content

1. Confirm the immutable object version, ETag, SHA-256, scan request, policy
   version, and scanner identity/version.
2. Keep the object in quarantine. Do not download it through the application.
3. Verify that no clean promotion, parsing, retrieval, model use, download, or
   publication exists.
4. Preserve immutable lifecycle, scan, Trace, audit, and domain-event evidence.
5. Escalate infected or suspicious results to application security.
6. Apply the approved retention/deletion policy; never delete using a
   client-supplied physical key.

### Scanner outage, timeout, missing, forged, or conflicting result

1. Keep all affected objects quarantined and the clean-object gate closed.
2. Check scanner identity/version, HMAC signature, callback rate, timestamps,
   request deadline, policy version, object version, ETag, size, and SHA-256.
3. Reject late, replayed, contradictory, malformed, or mismatched results.
4. Create a new bounded rescan request only after the dependency is healthy.
5. Do not manually mark an object clean.

### Checksum or provider-version mismatch

1. Stop promotion immediately.
2. Compare the provider immutable version, ETag, byte size, stored SHA-256, and
   database binding.
3. Mark the attempt as a safe terminal failure and retain the source in
   quarantine.
4. Investigate object substitution, provider inconsistency, and key or
   workload-identity compromise.
5. Do not retry under the same immutable identity when bytes conflict.

### Storage outage or ambiguous database/object commit

1. Keep readiness degraded and do not bypass the clean gate.
2. Reconcile by opaque object and immutable version identity.
3. Treat a provider version as existing only when its exact size and SHA-256
   match the durable record.
4. Retry idempotently; never create a second promotion for the same source and
   policy-valid result.
5. Record orphans for reviewed cleanup. Do not infer safety from object
   location or a mutable tag.

### Expired, abandoned, or orphaned upload

1. Run bounded reconciliation for sessions past their deadline and scan
   requests past their deadline.
2. Append the expiry/error transition; do not rewrite earlier lifecycle rows.
3. Verify that the object remains outside clean and is unavailable to all
   protected consumers.
4. Delete the exact immutable provider version only under the approved
   retention policy and record the deletion request/evidence.

### Key, capability, or scanner-secret compromise

1. Disable secure ingestion.
2. Revoke the affected workload identity or rotate the affected server-only
   secret.
3. Cancel or expire every outstanding capability/request issued under the
   compromised generation.
4. Treat results signed under the compromised scanner secret as untrusted and
   require a new scan under the new identity/version/policy.
5. Audit for cross-scope access, unexpected versions, duplicate promotions,
   and clean reads.
6. Restore service only after focused clean/unsafe/forgery/stale-result tests
   and provider readiness checks pass.

## Retention, deletion, recovery, and backup

Relational evidence is append-only. Provider object deletion is a separate,
reviewed operation against the exact stored physical key and immutable version.
A deletion request blocks clean reads before provider cleanup. Backups must
preserve relational evidence and the corresponding provider versions at a
consistent recovery point.

After restore, verify exact workspace/canvas/document scope, lifecycle head,
scan request/result, policy/scanner versions, promotion source and target,
ETag, byte size, and SHA-256 before allowing protected consumers. A restored
legacy or incomplete object remains `legacy_unscanned` or quarantined.

## Evidence and revalidation

Record the commit, environment, storage/scanner versions, validation time,
operator, exact immutable identities, results, limitations, and cleanup.
Revalidate after storage-account policy, container, workload identity, scanner,
signature secret, malware policy, upload limit, format validator, promotion,
migration, or protected-consumer changes.

Managed staging evidence currently proves the harmless and EICAR paths through
matching Log Analytics records. Direct human blob-tag reads are unavailable by
least-privilege design and are not an authorization path.
