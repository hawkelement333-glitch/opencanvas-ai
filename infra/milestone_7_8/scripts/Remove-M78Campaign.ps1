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
  [Parameter(Mandatory = $true)][ValidateSet(5000, 5651)][int]$CostCeilingCents,
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

function Get-ArmContent([string]$Path) {
  $response = Invoke-AzRestMethod -Path $Path -Method GET
  if ([string]::IsNullOrWhiteSpace($response.Content)) { throw 'cleanup-readback-empty' }
  return $response.Content
}

function Get-ArmJson([string]$Path) {
  return (Get-ArmContent $Path) | ConvertFrom-Json -Depth 32
}

function Assert-CleanupBindingParameters([string]$Content, [hashtable]$Expected) {
  # ConvertFrom-Json can coerce ISO strings to DateTime in the Automation runtime.
  try { $document = [System.Text.Json.JsonDocument]::Parse($Content) }
  catch { throw 'cleanup-binding-parameter-set-mismatch:invalid-json' }
  try {
    try { $parameters = $document.RootElement.GetProperty('properties').GetProperty('parameters') }
    catch { throw 'cleanup-binding-parameter-set-mismatch:parameters-shape' }
    if ($parameters.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) {
      throw 'cleanup-binding-parameter-set-mismatch:parameters-shape'
    }
    $seen = @{}
    foreach ($parameter in $parameters.EnumerateObject()) {
      $key = $parameter.Name
      if (-not $Expected.ContainsKey($key)) {
        throw 'cleanup-binding-parameter-set-mismatch:unknown-field'
      }
      # Emit only the trusted parameter name and a fixed reason/type. Never
      # emit provider-supplied keys, values, identifiers, hashes, or raw content.
      $field = @($Expected.Keys | Where-Object { $_ -ieq $key })[0]
      if ($seen.ContainsKey($key)) {
        throw "cleanup-binding-parameter-set-mismatch:${field}:duplicate"
      }
      if ($parameter.Value.ValueKind -ne [System.Text.Json.JsonValueKind]::String) {
        throw "cleanup-binding-parameter-mismatch:${field}:type-$($parameter.Value.ValueKind)"
      }
      if ($Expected[$key] -isnot [string]) {
        throw "cleanup-binding-parameter-mismatch:${field}:expected-type"
      }
      $observedValue = $parameter.Value.GetString()
      if ($observedValue -cne $Expected[$key]) {
        if ([string]::Equals($observedValue, $Expected[$key], [System.StringComparison]::OrdinalIgnoreCase)) {
          throw "cleanup-binding-parameter-mismatch:${field}:value-case-only"
        }
        throw "cleanup-binding-parameter-mismatch:${field}:value"
      }
      $seen[$key] = $true
    }
    foreach ($field in ($Expected.Keys | Sort-Object)) {
      if (-not $seen.ContainsKey($field)) {
        throw "cleanup-binding-parameter-set-mismatch:${field}:missing"
      }
    }
  }
  finally { $document.Dispose() }
}

function Assert-CleanupBindingIdentity([hashtable]$Binding, [string]$ExpectedId, [string]$ExpectedName) {
  # ARM jobSchedules GET omits name. Match the full resource ID and UUID;
  # preserve the legacy named shape, and reject every supplied conflict.
  $properties = $Binding['properties']
  if ($properties -isnot [hashtable]) { throw 'cleanup-binding-identity-mismatch:properties' }
  $name = $Binding['name']
  $id = $Binding['id']
  $uuid = $properties['jobScheduleId']
  $values = @{ name = $name; id = $id; jobScheduleId = $uuid }
  foreach ($field in @('name', 'id', 'jobScheduleId')) {
    $value = $values[$field]
    $expectedValue = if ($field -eq 'id') { $ExpectedId } else { $ExpectedName }
    if ($null -ne $value -and ($value -isnot [string] -or $value -ine $expectedValue)) {
      throw "cleanup-binding-identity-mismatch:${field}"
    }
  }
  if ($null -eq $name -and ($null -eq $id -or $null -eq $uuid)) {
    throw 'cleanup-binding-identity-mismatch:missing'
  }
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
$bindingContent = Get-ArmContent "$automationBase/jobSchedules/$CleanupBindingName`?api-version=2024-10-23"

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
  # The parameter admission above already requires affirmative true. PowerShell
  # may bind it as 'True'; the persisted binding still must be the exact string.
  CleanupAuthorized = 'true'
}
Assert-CleanupBindingParameters $bindingContent $expectedBindingParameters
$binding = $bindingContent | ConvertFrom-Json -Depth 32 -AsHashtable
Assert-CleanupBindingIdentity $binding "$automationBase/jobSchedules/$CleanupBindingName" $CleanupBindingName
if (
  $observedControllerBinding -ne $ControllerBindingSha256 -or
  $account.name -ne $AutomationAccountName -or
  $runbook.name -ne $CleanupRunbookName -or
  $runbook.properties.state -ne 'Published' -or
  $schedule.name -ne $CleanupScheduleName -or
  $schedule.properties.frequency -ne 'OneTime' -or
  $schedule.properties.isEnabled -ne $true -or
  [DateTimeOffset]$schedule.properties.startTime -ne $parsedDeadline -or
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
  if ($key -eq 'mobius.cleanup-deadline-utc') { continue }
  if ($targetGroup.Tags[$key] -ne $requiredTags[$key]) { throw 'cleanup-resource-tag-mismatch' }
}

$targetScope = "/subscriptions/$($context.Subscription.Id)/resourceGroups/$TargetResourceGroupName"
$assignments = @(Get-AzRoleAssignment -Scope $targetScope | Where-Object { $_.ObjectId -eq $principalId })
$expectedRoles = @(
  'b24988ac-6180-42a0-ab88-20f7382dd24c',
  'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
)
$observedRoles = @($assignments | ForEach-Object { [string]$_.RoleDefinitionId } | Sort-Object -Unique)
if (
  $assignments.Count -ne 2 -or (Compare-Object $expectedRoles $observedRoles) -or
  @($assignments | Where-Object { $_.Scope -ine $targetScope }).Count -ne 0
) {
  throw 'cleanup-target-authority-mismatch'
}

if ($targetGroup.Tags['mobius.cleanup-deadline-utc'] -cne $CleanupDeadlineUtc) {
  # A predecessor stays armed during renewal. It may yield only to an exact,
  # enabled replacement selected by the target group's single tag update.
  # This is a pre-expiry, single-writer protocol, not an ARM concurrency lock.
  $activeDeadline = $targetGroup.Tags['mobius.cleanup-deadline-utc']
  $activeSchedule = $targetGroup.Tags['mobius.cleanup-schedule']
  $activeBinding = $targetGroup.Tags['mobius.cleanup-binding']
  $activeAuthority = $targetGroup.Tags['mobius.cleanup-authority-sha256']
  $plannedAt = $targetGroup.Tags['mobius.cleanup-renewal-planned-utc']
  if (
    $activeDeadline -isnot [string] -or
    $activeDeadline -cnotmatch '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' -or
    $activeSchedule -isnot [string] -or $activeSchedule -cnotmatch '^m78-deadline-[a-f0-9]{10}$' -or
    $activeBinding -isnot [string] -or $activeBinding -cnotmatch '^[a-f0-9-]{36}$' -or
    $activeAuthority -isnot [string] -or $activeAuthority -cnotmatch '^[a-f0-9]{64}$' -or
    $plannedAt -isnot [string] -or
    $plannedAt -cnotmatch '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$' -or
    $activeSchedule -ceq $CleanupScheduleName -or $activeBinding -ceq $CleanupBindingName -or
    $targetGroup.Tags['mobius.cleanup-parent-binding'] -cne $CleanupBindingName -or
    $targetGroup.Tags['mobius.cleanup-parent-authority-sha256'] -cne $CleanupAuthoritySha256 -or
    $targetGroup.Tags['mobius.expiry'] -cne $activeDeadline
  ) { throw 'cleanup-renewal-selection-invalid' }
  $activeTime = [DateTimeOffset]::ParseExact(
    $activeDeadline, 'yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal
  )
  $plannedTime = [DateTimeOffset]::Parse(
    $plannedAt, [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal
  )
  $activeExpiry = $activeTime.AddHours(1).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  if (
    $activeTime -le $parsedDeadline -or $plannedTime -ge $parsedDeadline -or
    $plannedTime -gt [DateTimeOffset]::UtcNow -or [DateTimeOffset]::UtcNow -ge $activeTime -or
    $controllerAuthorizedUntil -lt $activeTime.AddHours(1)
  ) { throw 'cleanup-renewal-window-invalid' }
  $replacementValues = @(
    'reusable-automation-controller-v1', $CampaignId, $GenerationId, $SubscriptionCorrelation,
    $TargetResourceGroupName, $ControllerResourceGroupName, $AutomationAccountName,
    $CleanupRunbookName, $activeSchedule, $activeBinding, $activeDeadline, $activeExpiry,
    [string]$CostCeilingCents, $ControllerBindingSha256,
    $FreshControllerAdmissionEvidenceSha256, $FreshControllerAdmissionEvidenceVersion
  )
  $replacementHash = Get-Sha256 ("m7.8/cleanup-authority/v4`0" + ($replacementValues -join "`0"))
  if ($replacementHash -cne $activeAuthority) { throw 'cleanup-renewal-authority-mismatch' }
  $replacementParameters = $expectedBindingParameters.Clone()
  $replacementParameters.CleanupScheduleName = $activeSchedule
  $replacementParameters.CleanupBindingName = $activeBinding
  $replacementParameters.CleanupDeadlineUtc = $activeDeadline
  $replacementParameters.CleanupAuthorityExpiresUtc = $activeExpiry
  $replacementParameters.CleanupAuthoritySha256 = $activeAuthority
  $replacementContent = Get-ArmContent "$automationBase/jobSchedules/$activeBinding`?api-version=2024-10-23"
  Assert-CleanupBindingParameters $replacementContent $replacementParameters
  $replacement = $replacementContent | ConvertFrom-Json -Depth 32 -AsHashtable
  Assert-CleanupBindingIdentity $replacement "$automationBase/jobSchedules/$activeBinding" $activeBinding
  $replacementSchedule = Get-ArmJson "$automationBase/schedules/$activeSchedule`?api-version=2024-10-23"
  if (
    $replacement.properties.runbook.name -cne $CleanupRunbookName -or
    $replacement.properties.schedule.name -cne $activeSchedule -or
    ($replacement['properties'].ContainsKey('runOn') -and
      -not [string]::IsNullOrEmpty($replacement['properties']['runOn'])) -or
    $replacementSchedule.name -cne $activeSchedule -or
    $replacementSchedule.properties.frequency -cne 'OneTime' -or
    $replacementSchedule.properties.isEnabled -ne $true -or
    [DateTimeOffset]$replacementSchedule.properties.startTime -ne $activeTime
  ) { throw 'cleanup-renewal-replacement-invalid' }
  [ordered]@{
    status = 'superseded-cleanup-verified'
    targetDeletionStarted = $false
    observedAtUtc = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json -Compress
  return
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
