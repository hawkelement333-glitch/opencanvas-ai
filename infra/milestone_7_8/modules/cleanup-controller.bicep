targetScope = 'resourceGroup'

param cleanupLocation string
param automationAccountName string
param cleanupRunbookName string
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
    description: 'Reusable fail-closed cleanup controller for one campaign generation at a time.'
    logProgress: false
    logVerbose: false
    runbookType: 'PowerShell72'
  }
}

output automationAccountName string = account.name
output cleanupPrincipalId string = account.identity.principalId
output runbookName string = runbook.name
output cleanupLocation string = cleanupLocation
