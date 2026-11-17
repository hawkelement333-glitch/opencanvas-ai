// Isolated, approval-bound pilot validation. This template does not run a proof.
targetScope = 'resourceGroup'

@allowed(['eastus', 'canadacentral'])
param location string = 'eastus'
@allowed(['eastus', 'canadacentral'])
param redisLocation string = location
@minLength(10)
@maxLength(10)
param suffix string
param lifecycleTags object
@allowed(['foundation', 'jobs', 'application'])
param stage string = 'foundation'
param enableExternalDelivery bool = false
param enableOperatorAccess bool = false
param operatorVpnAudienceAppId string = ''
@minValue(0)
param apiRequestConcurrencyLimit int = 0
param storageDataScannerResourceId string = ''
param bootstrapPrincipalId string = ''
param catalog object
param operatorPrincipalId string
// Separate administrator export identity from the revocable query test user.
param operatorExportPrincipalId string = operatorPrincipalId
param operatorPrincipalType string = 'User'
param campaignId string
param generationId string
param subscriptionCorrelation string
param cleanupPrincipal object
param apiImageDigest string = ''
param frontendImageDigest string = ''
param release string
param smtpHost string
param smtpPort int = 587
param smtpFromAddress string
@allowed(['gpt-5.6-terra'])
param openaiModel string
param embeddingModel string = 'text-embedding-3-small'
@secure()
param applicationSecrets object = {}
@allowed(['evidence', 'api', 'worker', 'migration'])
param proofRole string = 'evidence'
param proofDatabaseHost string = ''
param proofCommand array = []
param proofEnvironment array = []
param artifactCommand array = []
param artifactEnvironment array = []

var prefix = 'm78p-${suffix}'
var appEnabled = stage == 'application'
var jobsEnabled = stage != 'foundation'
var dnsTags = toObject(filter(items(lifecycleTags), tag => tag.key != 'mobius.expiry'), tag => tag.key, tag => tag.value)

module foundation './managed_objects.bicep' = {
  name: '${prefix}-foundation'
  params: {
    location: location
    resourceNameSuffix: suffix
    lifecycleTags: lifecycleTags
    deploymentStage: 'foundation'
    storageDataScannerResourceId: storageDataScannerResourceId
    postgresStorageGiB: 32
    applicationDatabaseName: 'opencanvas'
    pilotDestinationPrivacy: true
    pilotOperatorAccess: enableOperatorAccess
  }
}

module operatorAccess './pilot_operator_access.bicep' = if (enableOperatorAccess) {
  name: '${prefix}-operator-access'
  params: {
    location: location
    suffix: suffix
    lifecycleTags: lifecycleTags
    virtualNetworkName: 'vnet-m78o-${suffix}'
    workspaceName: 'law-m78o-${suffix}'
    audienceAppId: operatorVpnAudienceAppId
  }
  dependsOn: [foundation]
}

var extraIdentityNames = ['migration', 'gateway', 'frontend']
resource extraIdentities 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = [for role in extraIdentityNames: {
  name: 'id-${prefix}-${role}'
  location: location
  tags: lifecycleTags
}]
var bootstrap = foundation.outputs.identityBindings[0]
var api = foundation.outputs.identityBindings[1]
var worker = foundation.outputs.identityBindings[2]
var evidence = foundation.outputs.identityBindings[3]
var migration = { role: 'migration', name: extraIdentities[0].name, id: extraIdentities[0].id, principalId: extraIdentities[0].properties.principalId, clientId: extraIdentities[0].properties.clientId }
var gateway = { role: 'gateway', name: extraIdentities[1].name, id: extraIdentities[1].id, principalId: extraIdentities[1].properties.principalId, clientId: extraIdentities[1].properties.clientId }
var frontend = { role: 'frontend', name: extraIdentities[2].name, id: extraIdentities[2].id, principalId: extraIdentities[2].properties.principalId, clientId: extraIdentities[2].properties.clientId }
var networkId = foundation.outputs.virtualNetworkId
var endpointSubnetId = '${networkId}/subnets/private-endpoints'
var runtimeIdentities = { api: api, worker: worker, migration: migration, gateway: gateway, frontend: frontend }

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = { name: 'crm78o${suffix}' }
resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in ['api', 'worker', 'migration', 'gateway', 'frontend']: {
  scope: registry
  name: guid(registry.id, role, 'pilot-acr-pull')
  properties: { principalId: runtimeIdentities[role].principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') }
}]
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = { name: 'pg-m78o-${suffix}' }
resource administrator 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = if (jobsEnabled) {
  parent: postgres
  name: bootstrapPrincipalId
  properties: { principalName: bootstrap.name, principalType: 'ServicePrincipal', tenantId: tenant().tenantId }
}

// Same accepted HA/TLS/Entra Redis shape; no D002 acceptance is repeated here.
resource redis 'Microsoft.Cache/redisEnterprise@2026-05-01-preview' = {
  name: 'redis-${prefix}'
  location: redisLocation
  tags: lifecycleTags
  sku: { name: 'Balanced_B0' }
  properties: { minimumTlsVersion: '1.2', highAvailability: 'Enabled', publicNetworkAccess: 'Disabled' }
}
resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2026-05-01-preview' = {
  parent: redis
  name: 'default'
  properties: { accessKeysAuthentication: 'Disabled', clientProtocol: 'Encrypted', clusteringPolicy: 'NoCluster', evictionPolicy: 'NoEviction', modules: [], port: 10000 }
}
resource redisPolicies 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2026-05-01-preview' = [for role in ['api', 'worker']: {
  parent: redisDatabase
  name: 'm78${suffix}${role}'
  properties: {
    accessString: '+ping +eval +time +hmget +hset +pexpire ~${prefix}:rl:v1:{limits}:*'
    user: { objectId: runtimeIdentities[role].principalId }
  }
}]

resource vault 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: 'kv-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    accessPolicies: []
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: { bypass: 'None', defaultAction: 'Deny', ipRules: [], virtualNetworkRules: [] }
  }
}
resource secrets 'Microsoft.KeyVault/vaults/secrets@2026-02-01' = [for item in items(applicationSecrets): {
  parent: vault
  name: item.key
  properties: { value: item.value }
}]
// The runtime principals may read only the individual secrets they consume.
var commonSecretNames = ['openai-api-key', 'opencanvas-smtp-username', 'opencanvas-smtp-password', 'opencanvas-session-secret', 'opencanvas-invitation-secret', 'opencanvas-upload-capability-secret', 'opencanvas-scanner-result-secret', 'opencanvas-rate-limit-hmac-secret', 'opencanvas-telemetry-token', 'opencanvas-telemetry-pseudonymization-secret', 'opencanvas-observability-operator-user-ids']
var secretReaders = concat(
  map(commonSecretNames, name => { key: name, role: 'api' }),
  map(commonSecretNames, name => { key: name, role: 'worker' }),
  map(['opencanvas-pilot-email', 'opencanvas-pilot-password', 'opencanvas-pilot-secondary-email', 'opencanvas-pilot-secondary-password', 'opencanvas-telemetry-token', 'opencanvas-smtp-username', 'opencanvas-smtp-password'], name => { key: name, role: 'evidence' }),
  [{ key: 'opencanvas-telemetry-token', role: 'gateway' }],
  map(['api', 'worker'], reader => { key: 'opencanvas-pilot-email', role: reader }),
  map(['api', 'worker'], reader => { key: 'opencanvas-pilot-password', role: reader }),
  map(['api', 'worker'], reader => { key: 'opencanvas-pilot-secondary-email', role: reader }),
  map(['api', 'worker'], reader => { key: 'opencanvas-pilot-secondary-password', role: reader }),
  enableExternalDelivery ? [{ key: 'opencanvas-outbox-delivery-secret', role: 'worker' }] : []
)
resource secretScopes 'Microsoft.KeyVault/vaults/secrets@2026-02-01' existing = [for item in secretReaders: { parent: vault, name: item.key }]
resource secretReadGrants 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (item, index) in secretReaders: if (jobsEnabled) {
  scope: secretScopes[index]
  name: guid(vault.id, item.key, item.role, 'secret-read')
  properties: { principalId: item.role == 'evidence' ? evidence.principalId : runtimeIdentities[item.role].principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') }
  dependsOn: [secrets]
}]

var endpointSpecs = [
  { name: 'redis', resourceId: redis.id, group: 'redisEnterprise', dns: 'privatelink.redis.azure.net' }
  { name: 'vault', resourceId: vault.id, group: 'vault', dns: 'privatelink.vaultcore.azure.net' }
]
resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for spec in endpointSpecs: { name: spec.dns, location: 'global', tags: dnsTags }]
resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (spec, index) in endpointSpecs: {
  parent: zones[index]
  name: prefix
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: networkId } }
}]
resource endpoints 'Microsoft.Network/privateEndpoints@2024-10-01' = [for spec in endpointSpecs: {
  name: 'pe-${prefix}-${spec.name}'
  location: location
  tags: lifecycleTags
  properties: { subnet: { id: endpointSubnetId }, privateLinkServiceConnections: [{ name: spec.name, properties: { privateLinkServiceId: spec.resourceId, groupIds: [spec.group] } }] }
}]
resource zoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = [for (spec, index) in endpointSpecs: {
  parent: endpoints[index]
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: spec.name, properties: { privateDnsZoneId: zones[index].id } }] }
}]

module observability './pilot_observability.bicep' = {
  name: '${prefix}-observability'
  params: {
    location: location
    suffix: suffix
    lifecycleTags: lifecycleTags
    workspaceName: 'law-m78o-${suffix}'
    monitorScopeName: 'ampls-m78o-${suffix}'
    virtualNetworkId: networkId
    privateEndpointSubnetId: endpointSubnetId
    gatewayPrincipalId: gateway.principalId
    evidencePrincipalId: evidence.principalId
    operatorPrincipalId: operatorPrincipalId
    operatorPrincipalType: operatorPrincipalType
    catalog: catalog
  }
}

module runtime './pilot_runtime.bicep' = if (jobsEnabled) {
  name: '${prefix}-runtime'
  params: {
    location: location
    prefix: prefix
    lifecycleTags: lifecycleTags
    applicationEnabled: appEnabled
    enableExternalDelivery: enableExternalDelivery
    apiRequestConcurrencyLimit: apiRequestConcurrencyLimit
    environmentId: foundation.outputs.managedEnvironmentId
    environmentDomain: foundation.outputs.managedEnvironmentDefaultDomain
    environmentStaticIp: foundation.outputs.managedEnvironmentStaticIp
    virtualNetworkId: networkId
    registryServer: foundation.outputs.registryLoginServer
    apiImageDigest: apiImageDigest
    frontendImageDigest: frontendImageDigest
    vaultUri: vault.properties.vaultUri
    identities: { bootstrap: bootstrap, api: api, worker: worker, evidence: evidence, migration: migration, gateway: gateway, frontend: frontend }
    cleanupPrincipal: cleanupPrincipal
    campaignId: campaignId
    generationId: generationId
    subscriptionCorrelation: subscriptionCorrelation
    postgresHost: foundation.outputs.postgresHost
    redisHost: redis.properties.hostName
    storageUrl: foundation.outputs.storageAccountUrl
    workspaceCustomerId: foundation.outputs.workspaceCustomerId
    dceEndpoint: observability.outputs.dceEndpoint
    dcrImmutableId: observability.outputs.dcrImmutableId
    release: release
    smtpHost: smtpHost
    smtpPort: smtpPort
    smtpFromAddress: smtpFromAddress
    openaiModel: openaiModel
    embeddingModel: embeddingModel
    proofDatabaseHost: proofDatabaseHost
    proofRole: proofRole
    proofCommand: proofCommand
    proofEnvironment: proofEnvironment
    artifactCommand: artifactCommand
    artifactEnvironment: artifactEnvironment
  }
  dependsOn: [registryPull, secretReadGrants, administrator, zoneGroups, redisPolicies]
}

output foundationBindings object = {
  registryLoginServer: foundation.outputs.registryLoginServer
  apiUrl: 'https://ca-${prefix}-api.${foundation.outputs.managedEnvironmentDefaultDomain}'
  frontendUrl: 'https://ca-${prefix}-frontend.${foundation.outputs.managedEnvironmentDefaultDomain}'
  environmentId: foundation.outputs.managedEnvironmentId
  postgresHost: foundation.outputs.postgresHost
  storageUrl: foundation.outputs.storageAccountUrl
  vaultName: vault.name
  redisHost: redis.properties.hostName
  identityBindings: concat(foundation.outputs.identityBindings, [migration, gateway, frontend])
}
output observabilityBindings object = { dcrId: observability.outputs.dcrId, actionGroupId: observability.outputs.actionGroupId, alertNamespace: observability.outputs.alertNamespace, alertIds: observability.outputs.alertIds, workbookIds: observability.outputs.workbookIds }
output runtimeJobNames array = jobsEnabled ? runtime!.outputs.jobNames : []
output operatorAccessBindings object = enableOperatorAccess ? operatorAccess!.outputs.bindings : {}

// Immutable private execution payloads; no anonymous access or broad account writer.
resource artifactStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: 'stm78o${suffix}' }
resource artifactService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = { parent: artifactStorage, name: 'default' }
resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: artifactService
  name: 'operational-artifacts'
  properties: { publicAccess: 'None' }
  dependsOn: [foundation]
}
resource artifactGrants 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in concat(['bootstrap', 'evidence', 'api', 'worker'], (enableExternalDelivery || proofRole == 'migration') ? ['migration'] : []) : {
  scope: artifacts
  name: guid(artifacts.id, role, 'pilot-artifact')
  properties: {
    principalId: role == 'bootstrap' ? bootstrap.principalId : role == 'evidence' ? evidence.principalId : runtimeIdentities[role].principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role == 'bootstrap' ? 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' : '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  }
}]

resource proofEvidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: artifactService
  name: 'operational-evidence'
  properties: { publicAccess: 'None' }
  dependsOn: [foundation]
}
// Private export is scoped to one campaign container, never the storage account.
resource operatorEvidenceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableOperatorAccess) {
  scope: proofEvidence
  name: guid(proofEvidence.id, operatorExportPrincipalId, 'operator-export')
  properties: {
    principalId: operatorExportPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  }
}
resource evidenceExportGrants 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in concat(['evidence', 'api', 'worker'], (enableExternalDelivery || proofRole == 'migration') ? ['migration'] : []): {
  scope: proofEvidence
  name: guid(proofEvidence.id, role, 'pilot-export')
  properties: {
    principalId: role == 'evidence' ? evidence.principalId : runtimeIdentities[role].principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}]

resource postgresDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: postgres
  name: 'pilot-category-proof'
  properties: { workspaceId: resourceId('Microsoft.OperationalInsights/workspaces', 'law-m78o-${suffix}'), logAnalyticsDestinationType: 'Dedicated', logs: [{ category: 'PostgreSQLLogs', enabled: true }], metrics: [] }
  dependsOn: [foundation]
}
resource registryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: registry
  name: 'pilot-category-proof'
  properties: { workspaceId: resourceId('Microsoft.OperationalInsights/workspaces', 'law-m78o-${suffix}'), logAnalyticsDestinationType: 'Dedicated', logs: [{ category: 'ContainerRegistryLoginEvents', enabled: true }, { category: 'ContainerRegistryRepositoryEvents', enabled: true }], metrics: [] }
  dependsOn: [foundation]
}
resource blobDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: artifactService
  name: 'pilot-category-proof'
  properties: { workspaceId: resourceId('Microsoft.OperationalInsights/workspaces', 'law-m78o-${suffix}'), logAnalyticsDestinationType: 'Dedicated', logs: [{ category: 'StorageRead', enabled: true }, { category: 'StorageWrite', enabled: true }, { category: 'StorageDelete', enabled: true }], metrics: [] }
  dependsOn: [foundation]
}
resource vaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: vault
  name: 'pilot-category-proof'
  properties: { workspaceId: resourceId('Microsoft.OperationalInsights/workspaces', 'law-m78o-${suffix}'), logAnalyticsDestinationType: 'Dedicated', logs: [{ category: 'AuditEvent', enabled: true }], metrics: [] }
}
