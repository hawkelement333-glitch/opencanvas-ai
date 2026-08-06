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
param scannerProofDeploymentEnabled bool = false

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param targetResourceGroupId string = ''
param storageAccountName string = ''
param storageAccountUrl string = ''
param privateEndpointSubnetId string = ''
param virtualNetworkId string = ''
param logAnalyticsWorkspaceName string = 'law-mobius77-staging'
param logAnalyticsWorkspaceCustomerId string = ''
param workerIdentityId string = ''
param workerIdentityClientId string = ''
param workerIdentityPrincipalId string = ''
param managedEnvironmentId string = ''
param registryLoginServer string = ''
param apiImageDigest string = ''
@minLength(0)
@maxLength(64)
param proofCanarySeed string = ''
param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var proofEnabled = enabled && scannerProofDeploymentEnabled && !empty(apiImageDigest) && length(proofCanarySeed) == 64
var amplsName = 'ampls-mobius77-staging'
var logAnalyticsReaderRoleId = '73c42c96-874c-492b-b04d-ab87d138a893'
var proofRoleId = '7d78ed8f-4b48-4e74-bb95-f0fcfe811897'

resource workspace 'Microsoft.OperationalInsights/workspaces@2026-03-01' existing = if (enabled) {
  name: logAnalyticsWorkspaceName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' existing = if (enabled) {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' existing = if (enabled) {
  parent: storageAccount
  name: 'default'
}

resource quarantine 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' existing = if (enabled) {
  parent: blobService
  name: 'quarantine'
}

resource privateLinkScope 'Microsoft.Insights/privateLinkScopes@2021-09-01' = if (enabled) {
  name: amplsName
  location: 'global'
  tags: lifecycleTags
  properties: {
    accessModeSettings: {
      exclusions: []
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource scopedWorkspace 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = if (enabled) {
  parent: privateLinkScope
  name: 'law-mobius77-staging'
  properties: {
    linkedResourceId: workspace.id
  }
}

resource monitorPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-10-01' = if (enabled) {
  name: 'pe-mobius77-azure-monitor'
  location: location
  tags: lifecycleTags
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'azuremonitor'
        properties: {
          groupIds: ['azuremonitor']
          privateLinkServiceId: privateLinkScope.id
        }
      }
    ]
    subnet: {
      id: privateEndpointSubnetId
    }
  }
}

resource monitorZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: 'privatelink.monitor.azure.com'
  location: 'global'
  tags: lifecycleTags
}

resource omsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: 'privatelink.oms.opinsights.azure.com'
  location: 'global'
  tags: lifecycleTags
}

resource odsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: 'privatelink.ods.opinsights.azure.com'
  location: 'global'
  tags: lifecycleTags
}

resource agentZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: 'privatelink.agentsvc.azure-automation.net'
  location: 'global'
  tags: lifecycleTags
}

resource blobZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = if (enabled) {
  name: 'privatelink.blob.${environment().suffixes.storage}'
}

resource monitorZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: monitorZone
  name: 'link-mobius77-monitor'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: virtualNetworkId }
  }
}

resource omsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: omsZone
  name: 'link-mobius77-oms'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: virtualNetworkId }
  }
}

resource odsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: odsZone
  name: 'link-mobius77-ods'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: virtualNetworkId }
  }
}

resource agentZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: agentZone
  name: 'link-mobius77-agent'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: virtualNetworkId }
  }
}

resource monitorDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = if (enabled) {
  parent: monitorPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'monitor', properties: { privateDnsZoneId: monitorZone.id } }
      { name: 'oms', properties: { privateDnsZoneId: omsZone.id } }
      { name: 'ods', properties: { privateDnsZoneId: odsZone.id } }
      { name: 'agent', properties: { privateDnsZoneId: agentZone.id } }
      { name: 'blob', properties: { privateDnsZoneId: blobZone.id } }
    ]
  }
  dependsOn: [monitorZoneLink, omsZoneLink, odsZoneLink, agentZoneLink, scopedWorkspace]
}

resource workerLogReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(workspace.id, workerIdentityPrincipalId, logAnalyticsReaderRoleId)
  scope: workspace
  properties: {
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      logAnalyticsReaderRoleId
    )
  }
}

resource proofRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (proofEnabled) {
  name: proofRoleId
  properties: {
    assignableScopes: [targetResourceGroupId]
    description: 'Temporary Milestone 7.7 exact canary upload and deletion authority.'
    permissions: [
      {
        actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read']
        dataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/deleteBlobVersion/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/permanentDelete/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read'
        ]
        notActions: []
        notDataActions: []
      }
    ]
    roleName: 'Mobius77 Temporary Scanner Bridge Probe'
    type: 'CustomRole'
  }
}

resource proofRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (proofEnabled) {
  name: guid(quarantine.id, workerIdentityPrincipalId, proofRole.id)
  scope: quarantine
  properties: {
    principalId: workerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: proofRole.id
  }
}

resource proofJob 'Microsoft.App/jobs@2025-01-01' = if (proofEnabled) {
  name: 'caj-mobius77-scanner-proof'
  location: location
  tags: lifecycleTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workerIdentityId}': {}
    }
  }
  properties: {
    configuration: {
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          identity: workerIdentityId
          server: registryLoginServer
        }
      ]
      replicaRetryLimit: 0
      replicaTimeout: 3600
      triggerType: 'Manual'
    }
    environmentId: managedEnvironmentId
    template: {
      containers: [
        {
          args: [
            '-m'
            'scripts.scanner_bridge_probe'
            '--max-attempts'
            '60'
            '--delay-seconds'
            '30'
          ]
          command: ['python']
          env: [
            { name: 'OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL', value: storageAccountUrl }
            { name: 'OPENCANVAS_AZURE_QUARANTINE_CONTAINER', value: 'quarantine' }
            { name: 'OPENCANVAS_AZURE_CLEAN_CONTAINER', value: 'clean' }
            { name: 'OPENCANVAS_AZURE_REJECTED_CONTAINER', value: 'rejected' }
            { name: 'OPENCANVAS_AZURE_RETAINED_CONTAINER', value: 'retained' }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            {
              name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID'
              value: logAnalyticsWorkspaceCustomerId
            }
            { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT', value: 'https://api.loganalytics.azure.com' }
            { name: 'OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED', value: proofCanarySeed }
          ]
          image: apiImageDigest
          name: 'scanner-bridge-proof'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [proofRoleAssignment, workerLogReader, monitorDnsZoneGroup]
}

output moduleName string = 'scanner-result-bridge'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output bridgeFoundationEnabled bool = enabled
output proofDeploymentEnabled bool = proofEnabled
output transport string = 'private-blob-tags-plus-ampls-log-analytics-pull'
output provider string = 'microsoft-defender-for-storage-malware-scanning'
output privateLinkScopeId string = enabled ? privateLinkScope.id : ''
output privateEndpointId string = enabled ? monitorPrivateEndpoint.id : ''
output proofJobName string = proofEnabled ? proofJob.name : ''
output proofJobId string = proofEnabled ? proofJob.id : ''
output temporaryProofRoleId string = proofEnabled ? proofRole.id : ''
output temporaryProofRoleAssignmentId string = proofEnabled ? proofRoleAssignment.id : ''
output workerTagWriteAuthorized bool = false
output customEventGridTopicCreated bool = false
output eventSubscriptionCreated bool = false
output queueCreated bool = false
