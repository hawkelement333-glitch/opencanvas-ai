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
param defaultDomain string = ''
param staticIp string = ''
param virtualNetworkId string = ''
param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled

resource containerAppsPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: defaultDomain
  location: 'global'
  tags: lifecycleTags
}

resource containerAppsDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: containerAppsPrivateDnsZone
  name: 'link-mobius77-containerapps'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource containerAppsWildcardRecord 'Microsoft.Network/privateDnsZones/A@2024-06-01' = if (enabled) {
  parent: containerAppsPrivateDnsZone
  name: '*'
  properties: {
    TTL: 60
    ARecords: [
      {
        ipv4Address: staticIp
      }
    ]
  }
}

output moduleName string = 'container-apps-dns'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output managedBindingDeploymentEnabled bool = enabled
output privateDnsZoneId string = enabled ? containerAppsPrivateDnsZone.id : ''
output privateDnsLinkId string = enabled ? containerAppsDnsLink.id : ''
output privateDnsWildcardRecordId string = enabled ? containerAppsWildcardRecord.id : ''
