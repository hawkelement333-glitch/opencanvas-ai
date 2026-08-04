param(
    [Parameter(Mandatory = $true)]
    [string] $TargetResourceGroupName,

    [Parameter(Mandatory = $true)]
    [bool] $CleanupAuthorized
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ExecutionStartedAtUtc = [DateTimeOffset]::UtcNow

$ExactTargetResourceGroup = "rg-solarplexus-mobius-77-staging"
$ProtectedResourceGroups = @(
    "rg-solarplexus-mobius-73-staging",
    "rg-solarplexus-mobius-77-cleanup-control",
    "rg-solarplexus-mobius-77-containerapps-infrastructure"
)
$ExpectedSubscriptionFingerprint = "f4493115ce6375cf0e5d0616bede57126075fdb27ac78ea0ba7e0085252a7028"
$SubscriptionFingerprintDomain = "mobius.azure.subscription-context.v1"
$ExpectedCleanupPrincipalFingerprint = "19a9f97779cd2eb9acfdc04797f1fc5339316ee1a424ca79b70661beffa33260"
$CleanupPrincipalFingerprintDomain = "mobius.azure.cleanup-principal.v1"
$ExpectedRoleDefinitionId = "b24988ac-6180-42a0-ab88-20f7382dd24c"
$CleanupLaunchGrace = [TimeSpan]::FromMinutes(30)
$ScheduledCleanupAtUtc = [DateTimeOffset]::ParseExact(
    "2026-08-05T06:45:00Z",
    "yyyy-MM-ddTHH:mm:ssZ",
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal
).ToUniversalTime()
$LatestCleanupLaunchAtUtc = $ScheduledCleanupAtUtc.Add($CleanupLaunchGrace)

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
if (
    $ExecutionStartedAtUtc -lt $ScheduledCleanupAtUtc -or
    $ExecutionStartedAtUtc -gt $LatestCleanupLaunchAtUtc
) {
    Stop-Cleanup "outside-launch-window"
}

Disable-AzContextAutosave -Scope Process | Out-Null
$context = (Connect-AzAccount -Identity -ErrorAction Stop).Context
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
$context = Set-AzContext `
    -SubscriptionId $context.Subscription.Id `
    -DefaultProfile $context `
    -ErrorAction Stop

$targetScope = "/subscriptions/$($context.Subscription.Id)/resourceGroups/$ExactTargetResourceGroup"
$roleAssignmentsPath = (
    "$targetScope/providers/Microsoft.Authorization/roleAssignments" +
    "?api-version=2022-04-01&`$filter=atScope()"
)
$roleAssignmentsResponse = Invoke-AzRestMethod `
    -Method GET `
    -Path $roleAssignmentsPath `
    -DefaultProfile $context `
    -ErrorAction Stop
$roleAssignmentPayload = $roleAssignmentsResponse.Content | ConvertFrom-Json -Depth 16
if ($null -eq $roleAssignmentPayload -or $null -ne $roleAssignmentPayload.nextLink) {
    Stop-Cleanup "role-inventory-malformed"
}
$assignments = @()
foreach ($assignment in @($roleAssignmentPayload.value)) {
    $principalId = [string] $assignment.properties.principalId
    $roleDefinitionId = [string] $assignment.properties.roleDefinitionId
    $scope = [string] $assignment.properties.scope
    if (
        [string]::IsNullOrWhiteSpace($principalId) -or
        [string]::IsNullOrWhiteSpace($roleDefinitionId) -or
        [string]::IsNullOrWhiteSpace($scope)
    ) {
        Stop-Cleanup "role-inventory-malformed"
    }
    $principalBytes = [Text.Encoding]::UTF8.GetBytes(
        $CleanupPrincipalFingerprintDomain + [char]0 + $principalId.ToLowerInvariant()
    )
    $principalHasher = [Security.Cryptography.SHA256]::Create()
    try {
        $principalFingerprint = [Convert]::ToHexString(
            $principalHasher.ComputeHash($principalBytes)
        ).ToLowerInvariant()
    }
    finally {
        $principalHasher.Dispose()
        [Array]::Clear($principalBytes, 0, $principalBytes.Length)
    }
    if (
        $principalFingerprint -ceq $ExpectedCleanupPrincipalFingerprint -and
        $roleDefinitionId -match "/$ExpectedRoleDefinitionId$" -and
        $scope -ceq $targetScope
    ) {
        $assignments += $assignment
    }
}
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
