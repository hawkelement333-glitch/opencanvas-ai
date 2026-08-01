targetScope = 'resourceGroup'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

@allowed(['Balanced_B0'])
param proposedSku string = 'Balanced_B0'
@minValue(2)
@maxValue(2)
param nodeCount int = 2
@allowed([false])
param providerContractResolved bool = false

@allowed(['contract-only', 'managed-binding-one-run'])
param managedBindingMode string
param managedBindingDeploymentEnabled bool
@allowed(['southcentralus'])
param location string
param privateEndpointSubnetId string
param virtualNetworkId string
param workloadIdentityPrincipalId string
param lifecycleTags object

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var cacheName = 'redis-mobius77-11564669'

resource cache 'Microsoft.Cache/redisEnterprise@2026-05-01-preview' = if (enabled) {
  name: cacheName
  location: location
  tags: lifecycleTags
  sku: { name: 'Balanced_B0' }
  properties: { minimumTlsVersion: '1.2', publicNetworkAccess: 'Disabled' }
}

resource database 'Microsoft.Cache/redisEnterprise/databases@2026-05-01-preview' = if (enabled) {
  parent: cache
  name: 'default'
  properties: {
    accessKeysAuthentication: 'Disabled'
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'NoCluster'
    evictionPolicy: 'NoEviction'
  }
}

resource accessPolicy 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2026-05-01-preview' = if (enabled) {
  parent: database
  name: 'mobius77api'
  properties: {
    accessPolicyName: 'default'
    accessString: '+@read +@write +@connection +@scripting +time ~mobius:v1:*'
    user: { objectId: workloadIdentityPrincipalId }
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: 'privatelink.redis.azure.net'
  location: 'global'
  tags: lifecycleTags
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: privateDnsZone
  name: 'link-mobius77-redis'
  location: 'global'
  tags: lifecycleTags
  properties: { registrationEnabled: false, virtualNetwork: { id: virtualNetworkId } }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-10-01' = if (enabled) {
  name: 'pe-mobius77-redis'
  location: location
  tags: lifecycleTags
  properties: {
    privateLinkServiceConnections: [{
      name: 'redis'
      properties: { groupIds: ['redisEnterprise'], privateLinkServiceId: cache.id }
    }]
    subnet: { id: privateEndpointSubnetId }
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = if (enabled) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'redis', properties: { privateDnsZoneId: privateDnsZone.id } }]
  }
  dependsOn: [dnsLink]
}

output cacheId string = enabled ? cache.id : ''
output hostName string = enabled ? cache.properties.hostName : ''
output port int = enabled ? database.properties.port : 10000
output username string = workloadIdentityPrincipalId
output publicNetworkAccess string = 'Disabled'
output configuredSku string = proposedSku
output configuredNodeCount int = nodeCount
output providerContractResolved bool = providerContractResolved
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
