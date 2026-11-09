param(
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-z][a-z0-9-]{7,47}$')][string]$CampaignId,
  [Parameter(Mandatory = $true)][ValidatePattern('^g[1-9][0-9]{0,5}-[a-f0-9]{12}$')][string]$GenerationId,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{16}$')][string]$SubscriptionCorrelation,
  [Parameter(Mandatory = $true)][ValidatePattern('^rg-m78-[a-f0-9]{10}-target$')][string]$TargetResourceGroupName,
  [Parameter(Mandatory = $true)][ValidatePattern('^rg-m78-controller-[a-f0-9]{10}$')][string]$ControllerResourceGroupName,
  [Parameter(Mandatory = $true)][ValidatePattern('^aa-m78-controller-[a-f0-9]{10}$')][string]$AutomationAccountName,
  [Parameter(Mandatory = $true)][ValidateSet('Remove-M78Campaign')][string]$CleanupRunbookName,
  [Parameter(Mandatory = $true)][ValidatePattern('^m78-deadline-[a-f0-9]{10}$')][string]$CleanupScheduleName,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9-]{36}$')][string]$CleanupBindingName,
  [Parameter(Mandatory = $true)][ValidatePattern('^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')][string]$CleanupDeadlineUtc,
  [Parameter(Mandatory = $true)][ValidatePattern('^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')][string]$CleanupAuthorityExpiresUtc,
  [Parameter(Mandatory = $true)][ValidateRange(5000, 5000)][int]$CostCeilingCents,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$ControllerBindingSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$FreshControllerAdmissionEvidenceSha256,
  [Parameter(Mandatory = $true)][ValidateSet('m7.8-fresh-subscription-predeployment-absence-evidence-v1')][string]$FreshControllerAdmissionEvidenceVersion,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$CleanupAuthoritySha256,
  [Parameter(Mandatory = $true)][ValidateSet('true')][string]$CleanupAuthorized
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256([string]$Value) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
  }
  finally { $sha.Dispose() }
}

function Get-Correlation([string]$Domain, [string]$Value) {
  return (Get-Sha256 "m7.8/$Domain`0$Value").Substring(0, 16)
}

function Get-ArmJson([string]$Path) {
  $response = Invoke-AzRestMethod -Path $Path -Method GET
  if ([string]::IsNullOrWhiteSpace($response.Content)) { throw 'cleanup-readback-empty' }
  return $response.Content | ConvertFrom-Json -Depth 32
}

function Get-ExecutingPrincipalId {
  $accessToken = Get-AzAccessToken -ResourceUrl 'https://management.azure.com/'
  $tokenValue = $null
  if ($accessToken.Token -is [System.Security.SecureString]) {
    $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($accessToken.Token)
    try { $tokenValue = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
  }
  else { $tokenValue = [string]$accessToken.Token }
  $parts = $tokenValue.Split('.')
  if ($parts.Count -ne 3) { throw 'cleanup-identity-token-malformed' }
  $payload = $parts[1].Replace('-', '+').Replace('_', '/')
  switch ($payload.Length % 4) {
    0 { }
    2 { $payload += '==' }
    3 { $payload += '=' }
    default { throw 'cleanup-identity-token-malformed' }
  }
  $claims = [System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String($payload)
  ) | ConvertFrom-Json
  if ([string]$claims.oid -notmatch '^[0-9a-fA-F-]{36}$') {
    throw 'cleanup-identity-token-oid-missing'
  }
  return [string]$claims.oid
}

if ($CleanupAuthorized -ne 'true' -or $TargetResourceGroupName -eq $ControllerResourceGroupName) {
  throw 'cleanup-binding-invalid'
}
$parsedDeadline = [DateTimeOffset]::ParseExact(
  $CleanupDeadlineUtc,
  'yyyy-MM-ddTHH:mm:ssZ',
  [System.Globalization.CultureInfo]::InvariantCulture,
  [System.Globalization.DateTimeStyles]::AssumeUniversal
)
$parsedExpiry = [DateTimeOffset]::ParseExact(
  $CleanupAuthorityExpiresUtc,
  'yyyy-MM-ddTHH:mm:ssZ',
  [System.Globalization.CultureInfo]::InvariantCulture,
  [System.Globalization.DateTimeStyles]::AssumeUniversal
)
if (
  $parsedDeadline.Offset -ne [TimeSpan]::Zero -or
  $parsedExpiry.Offset -ne [TimeSpan]::Zero -or
  $parsedExpiry -ne $parsedDeadline.AddHours(1) -or
  [DateTimeOffset]::UtcNow -gt $parsedExpiry
) { throw 'cleanup-authority-expired-or-invalid' }

$authorityValues = @(
  'reusable-automation-controller-v1',
  $CampaignId,
  $GenerationId,
  $SubscriptionCorrelation,
  $TargetResourceGroupName,
  $ControllerResourceGroupName,
  $AutomationAccountName,
  $CleanupRunbookName,
  $CleanupScheduleName,
  $CleanupBindingName,
  $CleanupDeadlineUtc,
  $CleanupAuthorityExpiresUtc,
  [string]$CostCeilingCents,
  $ControllerBindingSha256
  $FreshControllerAdmissionEvidenceSha256
  $FreshControllerAdmissionEvidenceVersion
)
$observedAuthoritySha256 = Get-Sha256 ("m7.8/cleanup-authority/v4`0" + ($authorityValues -join "`0"))
if ($observedAuthoritySha256 -ne $CleanupAuthoritySha256) {
  throw 'cleanup-authority-hash-mismatch'
}

Connect-AzAccount -Identity | Out-Null
$context = Get-AzContext
if ((Get-Correlation 'subscription' $context.Subscription.Id) -ne $SubscriptionCorrelation) {
  throw 'cleanup-subscription-correlation-mismatch'
}

$controllerGroup = Get-AzResourceGroup -Name $ControllerResourceGroupName
$controllerTags = @{
  'mobius.milestone' = '7.8'
  'mobius.owner' = 'managed-postgresql-evidence'
  'mobius.cleanup-controller' = 'reusable-automation-controller-v1'
  'mobius.subscription-correlation' = $SubscriptionCorrelation
  'mobius.fresh-controller-admission-sha256' = $FreshControllerAdmissionEvidenceSha256
  'mobius.fresh-controller-admission-version' = $FreshControllerAdmissionEvidenceVersion
}
foreach ($key in $controllerTags.Keys) {
  if ($controllerGroup.Tags[$key] -ne $controllerTags[$key]) {
    throw 'cleanup-controller-ownership-mismatch'
  }
}
$controllerAuthorizedUntil = [DateTimeOffset]::Parse($controllerGroup.Tags['mobius.controller-authorized-until-utc'])
if ($controllerAuthorizedUntil -lt $parsedExpiry) { throw 'cleanup-controller-authority-expired' }

$automationBase = "/subscriptions/$($context.Subscription.Id)/resourceGroups/$ControllerResourceGroupName/providers/Microsoft.Automation/automationAccounts/$AutomationAccountName"
$account = Get-ArmJson "$automationBase`?api-version=2024-10-23"
$runbook = Get-ArmJson "$automationBase/runbooks/$CleanupRunbookName`?api-version=2024-10-23"
$schedule = Get-ArmJson "$automationBase/schedules/$CleanupScheduleName`?api-version=2024-10-23"
$binding = Get-ArmJson "$automationBase/jobSchedules/$CleanupBindingName`?api-version=2024-10-23"

$controllerRunbookId = "$automationBase/runbooks/$CleanupRunbookName".ToLowerInvariant()
$observedControllerBinding = Get-Sha256 "m7.8/reusable-cleanup-controller/v1`0$controllerRunbookId"
foreach ($key in $controllerTags.Keys) {
  if ($account.tags.$key -ne $controllerTags[$key]) {
    throw 'cleanup-controller-account-ownership-mismatch'
  }
}
$expectedBindingParameters = @{
  CampaignId = $CampaignId
  GenerationId = $GenerationId
  SubscriptionCorrelation = $SubscriptionCorrelation
  TargetResourceGroupName = $TargetResourceGroupName
  ControllerResourceGroupName = $ControllerResourceGroupName
  AutomationAccountName = $AutomationAccountName
  CleanupRunbookName = $CleanupRunbookName
  CleanupScheduleName = $CleanupScheduleName
  CleanupBindingName = $CleanupBindingName
  CleanupDeadlineUtc = $CleanupDeadlineUtc
  CleanupAuthorityExpiresUtc = $CleanupAuthorityExpiresUtc
  CostCeilingCents = [string]$CostCeilingCents
  ControllerBindingSha256 = $ControllerBindingSha256
  FreshControllerAdmissionEvidenceSha256 = $FreshControllerAdmissionEvidenceSha256
  FreshControllerAdmissionEvidenceVersion = $FreshControllerAdmissionEvidenceVersion
  CleanupAuthoritySha256 = $CleanupAuthoritySha256
  CleanupAuthorized = $CleanupAuthorized
}
foreach ($key in $expectedBindingParameters.Keys) {
  if ([string]$binding.properties.parameters.$key -ne $expectedBindingParameters[$key]) {
    throw 'cleanup-binding-parameter-mismatch'
  }
}
if (@($binding.properties.parameters.PSObject.Properties.Name).Count -ne $expectedBindingParameters.Count) {
  throw 'cleanup-binding-parameter-set-mismatch'
}
if (
  $observedControllerBinding -ne $ControllerBindingSha256 -or
  $account.name -ne $AutomationAccountName -or
  $runbook.name -ne $CleanupRunbookName -or
  $runbook.properties.state -ne 'Published' -or
  $schedule.name -ne $CleanupScheduleName -or
  $schedule.properties.frequency -ne 'OneTime' -or
  $schedule.properties.isEnabled -ne $true -or
  [DateTimeOffset]::Parse($schedule.properties.startTime) -ne $parsedDeadline -or
  $binding.name -ne $CleanupBindingName -or
  $binding.properties.runbook.name -ne $CleanupRunbookName -or
  $binding.properties.schedule.name -ne $CleanupScheduleName
) { throw 'cleanup-controller-readback-mismatch' }

$principalId = [string]$account.identity.principalId
if (
  [string]::IsNullOrWhiteSpace($principalId) -or
  (Get-ExecutingPrincipalId).ToLowerInvariant() -ne $principalId.ToLowerInvariant()
) {
  throw 'cleanup-controller-identity-mismatch'
}
$controllerScope = "/subscriptions/$($context.Subscription.Id)/resourceGroups/$ControllerResourceGroupName"
$controllerAssignments = @(
  Get-AzRoleAssignment -Scope $controllerScope |
    Where-Object { $_.ObjectId -eq $principalId }
)
if (
  $controllerAssignments.Count -ne 1 -or
  $controllerAssignments[0].RoleDefinitionId -ne 'acdd72a7-3385-48ef-bd42-f606fba81ae7' -or
  $controllerAssignments[0].Scope.ToLowerInvariant() -ne $controllerScope.ToLowerInvariant()
) { throw 'cleanup-controller-reader-authority-mismatch' }
$targetGroup = Get-AzResourceGroup -Name $TargetResourceGroupName
$requiredTags = @{
  'mobius.milestone' = '7.8'
  'mobius.campaign' = $CampaignId
  'mobius.generation' = $GenerationId
  'mobius.cleanup-deadline-utc' = $CleanupDeadlineUtc
  'mobius.cost-ceiling-cents' = [string]$CostCeilingCents
  'mobius.fresh-controller-admission-sha256' = $FreshControllerAdmissionEvidenceSha256
  'mobius.fresh-controller-admission-version' = $FreshControllerAdmissionEvidenceVersion
}
foreach ($key in $requiredTags.Keys) {
  if ($targetGroup.Tags[$key] -ne $requiredTags[$key]) { throw 'cleanup-resource-tag-mismatch' }
}

$targetScope = "/subscriptions/$($context.Subscription.Id)/resourceGroups/$TargetResourceGroupName"
$assignments = @(Get-AzRoleAssignment -Scope $targetScope | Where-Object { $_.ObjectId -eq $principalId })
$expectedRoles = @(
  'b24988ac-6180-42a0-ab88-20f7382dd24c',
  'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
)
$observedRoles = @($assignments | ForEach-Object { [string]$_.RoleDefinitionId } | Sort-Object -Unique)
if ($assignments.Count -ne 2 -or (Compare-Object $expectedRoles $observedRoles)) {
  throw 'cleanup-target-authority-mismatch'
}

try {
  Remove-AzResourceGroup -Name $TargetResourceGroupName -Force
}
catch {
  if (Get-AzResourceGroup -Name $TargetResourceGroupName -ErrorAction SilentlyContinue) {
    throw 'cleanup-target-delete-failed'
  }
}
if (Get-AzResourceGroup -Name $TargetResourceGroupName -ErrorAction SilentlyContinue) {
  throw 'cleanup-target-residue-nonzero'
}

[ordered]@{
  version = 'm7.8-cleanup-receipt-v4'
  campaignCorrelation = Get-Correlation 'campaign' $CampaignId
  generationCorrelation = Get-Correlation 'generation' $GenerationId
  targetResourceGroups = 0
  controllerDisposition = 'reusable-controller-retained-disarm-required'
  cleanupDisposition = 'target-zero-residue-controller-retained'
  freshControllerAdmissionEvidenceSha256 = $FreshControllerAdmissionEvidenceSha256
  freshControllerAdmissionEvidenceVersion = $FreshControllerAdmissionEvidenceVersion
  status = 'target-removed-controller-disarm-required'
  observedAtUtc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json -Compress
