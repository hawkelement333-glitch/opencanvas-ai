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

param targetResourceGroupId string = ''
param privateEndpointSubnetId string = ''
param virtualNetworkId string = ''
param logAnalyticsWorkspaceId string = ''
param storageDataScannerResourceId string = ''
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

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var storageAccountName = 'stmobius7711564669'
var privateDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'
var apiQuarantineRoleId = '43c7bdad-b8f9-4d4b-9881-ae8af70cf269'
var apiCleanReaderRoleId = 'a59d0f11-7f62-4699-97d9-6c8565ba77a4'
var workerQuarantineReaderRoleId = '292f18b2-0b41-4a86-a4af-46cd22d2e52e'
var workerCleanWriterRoleId = '6ecfca2a-29a1-4802-a236-706d77995e21'

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' = if (enabled) {
  name: storageAccountName
  location: location
  kind: storageKind
  sku: {
    name: storageSku
  }
  tags: lifecycleTags
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
      ipRules: []
      resourceAccessRules: [
        {
          resourceId: storageDataScannerResourceId
          tenantId: tenant().tenantId
        }
      ]
      virtualNetworkRules: []
    }
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
      allowPermanentDelete: true
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

resource defenderForStorage 'Microsoft.Security/defenderForStorageSettings@2025-06-01' = if (enabled) {
  scope: storageAccount
  name: 'current'
  properties: {
    isEnabled: true
    malwareScanning: {
      blobScanResultsOptions: 'BlobIndexTags'
      onUpload: {
        capGBPerMonth: defenderMonthlyCapGiB
        isEnabled: true
      }
    }
    overrideSubscriptionLevelSettings: true
    sensitiveDataDiscovery: {
      isEnabled: false
    }
  }
}

resource scanResultsDiagnostic 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enabled) {
  scope: defenderForStorage
  name: 'mobius77-defender-scan-results'
  properties: {
    logs: [
      {
        category: 'ScanResults'
        enabled: true
      }
    ]
    metrics: []
    workspaceId: logAnalyticsWorkspaceId
  }
}

resource apiQuarantineRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (enabled) {
  name: apiQuarantineRoleId
  properties: {
    assignableScopes: [targetResourceGroupId]
    description: 'Milestone 7.7 API immutable quarantine upload without blob-tag access.'
    permissions: [
      {
        actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read']
        dataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
        ]
        notActions: []
        notDataActions: []
      }
    ]
    roleName: 'Mobius77 API Quarantine Writer'
    type: 'CustomRole'
  }
}

resource apiCleanReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (enabled) {
  name: apiCleanReaderRoleId
  properties: {
    assignableScopes: [targetResourceGroupId]
    description: 'Milestone 7.7 API exact clean-blob reader without blob-tag access.'
    permissions: [
      {
        actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read']
        dataActions: ['Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read']
        notActions: []
        notDataActions: []
      }
    ]
    roleName: 'Mobius77 API Clean Reader'
    type: 'CustomRole'
  }
}

resource workerQuarantineReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (enabled) {
  name: workerQuarantineReaderRoleId
  properties: {
    assignableScopes: [targetResourceGroupId]
    description: 'Milestone 7.7 worker immutable quarantine and blob-tag reader.'
    permissions: [
      {
        actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read']
        dataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read'
        ]
        notActions: []
        notDataActions: []
      }
    ]
    roleName: 'Mobius77 Worker Quarantine Evidence Reader'
    type: 'CustomRole'
  }
}

resource workerCleanWriterRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (enabled) {
  name: workerCleanWriterRoleId
  properties: {
    assignableScopes: [targetResourceGroupId]
    description: 'Milestone 7.7 worker immutable clean promotion without blob-tag access.'
    permissions: [
      {
        actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read']
        dataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
        ]
        notActions: []
        notDataActions: []
      }
    ]
    roleName: 'Mobius77 Worker Clean Promoter'
    type: 'CustomRole'
  }
}

resource apiQuarantineAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(quarantine.id, apiIdentityPrincipalId, apiQuarantineRole.id)
  scope: quarantine
  properties: {
    principalId: apiIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: apiQuarantineRole.id
  }
}

resource apiCleanAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(clean.id, apiIdentityPrincipalId, apiCleanReaderRole.id)
  scope: clean
  properties: {
    principalId: apiIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: apiCleanReaderRole.id
  }
}

resource workerQuarantineAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(quarantine.id, workerIdentityPrincipalId, workerQuarantineReaderRole.id)
  scope: quarantine
  properties: {
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: workerQuarantineReaderRole.id
  }
}

resource workerCleanAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(clean.id, workerIdentityPrincipalId, workerCleanWriterRole.id)
  scope: clean
  properties: {
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: workerCleanWriterRole.id
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
          groupIds: ['blob']
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
output storageAccountId string = enabled ? storageAccount.id : ''
output storageAccountName string = enabled ? storageAccount.name : ''
output storageAccountUrl string = enabled ? storageAccount.properties.primaryEndpoints.blob : ''
output quarantineContainerId string = enabled ? quarantine.id : ''
output containerNames array = [quarantine.name, clean.name, rejected.name, retained.name]
output defenderForStorageId string = enabled ? defenderForStorage.id : ''
output scanResultsDiagnosticId string = enabled ? scanResultsDiagnostic.id : ''
output workerTagWriteAuthorized bool = false
output apiTagWriteAuthorized bool = false
output publicAccessEnabled bool = false
