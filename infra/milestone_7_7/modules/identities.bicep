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

@description('The cleanup-binding stage creates only the exact target-group role assignment.')
param workloadIdentityDeploymentEnabled bool = false

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

param targetResourceGroupId string

param cleanupAutomationPrincipalId string

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var workloadIdentityEnabled = enabled && workloadIdentityDeploymentEnabled

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (workloadIdentityEnabled) {
  name: 'id-mobius77-api'
  location: location
  tags: lifecycleTags
}

resource databaseAdministratorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (workloadIdentityEnabled) {
  name: 'id-mobius77-db-admin'
  location: location
  tags: lifecycleTags
}

resource cleanupTargetContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(targetResourceGroupId, cleanupAutomationPrincipalId, 'b24988ac-6180-42a0-ab88-20f7382dd24c')
  properties: {
    principalId: cleanupAutomationPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b24988ac-6180-42a0-ab88-20f7382dd24c'
    )
  }
}

output moduleName string = 'identities'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output managedIdentityEnvironmentMappingResolved bool = managedIdentityEnvironmentMappingResolved
output crossScopeAuthorityAllowed bool = crossScopeAuthorityAllowed
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output workloadIdentityDeploymentEnabled bool = workloadIdentityEnabled
output workloadIdentityId string = workloadIdentityEnabled ? workloadIdentity.id : ''
output workloadIdentityPrincipalId string = workloadIdentityEnabled ? workloadIdentity.properties.principalId : ''
output workloadIdentityClientId string = workloadIdentityEnabled ? workloadIdentity.properties.clientId : ''
output databaseAdministratorIdentityId string = workloadIdentityEnabled ? databaseAdministratorIdentity.id : ''
output databaseAdministratorPrincipalId string = workloadIdentityEnabled ? databaseAdministratorIdentity.properties.principalId : ''
output databaseAdministratorClientId string = workloadIdentityEnabled ? databaseAdministratorIdentity.properties.clientId : ''
output databaseAdministratorName string = workloadIdentityEnabled ? databaseAdministratorIdentity.name : ''
