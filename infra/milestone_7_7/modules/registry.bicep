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
  'Premium'
])
param registrySku string = 'Premium'

@allowed([
  false
])
param publicNetworkAccess bool = false

@allowed([
  false
])
param administratorAccountEnabled bool = false

@minValue(8)
@maxValue(8)
param imageBindingCount int = 8

@allowed([
  false
])
param imageDigestContractResolved bool = false

output moduleName string = 'registry'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output registrySku string = registrySku
output publicNetworkAccess bool = publicNetworkAccess
output administratorAccountEnabled bool = administratorAccountEnabled
output imageBindingCount int = imageBindingCount
output imageDigestContractResolved bool = imageDigestContractResolved
