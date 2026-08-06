# Milestone 7.7 cleanup Automation recovery

`aa-mobius77-cleanup` is retained as evidence of the Azure Automation
job-schedule namespace defect. Its generation-1 and generation-2 binding IDs
remain tombstoned: direct lookup and inventory are absent while recreation
conflicts. It is never an admission candidate and must not be modified.

The sole active cleanup-control account is
`aa-mobius77-cleanup-recovery` in the existing cleanup-control resource group.
It has a fresh deterministic binding namespace, a system-assigned identity,
and only the existing cleanup role at the exact staging-group scope. Admission
requires exactly one enabled one-time schedule, one binding, the committed
runbook, `TargetResourceGroupName=rg-solarplexus-mobius-77-staging`, and
`CleanupAuthorized=true`.

The replacement must be proven executable before any remaining lifecycle work.
The corrupted account is preserved until that proof succeeds.
