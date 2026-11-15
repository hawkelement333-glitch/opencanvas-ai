// M78-D-001 only. The independently armed cleanup controller is outside this group.
// Foundation creates no execution; workload requires the retained image's digest
// and the Defender-created scanner binding discovered from this account.
targetScope = 'resourceGroup'

@allowed(['canadacentral'])
param location string = 'canadacentral'
@minLength(10)
@maxLength(10)
param resourceNameSuffix string
param lifecycleTags object
@allowed(['foundation', 'workload'])
param deploymentStage string = 'foundation'
// Read back from foundation identityBindings; never substitute another principal.
param bootstrapPrincipalId string = ''
param storageDataScannerResourceId string = ''
param imageDigest string = ''
param probePythonSource string = ''
param probeSourceSha256 string = ''
param bootstrapPythonSource string = ''
param bootstrapSourceSha256 string = ''
param probeEnvironment array = []
param bootstrapEnvironment array = []
@secure()
param probeSecrets object = {}

var prefix = 'm78o-${resourceNameSuffix}'
var workloadEnabled = deploymentStage == 'workload'
var dnsTags = toObject(filter(items(lifecycleTags), tag => tag.key != 'mobius.expiry'), tag => tag.key, tag => tag.value)
var blobActions = 'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/'
var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var logReaderRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')
var roleSpecs = [
  { key: 'api-upload', actions: ['${blobActions}read', '${blobActions}add/action', '${blobActions}write'] }
  { key: 'api-download', actions: ['${blobActions}read'] }
  { key: 'worker-quarantine', actions: ['${blobActions}read', '${blobActions}tags/read', '${blobActions}delete', '${blobActions}deleteBlobVersion/action'] }
  { key: 'worker-promote', actions: ['${blobActions}read', '${blobActions}add/action', '${blobActions}write', '${blobActions}delete', '${blobActions}deleteBlobVersion/action'] }
  // Temporary isolated proof authority: exact-version recovery/deletion, no tag writes.
  { key: 'probe-lifecycle', actions: ['${blobActions}read', '${blobActions}add/action', '${blobActions}write', '${blobActions}delete', '${blobActions}deleteBlobVersion/action', '${blobActions}permanentDelete/action', '${blobActions}tags/read'] }
]
var containerNames = ['quarantine', 'clean', 'rejected', 'retained']
var identityNames = ['bootstrap', 'api', 'worker', 'probe']
var dnsNames = [
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.azurecr.io'
  'privatelink.monitor.azure.com'
  'privatelink.oms.opinsights.azure.com'
  'privatelink.ods.opinsights.azure.com'
  'privatelink.agentsvc.azure-automation.net'
  '${prefix}.postgres.database.azure.com'
]
var sourceVerifier = 'import hashlib,hmac,os,sys; s=os.environ["M78_EXECUTION_SOURCE"]; hmac.compare_digest(hashlib.sha256(s.encode("utf-8")).hexdigest(),os.environ["M78_EXECUTION_SHA256"]) or sys.exit("execution source hash mismatch"); exec(compile(s,"<m78-d001-bound-probe>","exec"))'

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    addressSpace: { addressPrefixes: ['10.79.0.0/16'] }
    subnets: [
      {
        name: 'postgres'
        properties: {
          addressPrefix: '10.79.1.0/24'
          delegations: [{ name: 'postgres', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }]
        }
      }
      {
        name: 'container-apps'
        properties: {
          addressPrefix: '10.79.4.0/23'
          delegations: [{ name: 'container-apps', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      { name: 'private-endpoints', properties: { addressPrefix: '10.79.8.0/24', privateEndpointNetworkPolicies: 'Disabled' } }
    ]
  }
}

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = [for identityName in identityNames: {
  name: 'id-${prefix}-${identityName}'
  location: location
  tags: lifecycleTags
}]

resource dnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for dnsName in dnsNames: {
  name: dnsName
  location: 'global'
  tags: dnsTags
}]

resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (dnsName, index) in dnsNames: {
  parent: dnsZones[index]
  name: prefix
  location: 'global'
  tags: dnsTags
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}]

resource storage 'Microsoft.Storage/storageAccounts@2025-06-01' = {
  name: 'stm78o${resourceNameSuffix}'
  location: location
  tags: lifecycleTags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: []
      virtualNetworkRules: []
      resourceAccessRules: empty(storageDataScannerResourceId) ? [] : [{ resourceId: storageDataScannerResourceId, tenantId: tenant().tenantId }]
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' = {
  parent: storage
  name: 'default'
  properties: {
    isVersioningEnabled: true
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
    deleteRetentionPolicy: { enabled: true, days: 7, allowPermanentDelete: true }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = [for containerName in containerNames: {
  parent: blobService
  name: containerName
  properties: { publicAccess: 'None' }
}]

// Singleton aliases keep extension-resource scope inference out of the container
// copy loop. They declare no additional resources or permissions.
resource quarantineScope 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' existing = {
  parent: blobService
  name: 'quarantine'
}
resource cleanScope 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' existing = {
  parent: blobService
  name: 'clean'
}

resource defender 'Microsoft.Security/defenderForStorageSettings@2025-06-01' = {
  scope: storage
  name: 'current'
  properties: {
    isEnabled: true
    overrideSubscriptionLevelSettings: true
    malwareScanning: {
      blobScanResultsOptions: 'blobIndexTags'
      onUpload: { isEnabled: true, capGBPerMonth: 1 }
    }
    sensitiveDataDiscovery: { isEnabled: false }
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    retentionInDays: 30
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery: 'Disabled'
    sku: { name: 'PerGB2018' }
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource scanDiagnostic 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: defender
  name: 'scan-results'
  properties: {
    workspaceId: logs.id
    logs: [{ category: 'ScanResults', enabled: true }]
  }
}

resource monitorScope 'Microsoft.Insights/privateLinkScopes@2021-09-01' = {
  name: 'ampls-${prefix}'
  location: 'global'
  tags: lifecycleTags
  properties: {
    accessModeSettings: { exclusions: [], ingestionAccessMode: 'PrivateOnly', queryAccessMode: 'PrivateOnly' }
  }
}

resource scopedWorkspace 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = {
  parent: monitorScope
  name: logs.name
  properties: { linkedResourceId: logs.id }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'crm78o${resourceNameSuffix}'
  location: location
  tags: lifecycleTags
  sku: { name: 'Premium' }
  properties: { adminUserEnabled: false, publicNetworkAccess: 'Disabled', zoneRedundancy: 'Disabled' }
}

var endpoints = [
  { key: 'blob', id: storage.id, group: 'blob', zones: [0] }
  { key: 'registry', id: registry.id, group: 'registry', zones: [1] }
  { key: 'monitor', id: monitorScope.id, group: 'azuremonitor', zones: [2, 3, 4, 5, 0] }
]
resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-10-01' = [for endpoint in endpoints: {
  name: 'pe-${prefix}-${endpoint.key}'
  location: location
  tags: lifecycleTags
  properties: {
    subnet: { id: '${network.id}/subnets/private-endpoints' }
    privateLinkServiceConnections: [{ name: endpoint.key, properties: { privateLinkServiceId: endpoint.id, groupIds: [endpoint.group] } }]
  }
  dependsOn: [scopedWorkspace]
}]

resource endpointDnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = [for (endpoint, index) in endpoints: {
  parent: privateEndpoints[index]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [for zoneIndex in endpoint.zones: { name: 'zone-${zoneIndex}', properties: { privateDnsZoneId: dnsZones[zoneIndex].id } }]
  }
  dependsOn: [dnsLinks]
}]

resource storageRoles 'Microsoft.Authorization/roleDefinitions@2022-04-01' = [for role in roleSpecs: {
  name: guid(resourceGroup().id, role.key)
  properties: {
    roleName: '${prefix}-${role.key}'
    description: 'M78-D-001 isolated managed-object proof, no scanner result write authority.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{ actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read'], notActions: [], dataActions: role.actions, notDataActions: [] }]
  }
}]

resource apiUploadRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: quarantineScope
  name: guid(containers[0].id, identities[1].id, storageRoles[0].id)
  properties: { principalId: identities[1].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: storageRoles[0].id }
}
resource apiDownloadRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cleanScope
  name: guid(containers[1].id, identities[1].id, storageRoles[1].id)
  properties: { principalId: identities[1].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: storageRoles[1].id }
}
resource workerQuarantineRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: quarantineScope
  name: guid(containers[0].id, identities[2].id, storageRoles[2].id)
  properties: { principalId: identities[2].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: storageRoles[2].id }
}
resource workerPromotionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cleanScope
  name: guid(containers[1].id, identities[2].id, storageRoles[3].id)
  properties: { principalId: identities[2].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: storageRoles[3].id }
}
resource probeLifecycleRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (containerName, index) in containerNames: {
  scope: containers[index]
  name: guid(containers[index].id, identities[3].id, storageRoles[4].id)
  properties: { principalId: identities[3].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: storageRoles[4].id }
}]
resource logReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for identityIndex in [2, 3]: {
  scope: logs
  name: guid(logs.id, identities[identityIndex].id, logReaderRoleId)
  properties: { principalId: identities[identityIndex].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: logReaderRoleId }
}]
resource registryReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for identityIndex in [0, 3]: {
  scope: registry
  name: guid(registry.id, identities[identityIndex].id, acrPullRoleId)
  properties: { principalId: identities[identityIndex].properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: acrPullRoleId }
}]

// Transaction dependency only: no PG-E01..PG-E04 or TI-E01 acceptance is rerun.
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'pg-${prefix}'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[0].id}': {} } }
  sku: { name: 'Standard_D2ds_v4', tier: 'GeneralPurpose' }
  properties: {
    createMode: 'Default'
    version: '17'
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenant().tenantId }
    highAvailability: { mode: 'Disabled' }
    storage: { storageSizeGB: 64, autoGrow: 'Disabled', tier: 'P6' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    network: { delegatedSubnetResourceId: '${network.id}/subnets/postgres', privateDnsZoneArmResourceId: dnsZones[6].id, publicNetworkAccess: 'Disabled' }
  }
  dependsOn: [dnsLinks]
}
resource postgresAdministrator 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = if (workloadEnabled) {
  parent: postgres
  name: bootstrapPrincipalId
  properties: { principalName: identities[0].name, principalType: 'ServicePrincipal', tenantId: tenant().tenantId }
}
resource vectorExtension 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { source: 'user-override', value: 'vector' }
  dependsOn: [postgresAdministrator]
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'opencanvas_objects'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [vectorExtension]
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: 'cae-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    appLogsConfiguration: { destination: 'log-analytics', logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey } }
    vnetConfiguration: { infrastructureSubnetId: '${network.id}/subnets/container-apps', internal: true }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    zoneRedundant: false
  }
  dependsOn: [endpointDnsGroups]
}

var commonEnvironment = [
  { name: 'OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID', value: logs.properties.customerId }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT', value: 'https://api.loganalytics.azure.com' }
  { name: 'OPENCANVAS_DATABASE_HOST', value: postgres.properties.fullyQualifiedDomainName }
  { name: 'OPENCANVAS_DATABASE_NAME', value: database.name }
  { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
  { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
  { name: 'OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL', value: identities[3].name }
  { name: 'OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID', value: identities[3].properties.principalId }
  { name: 'OPENCANVAS_OBJECT_PROBE_BOOTSTRAP_PRINCIPAL_ID', value: identities[0].properties.principalId }
  { name: 'OPENCANVAS_OBJECT_PROBE_API_CLIENT_ID', value: identities[1].properties.clientId }
  { name: 'OPENCANVAS_OBJECT_PROBE_WORKER_CLIENT_ID', value: identities[2].properties.clientId }
  { name: 'OPENCANVAS_OBJECT_PROBE_RECOVERY_CLIENT_ID', value: identities[3].properties.clientId }
  { name: 'OPENCANVAS_OBJECT_PROBE_SHA256', value: probeSourceSha256 }
]
resource bootstrapJob 'Microsoft.App/jobs@2025-01-01' = if (workloadEnabled) {
  name: 'caj-${prefix}-bootstrap'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[0].id}': {} } }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaRetryLimit: 0
      replicaTimeout: 1800
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ identity: identities[0].id, server: registry.properties.loginServer }]
    }
    template: {
      containers: [{
        name: 'bootstrap'
        image: '${registry.properties.loginServer}/opencanvas-api@${imageDigest}'
        command: ['python']
        args: ['-c', sourceVerifier]
        env: concat(commonEnvironment, [
          { name: 'M78_EXECUTION_SOURCE', value: bootstrapPythonSource }
          { name: 'M78_EXECUTION_SHA256', value: bootstrapSourceSha256 }
          { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: identities[0].properties.clientId }
          { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${identities[0].name}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas_objects' }
          { name: 'OPENCANVAS_DATABASE_ROLE', value: 'migration' }
          { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: identities[0].properties.clientId }
        ], bootstrapEnvironment)
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
    }
  }
  dependsOn: [registryReaders]
}
resource probeJob 'Microsoft.App/jobs@2025-01-01' = if (workloadEnabled) {
  name: 'caj-${prefix}-probe'
  location: location
  tags: lifecycleTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identities[1].id}': {}, '${identities[2].id}': {}, '${identities[3].id}': {} }
  }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      secrets: [for secret in items(probeSecrets): { name: secret.key, value: secret.value }]
      replicaRetryLimit: 0
      replicaTimeout: 4200
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ identity: identities[3].id, server: registry.properties.loginServer }]
    }
    template: {
      containers: [{
        name: 'managed-objects'
        image: '${registry.properties.loginServer}/opencanvas-api@${imageDigest}'
        command: ['python']
        args: ['-c', sourceVerifier]
        env: concat(commonEnvironment, [
          { name: 'M78_EXECUTION_SOURCE', value: probePythonSource }
          { name: 'M78_EXECUTION_SHA256', value: probeSourceSha256 }
          { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: identities[3].properties.clientId }
          { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${identities[3].name}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas_objects' }
          { name: 'OPENCANVAS_DATABASE_ROLE', value: 'api' }
          { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: identities[3].properties.clientId }
        ], probeEnvironment)
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
    }
  }
  dependsOn: [registryReaders, apiUploadRole, apiDownloadRole, workerQuarantineRole, workerPromotionRole, probeLifecycleRoles, logReaders, endpointDnsGroups, scanDiagnostic]
}

// Resource identities only: no tokens, workspace keys, principal manifest or source.
output storageAccountId string = storage.id
output storageAccountUrl string = storage.properties.primaryEndpoints.blob
output blobServiceId string = blobService.id
output containerIds array = [for (containerName, index) in containerNames: containers[index].id]
output defenderSettingsId string = defender.id
output scanResultsDiagnosticId string = scanDiagnostic.id
output monitorScopeId string = monitorScope.id
output virtualNetworkId string = network.id
output workspaceId string = logs.id
output workspaceCustomerId string = logs.properties.customerId
output registryId string = registry.id
output registryLoginServer string = registry.properties.loginServer
output managedEnvironmentId string = managedEnvironment.id
output postgresServerId string = postgres.id
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output databaseName string = database.name
output identityBindings array = [for (identityName, index) in identityNames: { role: identityName, name: identities[index].name, id: identities[index].id, clientId: identities[index].properties.clientId, principalId: identities[index].properties.principalId }]
output customRoleDefinitionIds array = [for (role, index) in roleSpecs: storageRoles[index].id]
// Build each extension ID with its explicit container scope. Referencing the
// assignment .id leaks the container resource loop's copyIndex into this output.
output serviceStorageRoleAssignmentIds array = [
  extensionResourceId(containers[0].id, 'Microsoft.Authorization/roleAssignments', apiUploadRole.name)
  extensionResourceId(containers[1].id, 'Microsoft.Authorization/roleAssignments', apiDownloadRole.name)
  extensionResourceId(containers[0].id, 'Microsoft.Authorization/roleAssignments', workerQuarantineRole.name)
  extensionResourceId(containers[1].id, 'Microsoft.Authorization/roleAssignments', workerPromotionRole.name)
]
output probeStorageRoleAssignmentIds array = [for (containerName, index) in containerNames: probeLifecycleRoles[index].id]
output privateEndpointIds array = [for (endpoint, index) in endpoints: privateEndpoints[index].id]
output privateDnsZoneIds array = [for (dnsName, index) in dnsNames: dnsZones[index].id]
output bootstrapJobName string = workloadEnabled ? bootstrapJob.name : ''
output probeJobName string = workloadEnabled ? probeJob.name : ''
