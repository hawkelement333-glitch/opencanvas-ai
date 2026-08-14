targetScope = 'resourceGroup'

param cleanupLocation string
param cleanupRegionSelectionSha256 string
param cleanupCandidateRegions string
param cleanupOfferClassification string
param cleanupOfferEligibilityDisposition string
param cleanupOfferEligibleRegions string
param cleanupOfferEligibilitySource string
param cleanupOfferEligibilitySha256 string
param automationAccountName string
param cleanupRunbookName string
param cleanupScheduleName string
param cleanupBindingName string
param lifecycleTags object

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

output automationAccountName string = account.name
output cleanupPrincipalId string = account.identity.principalId
output runbookName string = runbook.name
// Publication is an imperative Automation operation. The schedule and binding
// are intentionally absent here and are created only by cleanup-arm after the
// published runbook and exact campaign authority have been read back.
output scheduleName string = cleanupScheduleName
output bindingName string = cleanupBindingName
output cleanupLocation string = cleanupLocation
output cleanupRegionSelectionSha256 string = cleanupRegionSelectionSha256
output cleanupCandidateRegions string = cleanupCandidateRegions
output cleanupOfferClassification string = cleanupOfferClassification
output cleanupOfferEligibilityDisposition string = cleanupOfferEligibilityDisposition
output cleanupOfferEligibleRegions string = cleanupOfferEligibleRegions
output cleanupOfferEligibilitySource string = cleanupOfferEligibilitySource
output cleanupOfferEligibilitySha256 string = cleanupOfferEligibilitySha256
