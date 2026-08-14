targetScope = 'resourceGroup'

param campaignId string
param generationId string
param subscriptionCorrelation string
param targetResourceGroupName string
param cleanupResourceGroupName string
param cleanupLocation string
param cleanupRegionSelectionSha256 string
param cleanupOfferClassification string
param cleanupOfferEligibilityDisposition string
param cleanupOfferEligibleRegions string
param cleanupOfferEligibilitySource string
param cleanupOfferEligibilitySha256 string
param cleanupDeadlineUtc string
param automationAccountName string
param cleanupRunbookName string
param cleanupScheduleName string
param costCeilingCents int
param lifecycleTags object

var bindingName = guid(campaignId, generationId, subscriptionCorrelation, targetResourceGroupName, cleanupDeadlineUtc)

resource account 'Microsoft.Automation/automationAccounts@2024-10-23' = {
  name: automationAccountName
  location: cleanupLocation
  tags: lifecycleTags
  identity: { type: 'SystemAssigned' }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: true
    sku: { name: 'Basic' }
  }
}

resource runbook 'Microsoft.Automation/automationAccounts/runbooks@2024-10-23' = {
  parent: account
  name: cleanupRunbookName
  location: cleanupLocation
  tags: lifecycleTags
  properties: {
    description: 'Fail-closed cleanup for one bound Milestone 7.8 campaign generation.'
    logProgress: false
    logVerbose: false
    runbookType: 'PowerShell72'
  }
}

resource schedule 'Microsoft.Automation/automationAccounts/schedules@2024-10-23' = {
  parent: account
  name: cleanupScheduleName
  properties: {
    description: 'One-time immutable Milestone 7.8 cleanup deadline.'
    frequency: 'OneTime'
    interval: 1
    startTime: cleanupDeadlineUtc
    timeZone: 'Etc/UTC'
  }
}

resource binding 'Microsoft.Automation/automationAccounts/jobSchedules@2024-10-23' = {
  parent: account
  name: bindingName
  properties: {
    parameters: {
      CampaignId: campaignId
      GenerationId: generationId
      SubscriptionCorrelation: subscriptionCorrelation
      TargetResourceGroupName: targetResourceGroupName
      CleanupResourceGroupName: cleanupResourceGroupName
      CleanupDeadlineUtc: cleanupDeadlineUtc
      CostCeilingCents: string(costCeilingCents)
      CleanupAuthorized: 'true'
    }
    runbook: { name: runbook.name }
    schedule: { name: schedule.name }
  }
}

output automationAccountName string = account.name
output cleanupPrincipalId string = account.identity.principalId
output runbookName string = runbook.name
output scheduleName string = schedule.name
output bindingName string = binding.name
output cleanupLocation string = cleanupLocation
output cleanupRegionSelectionSha256 string = cleanupRegionSelectionSha256
output cleanupOfferClassification string = cleanupOfferClassification
output cleanupOfferEligibilityDisposition string = cleanupOfferEligibilityDisposition
output cleanupOfferEligibleRegions string = cleanupOfferEligibleRegions
output cleanupOfferEligibilitySource string = cleanupOfferEligibilitySource
output cleanupOfferEligibilitySha256 string = cleanupOfferEligibilitySha256
