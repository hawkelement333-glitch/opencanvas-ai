targetScope = 'subscription'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

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
  false
])
param telemetryGatewayResolved bool = false

output moduleName string = 'observability'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output logAnalyticsSku string = logAnalyticsSku
output absoluteExerciseIngestionCapMiB int = absoluteExerciseIngestionCapMiB
output sanitizedEvidenceCapMiB int = sanitizedEvidenceCapMiB
output retentionResolved bool = retentionResolved
output alertDestinationResolved bool = alertDestinationResolved
output telemetryGatewayResolved bool = telemetryGatewayResolved
