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
  false
])
param managedIdentityEnvironmentMappingResolved bool = false

@allowed([
  false
])
param crossScopeAuthorityAllowed bool = false

output moduleName string = 'identities'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output managedIdentityEnvironmentMappingResolved bool = managedIdentityEnvironmentMappingResolved
output crossScopeAuthorityAllowed bool = crossScopeAuthorityAllowed
