targetScope = 'resourceGroup'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

@allowed([
  'contract-only'
  'managed-binding-one-run'
])
param managedBindingMode string = 'contract-only'

param managedBindingDeploymentEnabled bool = false

@minValue(1)
@maxValue(12000)
param expectedUsdCents int

@minValue(1)
@maxValue(14999)
param maximumPlausibleUsdCents int

@minValue(2500)
@maxValue(10000)
param uncertaintyContingencyBasisPoints int = 2500

@minValue(12)
@maxValue(12)
param defaultPlannedHours int = 12

@minValue(24)
@maxValue(24)
param hardMaximumHours int = 24

@minValue(12)
@maxValue(12)
param vpnMaximumHours int = 12

@minValue(90)
@maxValue(90)
param minimumCleanupReserveMinutes int = 90

@minValue(11)
@maxValue(11)
param requiredTagCount int = 11

@allowed([
  false
])
param leaseBindingResolved bool = false

@allowed([
  false
])
param cleanupTimerBindingResolved bool = false

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

@allowed([
  'rg-solarplexus-mobius-77-staging'
])
param targetResourceGroupName string = 'rg-solarplexus-mobius-77-staging'

param lifecycleTags object = {}
param cleanupAtUtc string = ''

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled

resource automationAccount 'Microsoft.Automation/automationAccounts@2024-10-23' = if (enabled) {
  name: 'aa-mobius77-cleanup'
  location: location
  tags: lifecycleTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: false
    sku: {
      name: 'Basic'
    }
  }
}

resource cleanupRunbook 'Microsoft.Automation/automationAccounts/runbooks@2024-10-23' = if (enabled) {
  parent: automationAccount
  name: 'Remove-Mobius77Staging'
  location: location
  tags: lifecycleTags
  properties: {
    description: 'Failsafe deletion of the exact Milestone 7.7 target resource group.'
    logProgress: false
    logVerbose: false
    runbookType: 'PowerShell72'
  }
}

resource cleanupSchedule 'Microsoft.Automation/automationAccounts/schedules@2024-10-23' = if (enabled) {
  parent: automationAccount
  name: 'schedule-mobius77-cleanup'
  properties: {
    description: 'One-time Milestone 7.7 hard cleanup failsafe.'
    frequency: 'OneTime'
    interval: 1
    startTime: cleanupAtUtc
    timeZone: 'Etc/UTC'
  }
}

resource cleanupJobSchedule 'Microsoft.Automation/automationAccounts/jobSchedules@2024-10-23' = if (enabled) {
  parent: automationAccount
  name: guid(automationAccount.id, cleanupRunbook.name, cleanupSchedule.name)
  properties: {
    parameters: {
      TargetResourceGroupName: targetResourceGroupName
    }
    runbook: {
      name: cleanupRunbook.name
    }
    schedule: {
      name: cleanupSchedule.name
    }
  }
}

output moduleName string = 'cleanup-supervisor'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output expectedWithinBlock bool = expectedUsdCents <= 12000
output maximumBelowCeiling bool = maximumPlausibleUsdCents < 15000
output uncertaintyContingencyBasisPoints int = uncertaintyContingencyBasisPoints
output defaultPlannedHours int = defaultPlannedHours
output hardMaximumHours int = hardMaximumHours
output vpnMaximumHours int = vpnMaximumHours
output minimumCleanupReserveMinutes int = minimumCleanupReserveMinutes
output requiredTagCount int = requiredTagCount
output leaseBindingResolved bool = leaseBindingResolved
output cleanupTimerBindingResolved bool = cleanupTimerBindingResolved
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output automationAccountName string = 'aa-mobius77-cleanup'
output cleanupRunbookName string = 'Remove-Mobius77Staging'
output cleanupScheduleName string = 'schedule-mobius77-cleanup'
output cleanupPrincipalId string = enabled ? automationAccount.identity.principalId : ''
output publicNetworkAccess bool = false
output managedBindingCleanupTimerResourceCreated bool = enabled && !empty(cleanupAtUtc)
