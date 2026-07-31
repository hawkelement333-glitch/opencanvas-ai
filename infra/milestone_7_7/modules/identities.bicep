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
  false
])
param managedIdentityEnvironmentMappingResolved bool = false

@allowed([
  false
])
param crossScopeAuthorityAllowed bool = false

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (enabled) {
  name: 'id-mobius77-api'
  location: location
  tags: lifecycleTags
}

output moduleName string = 'identities'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output managedIdentityEnvironmentMappingResolved bool = managedIdentityEnvironmentMappingResolved
output crossScopeAuthorityAllowed bool = crossScopeAuthorityAllowed
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output workloadIdentityId string = enabled ? workloadIdentity.id : ''
output workloadIdentityPrincipalId string = enabled ? workloadIdentity.properties.principalId : ''
