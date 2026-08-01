param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("rg-solarplexus-mobius-77-staging")]
    [string] $TargetResourceGroupName
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ($TargetResourceGroupName -cne "rg-solarplexus-mobius-77-staging") {
    throw "target-scope-mismatch"
}

Disable-AzContextAutosave -Scope Process | Out-Null
Connect-AzAccount -Identity | Out-Null

$target = Get-AzResourceGroup `
    -Name "rg-solarplexus-mobius-77-staging" `
    -ErrorAction SilentlyContinue

[pscustomobject]@{
    status = "PAUSED_PRESERVED"
    reason = "CLEANUP_TIMER_EXPIRED"
    cleanupAuthorized = $false
    targetResourceGroupPresent = ($null -ne $target)
    targetScopeMatched = $true
    secretValueAccessed = $false
} | ConvertTo-Json -Compress
