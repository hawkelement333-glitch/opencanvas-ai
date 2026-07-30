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
  'Balanced_B0'
])
param proposedSku string = 'Balanced_B0'

@minValue(2)
@maxValue(2)
param nodeCount int = 2

@allowed([
  'single-shard-nonclustered'
])
param clusteringBehavior string = 'single-shard-nonclustered'

@allowed([
  'NoEviction'
])
param evictionPolicy string = 'NoEviction'

@allowed([
  'MicrosoftEntraOnly'
])
param authenticationMode string = 'MicrosoftEntraOnly'

@allowed([
  false
])
param accessKeysEnabled bool = false

@allowed([
  false
])
param publicNetworkAccess bool = false

@allowed([
  false
])
param providerContractResolved bool = false

output moduleName string = 'redis'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output proposedSku string = proposedSku
output nodeCount int = nodeCount
output clusteringBehavior string = clusteringBehavior
output evictionPolicy string = evictionPolicy
output authenticationMode string = authenticationMode
output accessKeysEnabled bool = accessKeysEnabled
output publicNetworkAccess bool = publicNetworkAccess
output providerContractResolved bool = providerContractResolved
