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
  'southcentralus'
])
param location string = 'southcentralus'

param privateEndpointSubnetId string = ''
param virtualNetworkId string = ''
param apiIdentityPrincipalId string = ''
param workerIdentityPrincipalId string = ''
param lifecycleTags object = {}

@allowed([
  'Standard_LRS'
])
param storageSku string = 'Standard_LRS'

@allowed([
  'StorageV2'
])
param storageKind string = 'StorageV2'

@allowed([
  false
])
param sharedKeyAccess bool = false

@allowed([
  false
])
param anonymousAccess bool = false

@allowed([
  false
])
param publicNetworkAccess bool = false

@allowed([
  true
])
param versioningEnabled bool = true

@minValue(1)
@maxValue(1)
param defenderMonthlyCapGiB int = 1

@minValue(25)
@maxValue(25)
param scannerExerciseObjectCap int = 25

@minValue(26214400)
@maxValue(26214400)
param scannerExerciseBytesCap int = 26214400

@minValue(134217728)
@maxValue(134217728)
param totalSyntheticUploadBytesCap int = 134217728

@allowed([
  false
])
param scannerResultBridgeResolved bool = false

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var storageAccountName = 'stmobius7711564669'
var privateDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'
var blobDataContributorRole = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' = if (enabled) {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  tags: lifecycleTags
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' = if (enabled) {
  parent: storageAccount
  name: 'default'
  properties: {
    containerDeleteRetentionPolicy: {
      days: 7
      enabled: true
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      days: 7
      enabled: true
    }
    isVersioningEnabled: true
  }
}

resource quarantine 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = if (enabled) {
  parent: blobService
  name: 'quarantine'
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
    publicAccess: 'None'
  }
}

resource clean 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = if (enabled) {
  parent: blobService
  name: 'clean'
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
    publicAccess: 'None'
  }
}

resource rejected 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = if (enabled) {
  parent: blobService
  name: 'rejected'
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
    publicAccess: 'None'
  }
}

resource retained 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = if (enabled) {
  parent: blobService
  name: 'retained'
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
    publicAccess: 'None'
  }
}

resource apiBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(storageAccount.id, apiIdentityPrincipalId, blobDataContributorRole)
  scope: storageAccount
  properties: {
    principalId: apiIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRole)
  }
}

resource workerBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(storageAccount.id, workerIdentityPrincipalId, blobDataContributorRole)
  scope: storageAccount
  properties: {
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRole)
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: privateDnsZoneName
  location: 'global'
  tags: lifecycleTags
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: privateDnsZone
  name: 'link-mobius77-storage'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-10-01' = if (enabled) {
  name: 'pe-mobius77-storage'
  location: location
  tags: lifecycleTags
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          groupIds: [
            'blob'
          ]
          privateLinkServiceId: storageAccount.id
        }
      }
    ]
    subnet: {
      id: privateEndpointSubnetId
    }
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = if (enabled) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
  dependsOn: [dnsLink]
}

output moduleName string = 'storage-scanner'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output managedBindingDeploymentEnabled bool = enabled
output storageSku string = storageSku
output storageKind string = storageKind
output sharedKeyAccess bool = sharedKeyAccess
output anonymousAccess bool = anonymousAccess
output publicNetworkAccess bool = publicNetworkAccess
output versioningEnabled bool = versioningEnabled
output defenderMonthlyCapGiB int = defenderMonthlyCapGiB
output scannerExerciseObjectCap int = scannerExerciseObjectCap
output scannerExerciseBytesCap int = scannerExerciseBytesCap
output totalSyntheticUploadBytesCap int = totalSyntheticUploadBytesCap
output scannerResultBridgeResolved bool = scannerResultBridgeResolved
output storageAccountId string = enabled ? storageAccount.id : ''
output storageAccountUrl string = enabled ? storageAccount.properties.primaryEndpoints.blob : ''
output containerNames array = [quarantine.name, clean.name, rejected.name, retained.name]
output publicAccessEnabled bool = false
