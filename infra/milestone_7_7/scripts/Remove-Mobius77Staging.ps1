param(
    [Parameter(Mandatory = $true)]
    [string] $TargetResourceGroupName,

    [Parameter(Mandatory = $true)]
    [bool] $CleanupAuthorized
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ExactTargetResourceGroup = "rg-solarplexus-mobius-77-staging"
$ProtectedResourceGroups = @(
    "rg-solarplexus-mobius-73-staging",
    "rg-solarplexus-mobius-77-cleanup-control",
    "rg-solarplexus-mobius-77-containerapps-infrastructure"
)
$ExpectedSubscriptionFingerprint = "f4493115ce6375cf0e5d0616bede57126075fdb27ac78ea0ba7e0085252a7028"
$SubscriptionFingerprintDomain = "mobius.azure.subscription-context.v1"
$ExpectedRoleDefinitionId = "b24988ac-6180-42a0-ab88-20f7382dd24c"
$AuthorizedCleanupDeadlineUtc = [DateTimeOffset]::ParseExact(
    "2026-08-03T11:00:00Z",
    "yyyy-MM-ddTHH:mm:ssZ",
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal
).ToUniversalTime()

function Stop-Cleanup([string] $Reason) {
    throw "cleanup-contract-$Reason"
}

if ([string]::IsNullOrWhiteSpace($TargetResourceGroupName)) {
    Stop-Cleanup "target-missing"
}
if ($TargetResourceGroupName -cne $ExactTargetResourceGroup) {
    Stop-Cleanup "target-mismatch"
}
if ($ProtectedResourceGroups -ccontains $TargetResourceGroupName) {
    Stop-Cleanup "protected-target"
}
if ($CleanupAuthorized -ne $true) {
    Stop-Cleanup "authorization-denied"
}
if ([DateTimeOffset]::UtcNow -gt $AuthorizedCleanupDeadlineUtc) {
    Stop-Cleanup "deadline-expired"
}

Disable-AzContextAutosave -Scope Process | Out-Null
Connect-AzAccount -Identity -ErrorAction Stop | Out-Null
$context = Get-AzContext -ErrorAction Stop
if ($null -eq $context -or [string]::IsNullOrWhiteSpace($context.Subscription.Id)) {
    Stop-Cleanup "subscription-context-missing"
}

$fingerprintInput = [Text.Encoding]::UTF8.GetBytes(
    $SubscriptionFingerprintDomain + [char]0 + $context.Subscription.Id.ToLowerInvariant()
)
$hasher = [Security.Cryptography.SHA256]::Create()
try {
    $observedFingerprint = [Convert]::ToHexString(
        $hasher.ComputeHash($fingerprintInput)
    ).ToLowerInvariant()
}
finally {
    $hasher.Dispose()
    [Array]::Clear($fingerprintInput, 0, $fingerprintInput.Length)
}
if ($observedFingerprint -cne $ExpectedSubscriptionFingerprint) {
    Stop-Cleanup "subscription-mismatch"
}
Set-AzContext -SubscriptionId $context.Subscription.Id -ErrorAction Stop | Out-Null

$principalObjectId = $context.Account.Id
if ([string]::IsNullOrWhiteSpace($principalObjectId)) {
    Stop-Cleanup "identity-missing"
}
$targetScope = "/subscriptions/$($context.Subscription.Id)/resourceGroups/$ExactTargetResourceGroup"
$assignments = @(
    Get-AzRoleAssignment -ObjectId $principalObjectId -Scope $targetScope -ErrorAction Stop |
        Where-Object {
            $_.RoleDefinitionId -match "/$ExpectedRoleDefinitionId$" -and
            $_.Scope -ceq $targetScope
        }
)
if ($assignments.Count -ne 1) {
    Stop-Cleanup "role-scope-unproved"
}

$target = Get-AzResourceGroup -Name $ExactTargetResourceGroup -ErrorAction SilentlyContinue
if ($null -eq $target) {
    [pscustomobject]@{
        cleanupAuthorized = $true
        deletionResult = "ALREADY_ABSENT"
        secretValueAccessed = $false
        targetScopeMatched = $true
    } | ConvertTo-Json -Compress
    exit 0
}
if ($target.ResourceGroupName -cne $ExactTargetResourceGroup) {
    Stop-Cleanup "resource-name-mismatch"
}

$deleteJob = Remove-AzResourceGroup `
    -Name $ExactTargetResourceGroup `
    -Force `
    -AsJob `
    -ErrorAction Stop
try {
    $null = Wait-Job -Job $deleteJob -Timeout 2700
    if ($deleteJob.State -ne "Completed") {
        Stop-Cleanup "deletion-timeout"
    }
    Receive-Job -Job $deleteJob -ErrorAction Stop | Out-Null
}
finally {
    Remove-Job -Job $deleteJob -Force -ErrorAction SilentlyContinue
}

$absenceDeadline = [DateTimeOffset]::UtcNow.AddSeconds(300)
do {
    $remaining = Get-AzResourceGroup `
        -Name $ExactTargetResourceGroup `
        -ErrorAction SilentlyContinue
    if ($null -eq $remaining) {
        break
    }
    Start-Sleep -Seconds 5
} while ([DateTimeOffset]::UtcNow -lt $absenceDeadline)
if ($null -ne $remaining) {
    Stop-Cleanup "absence-unproved"
}

[pscustomobject]@{
    cleanupAuthorized = $true
    deletionResult = "DELETED"
    secretValueAccessed = $false
    targetScopeMatched = $true
} | ConvertTo-Json -Compress
