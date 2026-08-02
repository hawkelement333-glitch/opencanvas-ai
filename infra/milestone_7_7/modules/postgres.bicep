targetScope = 'resourceGroup'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

@minValue(17)
@maxValue(17)
param majorVersion int = 17
@allowed(['Standard_D2ds_v5'])
param serverSku string = 'Standard_D2ds_v5'
@minValue(64)
@maxValue(64)
param storageGiB int = 64
@allowed(['ZoneRedundant'])
param highAvailability string = 'ZoneRedundant'

@allowed(['contract-only', 'managed-binding-one-run'])
param managedBindingMode string
param managedBindingDeploymentEnabled bool
@allowed(['centralus'])
param location string
param stagingVirtualNetworkId string
param databaseAdministratorIdentityId string
param databaseAdministratorPrincipalId string
param databaseAdministratorName string
param tenantId string
param lifecycleTags object

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var regionalVnetName = 'vnet-mobius77-postgres'
var delegatedSubnetName = 'snet-mobius77-postgres'
var privateDnsZoneName = 'privatelink.postgres.database.azure.com'
var serverName = 'psql-mobius77-11564669'

resource regionalVnet 'Microsoft.Network/virtualNetworks@2026-01-01' = if (enabled) {
  name: regionalVnetName
  location: location
  tags: lifecycleTags
  properties: {
    addressSpace: { addressPrefixes: ['10.78.0.0/24'] }
    subnets: [
      {
        name: delegatedSubnetName
        properties: {
          addressPrefix: '10.78.0.0/26'
          delegations: [
            {
              name: 'postgres-flexible-server'
              properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource stagingVnet 'Microsoft.Network/virtualNetworks@2026-01-01' existing = if (enabled) {
  name: last(split(stagingVirtualNetworkId, '/'))
}

resource stagingToPostgres 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2026-01-01' = if (enabled) {
  parent: stagingVnet
  name: 'peer-mobius77-staging-to-postgres'
  properties: {
    allowForwardedTraffic: false
    allowGatewayTransit: false
    allowVirtualNetworkAccess: true
    remoteVirtualNetwork: { id: regionalVnet.id }
    useRemoteGateways: false
  }
}

resource postgresToStaging 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2026-01-01' = if (enabled) {
  parent: regionalVnet
  name: 'peer-mobius77-postgres-to-staging'
  properties: {
    allowForwardedTraffic: false
    allowGatewayTransit: false
    allowVirtualNetworkAccess: true
    remoteVirtualNetwork: { id: stagingVnet.id }
    useRemoteGateways: false
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: privateDnsZoneName
  location: 'global'
  tags: lifecycleTags
}

resource postgresDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: privateDnsZone
  name: 'link-mobius77-postgres'
  location: 'global'
  tags: lifecycleTags
  properties: { registrationEnabled: false, virtualNetwork: { id: regionalVnet.id } }
}

resource stagingDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: privateDnsZone
  name: 'link-mobius77-staging-postgres'
  location: 'global'
  tags: lifecycleTags
  properties: { registrationEnabled: false, virtualNetwork: { id: stagingVnet.id } }
}

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = if (enabled) {
  name: serverName
  location: location
  tags: lifecycleTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${databaseAdministratorIdentityId}': {} }
  }
  sku: { name: 'Standard_D2ds_v5', tier: 'GeneralPurpose' }
  properties: {
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenantId }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'ZoneRedundant' }
    network: {
      delegatedSubnetResourceId: resourceId(
        'Microsoft.Network/virtualNetworks/subnets',
        regionalVnetName,
        delegatedSubnetName
      )
      privateDnsZoneArmResourceId: privateDnsZone.id
      publicNetworkAccess: 'Disabled'
    }
    storage: { autoGrow: 'Disabled', storageSizeGB: 64, tier: 'P4' }
    version: '17'
  }
  dependsOn: [postgresDnsLink, stagingDnsLink, stagingToPostgres, postgresToStaging]
}

resource administrator 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = if (enabled) {
  parent: server
  name: databaseAdministratorPrincipalId
  properties: {
    objectId: databaseAdministratorPrincipalId
    principalName: databaseAdministratorName
    principalType: 'ServicePrincipal'
    tenantId: tenantId
  }
}

resource applicationDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = if (enabled) {
  parent: server
  name: 'opencanvas'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [administrator]
}

output serverId string = enabled ? server.id : ''
output serverFqdn string = enabled ? server.properties.fullyQualifiedDomainName : ''
output serverPort int = 5432
output databaseName string = 'opencanvas'
output privateDnsZoneId string = enabled ? privateDnsZone.id : ''
output selectedLocation string = location
output publicNetworkAccess string = 'Disabled'
output highAvailability string = highAvailability
output configuredMajorVersion int = majorVersion
output configuredServerSku string = serverSku
output configuredStorageGiB int = storageGiB
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
