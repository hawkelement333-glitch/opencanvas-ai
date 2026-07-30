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
  'standard'
])
param vaultSku string = 'standard'

@allowed([
  false
])
param publicNetworkAccess bool = false

@allowed([
  true
])
param privateEndpointRequired bool = true

output moduleName string = 'key-vault'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output vaultSku string = vaultSku
output publicNetworkAccess bool = publicNetworkAccess
output privateEndpointRequired bool = privateEndpointRequired
