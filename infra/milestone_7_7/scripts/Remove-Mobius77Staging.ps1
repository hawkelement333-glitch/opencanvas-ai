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

if ($null -ne $target) {
    Remove-AzResourceGroup `
        -Name "rg-solarplexus-mobius-77-staging" `
        -Force | Out-Null
}

$residue = Get-AzResourceGroup `
    -Name "rg-solarplexus-mobius-77-staging" `
    -ErrorAction SilentlyContinue

if ($null -ne $residue) {
    throw "target-resource-group-residue"
}

[pscustomobject]@{
    status = "target-resource-group-absent"
    targetScopeMatched = $true
    secretValueAccessed = $false
} | ConvertTo-Json -Compress
