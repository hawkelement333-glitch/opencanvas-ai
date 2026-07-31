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

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param privateEndpointSubnetId string = ''
param virtualNetworkId string = ''
param workloadIdentityPrincipalId string = ''
param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var registryName = 'acrmobius7711564669'
var privateDnsZoneName = 'privatelink.azurecr.io'

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = if (enabled) {
  name: registryName
  location: location
  tags: lifecycleTags
  sku: {
    name: 'Premium'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    dataEndpointEnabled: false
    networkRuleBypassOptions: 'None'
    publicNetworkAccess: 'Disabled'
    zoneRedundancy: 'Disabled'
  }
}

resource registryPrivateEndpoint 'Microsoft.Network/privateEndpoints@2026-01-01' = if (enabled) {
  name: 'pe-mobius77-acr'
  location: location
  tags: lifecycleTags
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'plc-mobius77-acr'
        properties: {
          groupIds: [
            'registry'
          ]
          privateLinkServiceId: registry.id
          requestMessage: 'Milestone 7.7 isolated synthetic validation'
        }
      }
    ]
    subnet: {
      id: privateEndpointSubnetId
    }
  }
}

resource registryPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2025-07-01' = if (enabled) {
  parent: registryPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'registry'
        properties: {
          privateDnsZoneId: resourceId('Microsoft.Network/privateDnsZones', privateDnsZoneName)
        }
      }
    ]
  }
}

resource workloadRegistryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(registry.id, workloadIdentityPrincipalId, '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  scope: registry
  properties: {
    principalId: workloadIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

output moduleName string = 'registry'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output registrySku string = registrySku
output publicNetworkAccess bool = publicNetworkAccess
output administratorAccountEnabled bool = administratorAccountEnabled
output imageBindingCount int = imageBindingCount
output imageDigestContractResolved bool = imageDigestContractResolved
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output registryName string = registryName
output registryLoginServer string = enabled ? registry.properties.loginServer : '${registryName}.azurecr.io'
output virtualNetworkBindingVerified bool = enabled && !empty(virtualNetworkId)
output mutableImageTagsAllowed bool = false
