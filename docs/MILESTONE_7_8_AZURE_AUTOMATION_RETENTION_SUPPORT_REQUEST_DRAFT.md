# Draft: Azure Automation retained-account removal or quota relief

**DRAFT ONLY — NOT SUBMITTED**

## Request

Please permanently remove, or provide appropriate Automation-account quota
relief for, exactly one soft-deleted Azure Automation account attributable to a
bounded Milestone 7.8 evidence campaign. Do not restore the account and do not
modify any unrelated active or deleted Automation account.

## Sanitized case binding

- Campaign correlation: `07e350df451c6bec`
- Generation correlation: `599df8555c0781d9`
- Azure region: `southeastasia`
- Campaign deleted-account identity SHA-256:
  `9ddbb427b37f677c6c2fe9b649278e1aedf9e6e00a250cfe7c24df0df475ce4d`
- Provider deletion evidence: `2026-08-14T20:09:46Z`
- Expected 30-day removal boundary: `2026-09-13T20:09:46Z` (expectation,
  not proof)
- Active inventory: complete, one page, zero accounts
- Deleted inventory: complete, one page, five accounts total; one exact
  campaign match and four unrelated records

The exact raw subscription, tenant, account name, resource ID, and private
runtime are intentionally omitted from this tracked draft. The authorized
operator can supply the exact account mapping from the preserved ignored runtime
through an approved secure support channel if the request is later authorized.

## Requested provider action and proof

1. Confirm whether Microsoft can permanently remove this exact retained record
   before automatic expiry or exempt it from Automation regional quota.
2. Bind any action only to the exact resource identity supplied through the
   secure case channel.
3. Do not restore the account as an intermediate step.
4. Do not modify the four unrelated deleted accounts.
5. Return a case record identifying the supported operation and completion
   time without exposing credentials.

After provider action, the operator will independently and completely paginate
both active and deleted Automation inventories. Cleanup will remain nonzero
until that readback proves the exact account absent and the unrelated identity
hash set unchanged.

## Repository evidence available

- `evidence/milestone_7_8/automation-retention-cleanup-remediation.json`
- `docs/MILESTONE_7_8_CRITICAL_CLEANUP_RETENTION_REMEDIATION_HANDOFF.md`

Actual campaign cost is unavailable because the one authorized cost query
returned HTTP 429 and was not retried. No permanent-delete API call was made:
current Automation provider metadata exposed deleted-account read only, and the
documented REST surface supplies list/read rather than permanent deletion.
