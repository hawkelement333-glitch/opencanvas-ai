# Milestone 7.6 Backup, Restore, Rollback, and Disaster Recovery Handoff

Date: 2026-07-30

Status: complete locally; Stage 3 decision `DEPLOYMENT VALIDATED`; Milestone
7.7 remains blocked and unstarted

## Checkpoint

- Checkpoint: 7.6 — Backup, Restore, Rollback, and Disaster Recovery
- Branch: `milestone-7-6-recovery-adapter`
- Starting parent: `acca3020f2fa177f325dc124faf0afecec59f044`
- Recovery-adapter commit:
  `01e2bba692760bfb90c04689ce0e5c7589bf87e9`
- Deployment-image hardening commit:
  `cde72589ad0f3d6d8aa364c56ffed6af2a825a70`
- Completion commit: this handoff's local completion commit; the exact SHA is
  reported after commit creation
- Commit message: `Complete Milestone 7.6 production recovery`
- Sole Alembic head: `20260726_0028`
- Migration `0028` Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Migration `20260726_0029`: absent
- Upstream: none

No application migration was required. Stage 3 used only synthetic recovery
data in an isolated Azure recovery environment. The environment and its
temporary access were removed after evidence verification; the protected
Milestone 7.3 Azure inventory remained unchanged.

## Completed recovery boundary

The checkpoint proves the architecture's recovery boundary without claiming
an in-place production restore:

- managed PostgreSQL full restore and point-in-time restore into isolated
  targets;
- encrypted portable PostgreSQL export, signed manifest, and atomic import;
- recovery-region restore followed by a portable failback exercise;
- exact source archive, application image, schema, object-version, checksum,
  evidence-key-version, and recovery-time bindings;
- private TLS-only service access and a closed outbound-effect lock;
- isolated identities, role revocation, data-plane denial, and zero-residue
  cleanup;
- append-only event, outbox, Trace, audit, and activity integrity checks;
- durable-job eligibility and shared-limit behavior after recovery;
- application import, mapper, package, and Alembic-head validation;
- rollback and forward-fix decision criteria recorded in the recovery
  runbook.

Tenant-level point-in-time rewind is not claimed. Shared relational history,
append-only evidence, graph, workflow, agent, collaboration, and object
references still require isolated restore plus bounded forward repair.

## Source, image, and limiter evidence

| Evidence                         | Verified value                                                            |
| -------------------------------- | ------------------------------------------------------------------------- |
| Source archive size              | `3483333` bytes                                                           |
| Source archive SHA-256           | `64784063d0e80cf2dc44fa8a1b1397b1f263c19f8cf7a558bc4d348ceaf4c5db`        |
| Source archive blob version      | `2026-07-30T01:48:59.0545611Z`                                            |
| Source archive ETag              | `0x8DEEDDCB94C0ACB`                                                       |
| Private application image digest | `sha256:f0cdfaeadfeb21324c0d1342b0a1339279bb98185ce532533b67936d62d6b2dd` |
| Application package version      | `0.1.0`                                                                   |
| Valkey source image digest       | `sha256:4a5b313584744da28b845cdfde59e0d14f07529a6e72cd3a915bf384d4fab0f4` |
| Private Valkey image digest      | `sha256:484de83902e10e37c0466bdd74d695e7cf4cbd382605b4386907b274a3b4d121` |
| Database integrity digest        | `eb0535d8bee2dc52ee5917938cac97623fa73790ed648b06043cfcbe5249d6d4`        |

The built application image passed package installation, application imports,
SQLAlchemy mapper configuration, and sole-head `20260726_0028` checks.

The recovery-only Valkey fixture was loopback-bound, TLS verified,
ACL-authenticated, and nonpersistent. Two independent clients made 100
concurrent attempts: 25 were allowed and no update was lost. All seven
network, user, workspace, resource, operation, provider, and global
dimensions; Lua atomicity; namespace isolation; burst behavior; TTL,
expiration, and reset; and limiter epoch behavior passed. Limit denial
returned `429`. Authentication failure and connection outage returned `503`
with no process-local fallback.

## Recovery exercise measurements

The baseline was captured at `2026-07-30T02:51:07.574191Z`; the
post-recovery-point marker was committed at `2026-07-30T02:52:24.707716Z`.
The database fixture contained eight synthetic records and four append-only
domain events.

| Exercise                        | Submit/target                                                   | Ready observed                | Validation upper bound | Measured exercise RTO upper bound | Result |
| ------------------------------- | --------------------------------------------------------------- | ----------------------------- | ---------------------- | --------------------------------- | ------ |
| Point-in-time restore           | target `2026-07-30T02:51:30Z`; submitted `2026-07-30T02:58:09Z` | `2026-07-30T03:18:16Z`        | `2026-07-30T03:21:41Z` | `1412` seconds (`23m32s`)         | PASS   |
| Full managed restore            | submitted `2026-07-30T03:22:59Z`                                | `2026-07-30T03:29:47Z`        | `2026-07-30T03:35:58Z` | `779` seconds (`12m59s`)          | PASS   |
| Portable recovery-region import | submitted `2026-07-30T03:37:57.476977Z`                         | `2026-07-30T03:42:21.508368Z` | `2026-07-30T03:54:46Z` | `1009` seconds (`16m49s`)         | PASS   |
| Portable failback               | submitted `2026-07-30T03:56:56.761531Z`                         | `2026-07-30T04:01:19.920019Z` | `2026-07-30T04:05:27Z` | `511` seconds (`8m31s`)           | PASS   |

These values are measured upper bounds for this one controlled exercise. They
are not production recovery SLOs, contractual commitments, capacity evidence,
or a substitute for Milestone 7.7 measurements.

For PITR, the selected recovery point was 54.707716 seconds before the
post-recovery-point marker. The marker's absence was expected and verified;
schema, authorization, append-only evidence, and integrity checks passed. The
full restore retained both baseline markers. The failback added the
`recovery-region-validated` marker and retained all three expected markers.

## Portable backup, signing, and atomicity evidence

| Evidence                              | SHA-256 or immutable version                                       |
| ------------------------------------- | ------------------------------------------------------------------ |
| Recovery-region plaintext export      | `e65a456a6bd3dbd3b927669b5700f36735dc5f210e3cc3efef7a0914f180bd5a` |
| Recovery-region ciphertext            | `a64602d99948dab4025623278f560bc122664e41254db57e893786376ac37217` |
| Recovery-region manifest              | `288dedcb735f8477718e9441d53d07fc6c15b49b76e21d65aa3b2188fd6afd33` |
| Recovery-region portable blob version | `2026-07-30T02:57:09.6486214Z`                                     |
| Failback plaintext export             | `42329140b63446d7f034e31a96f306736cc008360d08d93faa8895931d375829` |
| Failback ciphertext                   | `c24ceb515b3c558c67ad5689015186f99b1b8e047c874d247aa3d85c84f8485b` |
| Failback manifest                     | `36fafb15d04bc76f214895d16c80f8031613695bdf350be12009b47de8fd0bc2` |
| Failback artifact blob version        | `2026-07-30T03:54:46.2359817Z`                                     |
| Final signed report                   | `976b0b7e611f59c488e76ba04d054ddf8696f3910db22778318bd5439a0997b1` |
| Final report blob version             | `2026-07-30T04:41:57.6811303Z`                                     |
| Final signature blob version          | `2026-07-30T04:41:57.7498308Z`                                     |
| Evidence signing-key version          | `64cfe248d14544b4ba9b8b030b0d8cbe`                                 |

Encryption, key-version binding, manifest HMAC, signature, ciphertext hash,
and restored plaintext hash were verified without exporting a key or secret
value. An intentionally failed initial portable import left zero partial
tables. The successful import committed atomically and retained the two
expected markers. The final signed report and signature were verified before
the recovery environment and its key were deleted.

## Security and network evidence

- Storage, registry, key vault, PostgreSQL, and Azure Monitor resolved through
  private DNS and negotiated verified TLS.
- Azure Monitor Private Link Scope was private-only.
- Public Storage, queue, OpenAI, external provider, webhook, SMTP, and public
  application paths were denied by the final effect-lock test.
- The workload VM and private services had no public application endpoint.
- Temporary uploader access was revoked; subsequent list, upload, read,
  overwrite, and delete attempts were denied.
- Temporary builder access was revoked; subsequent Storage access returned
  `403` and registry access returned `401`.
- The final nine recovery-scope role assignments were revoked; the final
  recovery-scope role-assignment query returned an empty set.

One concrete Azure-only defect was found and corrected during the exercise.
The workload NSG's `AllowVnetOutbound` rule used the `VirtualNetwork` service
tag, which expanded across the default route through the firewall and
therefore matched a public OpenAI destination. The Azure rule was narrowed to
the exact recovery VNet CIDR `10.76.0.0/16`. Network Watcher then returned
`DenyInternetOutbound`, and the complete denial test passed. This was an
Azure-only network-policy correction; no repository code, migration, or
infrastructure-as-code file changed.

## Observability and cost limitations

Diagnostic routing was configured privately for Firewall, PostgreSQL, Blob,
registry, key vault, and VM signals. Private metrics were confirmed for
Compute, PostgreSQL, Key Vault, and Firewall through approximately
`2026-07-30T04:38Z`.

Category-log rows had not arrived in `AzureDiagnostics` before mandatory
cleanup. The missing rows are recorded as a propagation limitation, not as a
pass and not as evidence loss inside the application. Revalidate category-log
arrival, alert queries, and retention against the next approved isolated
environment before production enablement or Milestone 7.8.

The exact posted Stage 3 cost is unknown. Azure Cost Management returned
`429`, and provider usage posting was delayed. The portal's displayed `$0.08`
was the overall subscription cost and included earlier unrelated usage; it is
not substituted for the Stage 3 cost. The run remained inside the approved
conservative `$75` envelope, but final posted Stage 3 attribution must be
reconciled when Azure makes it available.

## Results and decision

All controlled Stage 3 results numbered 14 through 24 passed. The final
decision is:

`DEPLOYMENT VALIDATED`

This means the isolated recovery exercise validated the approved deployment
and recovery contract. It does not certify a production deployment, public
release, production SLO, legal retention policy, tenant-level rewind, or
Milestone 7.7 capacity and resilience boundary.

## Cleanup and protected state

Application workloads were stopped and runtime files removed before resource
deletion. A provider-ordering issue initially prevented private-endpoint
deletion while PostgreSQL was stopped. The database was restarted only for
cleanup, the exact private endpoint was deleted, and PostgreSQL was then
deleted. This was a cleanup-only provider-ordering correction.

Final cleanup evidence:

- the isolated recovery resource group was absent by
  `2026-07-30T05:03:50Z`;
- the exact soft-deleted recovery key vault was purged and no matching
  deleted vault remained;
- all temporary recovery identities, nine role assignments, private
  endpoints, DNS, network, compute, database, cache, registry, storage,
  evidence objects, and runtime files were removed;
- 53 local temporary files totaling approximately 3.66 MB were removed;
- no temporary SSH private or public key file remained;
- the protected Milestone 7.3 Azure inventory remained exactly three
  resources: its storage account, Log Analytics workspace, and Event Grid
  topic.

Local protected-state audit before this completion commit:

- `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`;
- `competition-demo-v1` tag object:
  `acbde89b6e2cc3e41c372887794726d393836716`;
- `competition-demo-v1` peeled commit:
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`;
- five stash objects preserved:
  `9196c8d9f68c1af6251530f349fdf72638b57b82`,
  `58ffed44184ea3450a80f5883681da988a196ae7`,
  `d50c7020f9b9ce6add83f10d0b443510ccd33ba3`,
  `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`, and
  `71b384404468fbfa6326a951ef063e99c9e11652`;
- all eight external PostgreSQL recovery patch/manifest artifacts retained
  their recorded byte sizes and SHA-256 hashes;
- no stash was applied, popped, dropped, cleared, or rewritten;
- no migration was created or edited;
- no Git remote was contacted.

The protected Milestone 7.3 backend record remains one broad run of 619
passes and 34 failures followed by focused corrections and passing affected
suites. It is not rewritten as “653 passed.”

## Local completion audit

The documentation-only completion audit verified:

- exact starting branch `milestone-7-6-recovery-adapter` and HEAD
  `cde72589ad0f3d6d8aa364c56ffed6af2a825a70`;
- clean starting tree and no configured upstream;
- only the three authoritative Milestone 7 status documents, this handoff,
  and the recovery runbook changed;
- no application, test, migration, dependency, infrastructure, or Milestone
  7.7 file changed;
- Prettier formatting passed for all five changed Markdown files;
- `git diff --check`, trailing-whitespace, local-link, and secret-pattern
  checks passed with zero findings;
- Alembic reported the sole head `20260726_0028`;
- migration `0028` retained Git blob
  `55c203e669cace5be64fc25cdcf0eb8c05519198`;
- migration `0029` remained absent;
- `main`, `competition-demo-v1`, all five stash object identities, and all
  eight external recovery-artifact byte sizes and SHA-256 hashes matched their
  protected records.

No backend, frontend, deployment, or Azure validation was repeated during the
completion-documents-only audit. The already completed Stage 3 evidence is
the exercise record; this local run verified its accurate documentation and
the repository boundary.

## Restart boundary

Milestone 7.6 is complete locally only after this documentation commit is
created and the tree is clean. The authoritative restart boundary is that
completion commit on `milestone-7-6-recovery-adapter`, with sole Alembic head
`20260726_0028`, migration `0029` absent, no upstream, five stashes and eight
recovery artifacts preserved, and Milestone 7.7 blocked and unstarted.
