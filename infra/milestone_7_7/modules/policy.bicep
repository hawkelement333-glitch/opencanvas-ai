targetScope = 'subscription'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

@minLength(1)
@maxLength(64)
param deploymentRegion string

@allowed([
  false
])
param regionVerified bool = false

@minValue(11)
@maxValue(11)
param requiredTagCount int = 11

@minValue(10)
@maxValue(10)
param unresolvedGateCount int = 10

output moduleName string = 'policy'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output regionSupplied bool = !empty(deploymentRegion)
output regionVerified bool = regionVerified
output requiredTagCount int = requiredTagCount
output unresolvedGateCount int = unresolvedGateCount
