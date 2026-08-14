param(
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-z][a-z0-9-]{7,47}$')][string]$CampaignId,
  [Parameter(Mandatory = $true)][ValidatePattern('^g[1-9][0-9]{0,5}-[a-f0-9]{12}$')][string]$GenerationId,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{16}$')][string]$SubscriptionCorrelation,
  [Parameter(Mandatory = $true)][ValidatePattern('^rg-m78-[a-f0-9]{10}-target$')][string]$TargetResourceGroupName,
  [Parameter(Mandatory = $true)][ValidatePattern('^rg-m78-[a-f0-9]{10}-cleanup$')][string]$CleanupResourceGroupName,
  [Parameter(Mandatory = $true)][ValidatePattern('^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')][string]$CleanupDeadlineUtc,
  [Parameter(Mandatory = $true)][ValidateRange(5000, 5000)][int]$CostCeilingCents,
  [Parameter(Mandatory = $true)][ValidateSet('true')][string]$CleanupAuthorized
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Correlation([string]$Domain, [string]$Value) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes("m7.8/$Domain`0$Value")
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant().Substring(0, 16)
  }
  finally { $sha.Dispose() }
}

if ($CleanupAuthorized -ne 'true' -or $TargetResourceGroupName -eq $CleanupResourceGroupName) {
  throw 'cleanup-binding-invalid'
}
$parsedDeadline = [DateTimeOffset]::ParseExact(
  $CleanupDeadlineUtc,
  'yyyy-MM-ddTHH:mm:ssZ',
  [System.Globalization.CultureInfo]::InvariantCulture,
  [System.Globalization.DateTimeStyles]::AssumeUniversal
)
if ($parsedDeadline.Offset -ne [TimeSpan]::Zero) { throw 'cleanup-deadline-not-utc' }

Connect-AzAccount -Identity | Out-Null
$context = Get-AzContext
if ((Get-Correlation 'subscription' $context.Subscription.Id) -ne $SubscriptionCorrelation) {
  throw 'cleanup-subscription-correlation-mismatch'
}

$requiredTags = @{
  'mobius.milestone' = '7.8'
  'mobius.campaign' = $CampaignId
  'mobius.generation' = $GenerationId
  'mobius.cleanup-deadline-utc' = $CleanupDeadlineUtc
  'mobius.cost-ceiling-cents' = [string]$CostCeilingCents
}

foreach ($name in @($TargetResourceGroupName, $CleanupResourceGroupName)) {
  $group = Get-AzResourceGroup -Name $name
  foreach ($key in $requiredTags.Keys) {
    if ($group.Tags[$key] -ne $requiredTags[$key]) { throw 'cleanup-resource-tag-mismatch' }
  }
}

Remove-AzResourceGroup -Name $TargetResourceGroupName -Force
if (Get-AzResourceGroup -Name $TargetResourceGroupName -ErrorAction SilentlyContinue) {
  throw 'cleanup-target-residue-nonzero'
}

$receipt = [ordered]@{
  version = 'm7.8-cleanup-receipt-v2'
  campaignCorrelation = Get-Correlation 'campaign' $CampaignId
  generationCorrelation = Get-Correlation 'generation' $GenerationId
  targetResourceGroups = 0
  automationAccounts = 1
  softDeletedAutomationAccounts = 'pending-independent-readback'
  cleanupDisposition = 'provider-retention-pending'
  status = 'target-removed-cleanup-group-delete-started'
  observedAtUtc = [DateTime]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Compress

# The ARM delete request survives termination of this runbook. It removes the
# active cleanup group and scoped RBAC, but Automation account retention remains
# nonzero until an independently paginated deleted-account readback proves absence.
$selfDeletePath = "/subscriptions/$($context.Subscription.Id)/resourceGroups/${CleanupResourceGroupName}?api-version=2024-11-01"
Invoke-AzRestMethod -Path $selfDeletePath -Method DELETE | Out-Null
