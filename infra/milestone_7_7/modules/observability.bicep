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

@allowed([
  'PerGB2018'
])
param logAnalyticsSku string = 'PerGB2018'

@minValue(2560)
@maxValue(2560)
param absoluteExerciseIngestionCapMiB int = 2560

@minValue(100)
@maxValue(100)
param sanitizedEvidenceCapMiB int = 100

@allowed([
  false
])
param retentionResolved bool = false

@allowed([
  false
])
param alertDestinationResolved bool = false

@allowed([
  true
])
param telemetryGatewayResolved bool = true

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled

resource workspace 'Microsoft.OperationalInsights/workspaces@2026-03-01' = if (enabled) {
  name: 'law-mobius77-staging'
  location: location
  tags: lifecycleTags
  properties: {
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery: 'Disabled'
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
    workspaceCapping: {
      dailyQuotaGb: 2
    }
  }
}

output moduleName string = 'observability'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output logAnalyticsSku string = logAnalyticsSku
output absoluteExerciseIngestionCapMiB int = absoluteExerciseIngestionCapMiB
output sanitizedEvidenceCapMiB int = sanitizedEvidenceCapMiB
output retentionResolved bool = retentionResolved
output alertDestinationResolved bool = alertDestinationResolved
output telemetryGatewayResolved bool = telemetryGatewayResolved
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output workspaceId string = enabled ? workspace.id : ''
output publicIngestionAllowed bool = false
output publicQueryAllowed bool = false
output retentionDays int = 30
output exerciseIngestionCapMiB int = 2560
