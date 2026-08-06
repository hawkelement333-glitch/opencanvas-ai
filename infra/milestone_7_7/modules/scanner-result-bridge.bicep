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

param scannerResultBridgeResolved bool

param scannerResultBridgeState string

param scannerResultBridgeEvidenceIntegrity string
@allowed([
  'southcentralus'
])
param location string = 'southcentralus'
param storageAccountName string = ''
param privateEndpointSubnetId string = ''
param virtualNetworkId string = ''
param workerIdentityPrincipalId string = ''
param lifecycleTags object = {}

var workerIdentityBound = !empty(workerIdentityPrincipalId)
var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled && scannerResultBridgeResolved && scannerResultBridgeState == 'RESOLVED' && length(scannerResultBridgeEvidenceIntegrity) == 64 && workerIdentityBound
var queueDnsZoneName = 'privatelink.queue.${environment().suffixes.storage}'
var eventGridSenderRole = 'Storage Queue Data Message Sender'
var workerProcessorRole = 'Storage Queue Data Message Processor'

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' existing = if (enabled) {
  name: storageAccountName
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2025-06-01' = if (enabled) {
  parent: storageAccount
  name: 'default'
}

resource scannerResultsQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-06-01' = if (enabled) {
  parent: queueService
  name: 'scanner-results'
}

resource scannerDeadLetterQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-06-01' = if (enabled) {
  parent: queueService
  name: 'scanner-results-deadletter'
}

resource queueDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: queueDnsZoneName
  location: 'global'
  tags: lifecycleTags
}

resource queueDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: queueDnsZone
  name: 'link-mobius77-storage-queue'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: virtualNetworkId }
  }
}

resource queuePrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-10-01' = if (enabled) {
  name: 'pe-mobius77-storage-queue'
  location: location
  tags: lifecycleTags
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'queue'
        properties: {
          groupIds: ['queue']
          privateLinkServiceId: storageAccount.id
        }
      }
    ]
    subnet: { id: privateEndpointSubnetId }
  }
}

resource queueDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = if (enabled) {
  parent: queuePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'queue', properties: { privateDnsZoneId: queueDnsZone.id } }
    ]
  }
  dependsOn: [queueDnsLink]
}

// Live provider event shape, Event Grid delivery identity, and role-definition IDs
// remain explicit validation prerequisites; this module is inert until the local
// resolver produces RESOLVED evidence and a later authorized ledger binds it.
output moduleName string = 'scanner-result-bridge'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output bridgeResolved bool = enabled
output transport string = 'event-grid-system-topic-to-private-storage-queue'
output provider string = 'microsoft-defender-for-storage-malware-scanning'
output eventGridSenderRole string = eventGridSenderRole
output workerProcessorRole string = workerProcessorRole
output queueNames array = [scannerResultsQueue.name, scannerDeadLetterQueue.name]
