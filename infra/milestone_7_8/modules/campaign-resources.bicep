targetScope = 'resourceGroup'

param campaignId string
param generationId string
@minLength(10)
@maxLength(10)
param resourceNameSuffix string
param subscriptionCorrelation string
param targetLocation string
param postgresLocation string
param cleanupLocation string
param cleanupRegionSelectionSha256 string
param cleanupCandidateRegions string
param cleanupOfferClassification string
param cleanupOfferEligibilityDisposition string
param cleanupOfferEligibleRegions string
param cleanupOfferEligibilitySource string
param cleanupOfferEligibilitySha256 string
param cleanupResourceGroupName string
param cleanupPrincipalId string
param tenantId string
param postgresServerName string
param postgresSkuName string
param postgresVersion string
param postgresStorageGiB int
param postgresPrimaryZone string
param postgresStandbyZone string
param backupRetentionDays int
param maintenanceDay int
param maintenanceHour int
param maintenanceMinute int
param registryName string
param imageDigest string
param deploymentStage string
param containerAppsEnvironmentName string
param virtualNetworkName string
param privateDnsZoneName string
param logAnalyticsWorkspaceName string
param administratorIdentityName string
param migrationIdentityName string
param apiIdentityName string
param workerIdentityName string
param evidenceIdentityName string
param cleanupIdentityName string
param bootstrapIdentity object
param migrationIdentity object
param apiIdentity object
param workerIdentity object
param evidenceIdentity object
param cleanupDeadlineUtc string
param maximumHours int
param costCeilingCents int
param lifecycleTags object

var principalManifestJson = string({
  version: 'm7.8-principal-manifest-v1'
  campaignId: campaignId
  generationId: generationId
  subscriptionCorrelation: subscriptionCorrelation
  principals: {
    bootstrap: { role: 'bootstrap', name: administratorIdentityName, objectId: bootstrapIdentity.principalId }
    migration: { role: 'migration', name: migrationIdentityName, objectId: migrationIdentity.principalId }
    api: { role: 'api', name: apiIdentityName, objectId: apiIdentity.principalId }
    worker: { role: 'worker', name: workerIdentityName, objectId: workerIdentity.principalId }
    evidence: { role: 'evidence', name: evidenceIdentityName, objectId: evidenceIdentity.principalId }
    cleanup: { role: 'cleanup', name: cleanupIdentityName, objectId: cleanupPrincipalId }
  }
})
var commonEnvironment = [
  { name: 'OPENCANVAS_CAMPAIGN_ID', value: campaignId }
  { name: 'OPENCANVAS_CAMPAIGN_GENERATION_ID', value: generationId }
  { name: 'OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST', value: principalManifestJson }
  { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'require' }
  { name: 'OPENCANVAS_DATABASE_HOST', value: postgres.properties.fullyQualifiedDomainName }
  { name: 'OPENCANVAS_DATABASE_NAME', value: 'opencanvas' }
]
var commonRuntimeEnvironment = concat(commonEnvironment, [
  { name: 'OPENCANVAS_APP_MODE', value: 'development' }
  { name: 'OPENCANVAS_AUTH_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_AUTH_TEST_BYPASS', value: 'false' }
  { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20260726_0029' }
  { name: 'OPENCANVAS_STORAGE_PROVIDER', value: 'memory' }
  { name: 'OPENCANVAS_OBJECT_INGESTION_MODE', value: 'disabled' }
  { name: 'OPENCANVAS_JOB_PROVIDER', value: 'database' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER', value: 'memory' }
  { name: 'OPENCANVAS_AI_PROVIDER', value: 'mock' }
  { name: 'OPENCANVAS_EMBEDDING_PROVIDER', value: 'mock' }
  { name: 'OPENCANVAS_TELEMETRY_ENABLED', value: 'false' }
  { name: 'OPENCANVAS_TELEMETRY_EXPORTER', value: 'disabled' }
])
var postgresSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetworkName, 'postgres')
var containerAppsSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetworkName, 'container-apps')
var privateEndpointSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', virtualNetworkName, 'private-endpoints')
var workloadEnabled = deploymentStage == 'workload'
var acrPullRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: virtualNetworkName
  location: postgresLocation
  tags: lifecycleTags
  properties: {
    addressSpace: { addressPrefixes: [ '10.78.0.0/16' ] }
    subnets: [
      {
        name: 'postgres'
        properties: {
          addressPrefix: '10.78.1.0/24'
          delegations: [ { name: 'postgres', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } } ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'container-apps'
        properties: { addressPrefix: '10.78.4.0/23' }
      }
      {
        name: 'private-endpoints'
        properties: { addressPrefix: '10.78.8.0/24', privateEndpointNetworkPolicies: 'Disabled' }
      }
    ]
  }
}

resource privateDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneName
  location: 'global'
  tags: lifecycleTags
}

resource registryPrivateDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.azurecr.io'
  location: 'global'
  tags: lifecycleTags
}

resource registryPrivateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: registryPrivateDns
  name: 'm78-${uniqueString(campaignId, generationId)}'
  location: 'global'
  tags: lifecycleTags
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}

resource privateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDns
  name: 'm78-${uniqueString(campaignId, generationId)}'
  location: 'global'
  tags: lifecycleTags
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresServerName
  location: postgresLocation
  tags: lifecycleTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${bootstrapIdentity.id}': {} }
  }
  sku: { name: postgresSkuName, tier: 'GeneralPurpose' }
  properties: {
    createMode: 'Default'
    version: postgresVersion
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenantId }
    availabilityZone: postgresPrimaryZone
    highAvailability: { mode: 'ZoneRedundant', standbyAvailabilityZone: postgresStandbyZone }
    storage: { storageSizeGB: postgresStorageGiB, autoGrow: 'Disabled', tier: 'P6' }
    backup: { backupRetentionDays: backupRetentionDays, geoRedundantBackup: 'Disabled' }
    maintenanceWindow: { customWindow: 'Enabled', dayOfWeek: maintenanceDay, startHour: maintenanceHour, startMinute: maintenanceMinute }
    network: {
      delegatedSubnetResourceId: postgresSubnetId
      privateDnsZoneArmResourceId: privateDns.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [ privateDnsLink ]
}

resource postgresAdministrator 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: postgres
  name: bootstrapIdentity.principalId
  properties: {
    principalName: administratorIdentityName
    principalType: 'ServicePrincipal'
    tenantId: tenantId
  }
}

resource vectorExtension 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { source: 'user-override', value: 'vector' }
}

resource applicationDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'opencanvas'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ postgresAdministrator, vectorExtension ]
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: targetLocation
  tags: lifecycleTags
  properties: {
    retentionInDays: 30
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    sku: { name: 'PerGB2018' }
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: targetLocation
  tags: lifecycleTags
  sku: { name: 'Premium' }
  properties: { adminUserEnabled: false, publicNetworkAccess: 'Disabled', zoneRedundancy: 'Disabled' }
}

resource registryEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${registryName}'
  location: targetLocation
  tags: lifecycleTags
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      { name: 'registry', properties: { privateLinkServiceId: registry.id, groupIds: [ 'registry' ] } }
    ]
  }
}

resource registryDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: registryEndpoint
  name: 'registry'
  properties: {
    privateDnsZoneConfigs: [ { name: 'registry', properties: { privateDnsZoneId: registryPrivateDns.id } } ]
  }
  dependsOn: [ registryPrivateDnsLink ]
}

resource registryPullAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, index) in [
  bootstrapIdentity.principalId
  migrationIdentity.principalId
  apiIdentity.principalId
  workerIdentity.principalId
  evidenceIdentity.principalId
]: {
  name: guid(registry.id, principalId, string(index))
  scope: registry
  properties: {
    roleDefinitionId: acrPullRoleDefinitionId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource postgresDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'm78-postgres-sanitized'
  scope: postgres
  properties: {
    workspaceId: logs.id
    logs: [ { category: 'PostgreSQLLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

resource registryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'm78-registry-sanitized'
  scope: registry
  properties: {
    workspaceId: logs.id
    logs: [
      { category: 'ContainerRegistryRepositoryEvents', enabled: true }
      { category: 'ContainerRegistryLoginEvents', enabled: true }
    ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: containerAppsEnvironmentName
  location: targetLocation
  tags: lifecycleTags
  properties: {
    appLogsConfiguration: { destination: 'log-analytics', logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey } }
    vnetConfiguration: { infrastructureSubnetId: containerAppsSubnetId, internal: true }
    zoneRedundant: false
  }
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = if (workloadEnabled) {
  name: 'app-m78-${resourceNameSuffix}'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentity.id}': {} } }
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 8000, transport: 'http', allowInsecure: false }
      registries: [ { server: registry.properties.loginServer, identity: apiIdentity.id } ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: '${registry.properties.loginServer}/mobius-api@${imageDigest}'
          env: concat(commonRuntimeEnvironment, [
            { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${apiIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'api' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentity.clientId }
          ])
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 4 }
    }
  }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource workerJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-worker'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${workerIdentity.id}': {} } }
  properties: {
    environmentId: environment.id
    configuration: { triggerType: 'Manual', replicaTimeout: 7200, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: workerIdentity.id } ] }
    template: {
      containers: [
        {
          name: 'worker'
          image: '${registry.properties.loginServer}/mobius-api@${imageDigest}'
          command: [ 'python', '-m', 'scripts.worker' ]
          env: concat(commonRuntimeEnvironment, [
            { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${workerIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'worker' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentity.clientId }
          ])
        }
      ]
    }
  }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource bootstrapJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-bootstrap'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${bootstrapIdentity.id}': {} } }
  properties: {
    environmentId: environment.id
    configuration: { triggerType: 'Manual', replicaTimeout: 900, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: bootstrapIdentity.id } ] }
    template: { containers: [ { name: 'bootstrap', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.bootstrap_postgres' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${administratorIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'provisioning' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: bootstrapIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: bootstrapIdentity.principalId } ]) } ] }
  }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource migrationJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-migration'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${migrationIdentity.id}': {} } }
  properties: {
    environmentId: environment.id
    configuration: { triggerType: 'Manual', replicaTimeout: 1800, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: migrationIdentity.id } ] }
    template: { containers: [ { name: 'migration', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.migrate_and_grant' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${migrationIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'migration' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: migrationIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: migrationIdentity.principalId } ]) } ] }
  }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource evidenceJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-evidence'
  location: targetLocation
  tags: union(lifecycleTags, { evidenceDestination: 'log-analytics-sanitized' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${evidenceIdentity.id}': {} } }
  properties: {
    environmentId: environment.id
    configuration: { triggerType: 'Manual', replicaTimeout: 7200, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: evidenceIdentity.id } ] }
    template: { containers: [ { name: 'evidence', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.managed_postgres_evidence' ], args: [ '--phase', 'catalog' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${evidenceIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'observability' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: evidenceIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: evidenceIdentity.principalId }, { name: 'M78_PRIVATE_API_URL', value: 'https://${apiApp!.properties.configuration.ingress.fqdn}' } ]) } ] }
  }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource apiProbeJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-probe-api'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentity.id}': {} } }
  properties: { environmentId: environment.id, configuration: { triggerType: 'Manual', replicaTimeout: 900, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: apiIdentity.id } ] }, template: { containers: [ { name: 'probe-api', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.managed_postgres_evidence' ], args: [ '--phase', 'api' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${apiIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'api' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: apiIdentity.principalId } ]) } ] } }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource workerProbeJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-probe-worker'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${workerIdentity.id}': {} } }
  properties: { environmentId: environment.id, configuration: { triggerType: 'Manual', replicaTimeout: 900, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: workerIdentity.id } ] }, template: { containers: [ { name: 'probe-worker', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.managed_postgres_evidence' ], args: [ '--phase', 'worker' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${workerIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'worker' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: workerIdentity.principalId } ]) } ] } }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource migrationProbeJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-probe-migration'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${migrationIdentity.id}': {} } }
  properties: { environmentId: environment.id, configuration: { triggerType: 'Manual', replicaTimeout: 900, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: migrationIdentity.id } ] }, template: { containers: [ { name: 'probe-migration', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.managed_postgres_evidence' ], args: [ '--phase', 'migration' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${migrationIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'migration' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: migrationIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: migrationIdentity.principalId } ]) } ] } }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource recoveryJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-revoke'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${bootstrapIdentity.id}': {} } }
  properties: { environmentId: environment.id, configuration: { triggerType: 'Manual', replicaTimeout: 900, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: bootstrapIdentity.id } ] }, template: { containers: [ { name: 'credential-recovery', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.credential_recovery_probe', 'revoke' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${administratorIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'provisioning' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: bootstrapIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: bootstrapIdentity.principalId } ]) } ] } }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

resource recoveryRestoreJob 'Microsoft.App/jobs@2024-03-01' = if (workloadEnabled) {
  name: 'job-m78-${resourceNameSuffix}-restore'
  location: targetLocation
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${bootstrapIdentity.id}': {} } }
  properties: { environmentId: environment.id, configuration: { triggerType: 'Manual', replicaTimeout: 900, replicaRetryLimit: 0, registries: [ { server: registry.properties.loginServer, identity: bootstrapIdentity.id } ] }, template: { containers: [ { name: 'credential-restore', image: '${registry.properties.loginServer}/mobius-api@${imageDigest}', command: [ 'python', '-m', 'scripts.credential_recovery_probe', 'restore' ], env: concat(commonEnvironment, [ { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${administratorIdentityName}@${postgres.properties.fullyQualifiedDomainName}:5432/opencanvas' }, { name: 'OPENCANVAS_DATABASE_ROLE', value: 'provisioning' }, { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: bootstrapIdentity.clientId }, { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: bootstrapIdentity.principalId } ]) } ] } }
  dependsOn: [ applicationDatabase, registryDnsGroup, registryPullAssignments ]
}

output postgresServerName string = postgres.name
output bootstrapJobName string = workloadEnabled ? bootstrapJob.name : ''
output migrationJobName string = workloadEnabled ? migrationJob.name : ''
output evidenceJobName string = workloadEnabled ? evidenceJob.name : ''
output workerJobName string = workloadEnabled ? workerJob.name : ''
output apiAppName string = workloadEnabled ? apiApp.name : ''
output apiProbeJobName string = workloadEnabled ? apiProbeJob.name : ''
output workerProbeJobName string = workloadEnabled ? workerProbeJob.name : ''
output migrationProbeJobName string = workloadEnabled ? migrationProbeJob.name : ''
output recoveryJobName string = workloadEnabled ? recoveryJob.name : ''
output recoveryRestoreJobName string = workloadEnabled ? recoveryRestoreJob.name : ''
output registryLoginServer string = registry.properties.loginServer
output identityObjectIds object = {
  bootstrap: bootstrapIdentity.principalId
  migration: migrationIdentity.principalId
  api: apiIdentity.principalId
  worker: workerIdentity.principalId
  evidence: evidenceIdentity.principalId
}
output campaignBinding object = { campaignId: campaignId, generationId: generationId, subscriptionCorrelation: subscriptionCorrelation, cleanupDeadlineUtc: cleanupDeadlineUtc, cleanupLocation: cleanupLocation, cleanupRegionSelectionSha256: cleanupRegionSelectionSha256, cleanupCandidateRegions: cleanupCandidateRegions, cleanupOfferClassification: cleanupOfferClassification, cleanupOfferEligibilityDisposition: cleanupOfferEligibilityDisposition, cleanupOfferEligibleRegions: cleanupOfferEligibleRegions, cleanupOfferEligibilitySource: cleanupOfferEligibilitySource, cleanupOfferEligibilitySha256: cleanupOfferEligibilitySha256, maximumHours: maximumHours, costCeilingCents: costCeilingCents, cleanupResourceGroupName: cleanupResourceGroupName, registryPrivateEndpointId: registryEndpoint.id, principalManifest: principalManifestJson }
