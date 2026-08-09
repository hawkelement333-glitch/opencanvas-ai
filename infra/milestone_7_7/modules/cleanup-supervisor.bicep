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

param cleanupControlDeploymentEnabled bool = false

param cleanupJobScheduleDeploymentEnabled bool = false

@minValue(1)
@maxValue(12000)
param expectedUsdCents int

@minValue(1)
@maxValue(25000)
param maximumPlausibleUsdCents int

@minValue(2500)
@maxValue(10000)
param uncertaintyContingencyBasisPoints int = 2500

@minValue(12)
@maxValue(12)
param defaultPlannedHours int = 12

@minValue(30)
@maxValue(30)
param hardMaximumHours int = 30

@minValue(30)
@maxValue(30)
param vpnMaximumHours int = 30

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
  'westus'
])
param cleanupLocation string = 'westus'

@allowed([
  'rg-solarplexus-mobius-77-staging'
])
param targetResourceGroupName string = 'rg-solarplexus-mobius-77-staging'

param lifecycleTags object = {}
param cleanupAtUtc string = ''

@allowed([
  4
])
param cleanupBindingGeneration int = 4

@allowed([
  'm7.7-automation-cleanup-binding-v4'
])
param cleanupBindingContractVersion string = 'm7.7-automation-cleanup-binding-v4'

var contractEnabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var cleanupControlEnabled = contractEnabled && cleanupControlDeploymentEnabled && !cleanupJobScheduleDeploymentEnabled
var jobScheduleEnabled = contractEnabled && cleanupJobScheduleDeploymentEnabled && !cleanupControlDeploymentEnabled

resource automationAccount 'Microsoft.Automation/automationAccounts@2024-10-23' = if (cleanupControlEnabled) {
  name: 'aa-mobius77-cleanup-recovery'
  location: cleanupLocation
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

resource cleanupRunbook 'Microsoft.Automation/automationAccounts/runbooks@2024-10-23' = if (cleanupControlEnabled) {
  parent: automationAccount
  name: 'Remove-Mobius77Staging'
  location: cleanupLocation
  tags: lifecycleTags
  properties: {
    description: 'Failsafe deletion of the exact Milestone 7.7 target resource group.'
    logProgress: false
    logVerbose: false
    runbookType: 'PowerShell72'
  }
}

resource cleanupSchedule 'Microsoft.Automation/automationAccounts/schedules@2024-10-23' = if (cleanupControlEnabled) {
  parent: automationAccount
  name: 'schedule-mobius77-cleanup-g4'
  properties: {
    description: 'One-time Milestone 7.7 hard cleanup failsafe.'
    frequency: 'OneTime'
    interval: 1
    startTime: cleanupAtUtc
    timeZone: 'Etc/UTC'
  }
}

resource existingAutomationAccount 'Microsoft.Automation/automationAccounts@2024-10-23' existing = if (jobScheduleEnabled) {
  name: 'aa-mobius77-cleanup-recovery'
}

resource existingCleanupRunbook 'Microsoft.Automation/automationAccounts/runbooks@2024-10-23' existing = if (jobScheduleEnabled) {
  parent: existingAutomationAccount
  name: 'Remove-Mobius77Staging'
}

resource existingCleanupSchedule 'Microsoft.Automation/automationAccounts/schedules@2024-10-23' existing = if (jobScheduleEnabled) {
  parent: existingAutomationAccount
  name: 'schedule-mobius77-cleanup-g4'
}

var generationOneBindingId = guid(existingAutomationAccount.id, existingCleanupRunbook.name, existingCleanupSchedule.name)
var activeBindingId = guid(
  toLower(existingAutomationAccount.id),
  toLower(existingCleanupRunbook.id),
  toLower(existingCleanupSchedule.id),
  toLower(resourceId('Microsoft.Resources/resourceGroups', targetResourceGroupName)),
  cleanupBindingContractVersion,
  'cleanup-binding-generation-${cleanupBindingGeneration}',
  'cleanupauthorized=true',
  'bindingepoch=${toLower(cleanupAtUtc)}'
)

resource cleanupJobSchedule 'Microsoft.Automation/automationAccounts/jobSchedules@2024-10-23' = if (jobScheduleEnabled) {
  parent: existingAutomationAccount
  name: activeBindingId
  properties: {
    parameters: {
      TargetResourceGroupName: targetResourceGroupName
      CleanupAuthorized: 'true'
    }
    runbook: {
      name: existingCleanupRunbook.name
    }
    schedule: {
      name: existingCleanupSchedule.name
    }
  }
}

output moduleName string = 'cleanup-supervisor'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output expectedWithinBlock bool = expectedUsdCents <= 12000
output maximumBelowCeiling bool = maximumPlausibleUsdCents <= 25000
output uncertaintyContingencyBasisPoints int = uncertaintyContingencyBasisPoints
output defaultPlannedHours int = defaultPlannedHours
output hardMaximumHours int = hardMaximumHours
output vpnMaximumHours int = vpnMaximumHours
output minimumCleanupReserveMinutes int = minimumCleanupReserveMinutes
output requiredTagCount int = requiredTagCount
output leaseBindingResolved bool = leaseBindingResolved
output cleanupTimerBindingResolved bool = cleanupTimerBindingResolved
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = cleanupControlEnabled || jobScheduleEnabled
output cleanupControlDeploymentEnabled bool = cleanupControlEnabled
output cleanupJobScheduleDeploymentEnabled bool = jobScheduleEnabled
output automationAccountName string = 'aa-mobius77-cleanup-recovery'
output cleanupRunbookName string = 'Remove-Mobius77Staging'
output cleanupScheduleName string = 'schedule-mobius77-cleanup-g4'
output cleanupBindingContractVersion string = cleanupBindingContractVersion
output cleanupBindingGeneration int = cleanupBindingGeneration
output tombstonedCleanupBindingId string = jobScheduleEnabled ? generationOneBindingId : ''
output activeCleanupBindingId string = jobScheduleEnabled ? activeBindingId : ''
output cleanupPrincipalId string = cleanupControlEnabled ? automationAccount.identity.principalId : ''
output cleanupLocation string = cleanupLocation
output publicNetworkAccess bool = false
output managedBindingCleanupTimerResourceCreated bool = jobScheduleEnabled && !empty(cleanupAtUtc)
