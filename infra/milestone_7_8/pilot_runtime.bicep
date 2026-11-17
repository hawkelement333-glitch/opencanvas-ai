// Application and manual jobs only; foundation must be reconciled before this stage.
targetScope = 'resourceGroup'
param location string
param prefix string
param lifecycleTags object
param applicationEnabled bool
param enableExternalDelivery bool = false
@minValue(0)
param apiRequestConcurrencyLimit int = 0
param environmentId string
param environmentDomain string
param environmentStaticIp string
param virtualNetworkId string
param registryServer string
param apiImageDigest string
param frontendImageDigest string
param vaultUri string
param identities object
param cleanupPrincipal object
param campaignId string
param generationId string
param subscriptionCorrelation string
param postgresHost string
param redisHost string
param storageUrl string
param workspaceCustomerId string
param dceEndpoint string
param dcrImmutableId string
param release string
param smtpHost string
param smtpPort int
param smtpFromAddress string
param openaiModel string
param embeddingModel string
param proofDatabaseHost string
param proofRole string
param proofCommand array
param proofEnvironment array
param artifactCommand array
param artifactEnvironment array

var appUrl = 'https://ca-${prefix}-frontend.${environmentDomain}'
var apiUrl = 'https://ca-${prefix}-api.${environmentDomain}'
var gatewayUrl = 'https://ca-${prefix}-gateway.internal.${environmentDomain}/v1/signals'
resource applicationZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: environmentDomain
  location: 'global'
  tags: toObject(filter(items(lifecycleTags), tag => tag.key != 'mobius.expiry'), tag => tag.key, tag => tag.value)
}
resource applicationLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: applicationZone
  name: prefix
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: virtualNetworkId } }
}
resource applicationDns 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: applicationZone
  name: '*'
  properties: { ttl: 60, aRecords: [{ ipv4Address: environmentStaticIp }] }
}
var secretNames = ['openai-api-key', 'opencanvas-smtp-username', 'opencanvas-smtp-password', 'opencanvas-session-secret', 'opencanvas-invitation-secret', 'opencanvas-upload-capability-secret', 'opencanvas-scanner-result-secret', 'opencanvas-rate-limit-hmac-secret', 'opencanvas-telemetry-token', 'opencanvas-telemetry-pseudonymization-secret', 'opencanvas-observability-operator-user-ids']
var secretEnvironment = [
  { name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }
  { name: 'OPENCANVAS_SMTP_USERNAME', secretRef: 'opencanvas-smtp-username' }
  { name: 'OPENCANVAS_SMTP_PASSWORD', secretRef: 'opencanvas-smtp-password' }
  { name: 'OPENCANVAS_SESSION_SECRET', secretRef: 'opencanvas-session-secret' }
  { name: 'OPENCANVAS_INVITATION_SECRET', secretRef: 'opencanvas-invitation-secret' }
  { name: 'OPENCANVAS_UPLOAD_CAPABILITY_SECRET', secretRef: 'opencanvas-upload-capability-secret' }
  { name: 'OPENCANVAS_SCANNER_RESULT_SECRET', secretRef: 'opencanvas-scanner-result-secret' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET', secretRef: 'opencanvas-rate-limit-hmac-secret' }
  { name: 'OPENCANVAS_TELEMETRY_AUTH_TOKEN', secretRef: 'opencanvas-telemetry-token' }
  { name: 'OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET', secretRef: 'opencanvas-telemetry-pseudonymization-secret' }
  { name: 'OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS', secretRef: 'opencanvas-observability-operator-user-ids' }
]
var commonBase = [
  { name: 'OPENCANVAS_APP_MODE', value: 'staging' }
  { name: 'OPENCANVAS_APP_URL', value: appUrl }
  { name: 'OPENCANVAS_CORS_ORIGINS', value: string([appUrl]) }
  { name: 'OPENCANVAS_AUTH_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_AUTH_TEST_BYPASS', value: 'false' }
  { name: 'OPENCANVAS_PASSWORD_RESET_PROVIDER', value: 'smtp' }
  { name: 'OPENCANVAS_SMTP_HOST', value: smtpHost }
  { name: 'OPENCANVAS_SMTP_PORT', value: string(smtpPort) }
  { name: 'OPENCANVAS_SMTP_FROM_ADDRESS', value: smtpFromAddress }
  { name: 'OPENCANVAS_SMTP_STARTTLS', value: 'true' }
  { name: 'OPENCANVAS_AI_PROVIDER', value: 'openai' }
  { name: 'OPENCANVAS_OPENAI_MODEL', value: openaiModel }
  { name: 'OPENCANVAS_ESTIMATED_INPUT_COST_PER_MILLION_TOKENS', value: '2.0' }
  { name: 'OPENCANVAS_ESTIMATED_OUTPUT_COST_PER_MILLION_TOKENS', value: '12.0' }
  { name: 'OPENCANVAS_EMBEDDING_PROVIDER', value: 'openai' }
  { name: 'OPENCANVAS_OPENAI_EMBEDDING_MODEL', value: embeddingModel }
  { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
  { name: 'OPENCANVAS_DATABASE_POOL_SIZE', value: '5' }
  { name: 'OPENCANVAS_DATABASE_MAX_OVERFLOW', value: '0' }
  { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20261116_0030' }
  { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
  { name: 'OPENCANVAS_STORAGE_PROVIDER', value: 'azure' }
  { name: 'OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL', value: storageUrl }
  { name: 'OPENCANVAS_OBJECT_INGESTION_MODE', value: 'trusted' }
  { name: 'OPENCANVAS_MALWARE_SCANNER_IDENTITY', value: 'azure-defender-for-storage' }
  { name: 'OPENCANVAS_MALWARE_SCANNER_VERSION', value: 'defender-storage-dual-source-v1' }
  { name: 'OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS', value: '900' }
  { name: 'OPENCANVAS_UPLOAD_CAPABILITY_TTL_SECONDS', value: '300' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_MODE', value: 'private_pull' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS', value: '20' }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID', value: workspaceCustomerId }
  { name: 'OPENCANVAS_JOB_PROVIDER', value: 'database' }
  { name: 'OPENCANVAS_WORKER_POLL_INTERVAL_SECONDS', value: '1' }
  { name: 'OPENCANVAS_INDEXER_PUBLICATION_MODE', value: 'private_clean' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER', value: 'redis' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_URL', value: 'rediss://${redisHost}:10000/0' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_NAMESPACE', value: prefix }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_DEPLOYMENT', value: prefix }
  { name: 'OPENCANVAS_TELEMETRY_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_TELEMETRY_EXPORTER', value: 'http' }
  { name: 'OPENCANVAS_TELEMETRY_ENDPOINT', value: gatewayUrl }
  { name: 'OPENCANVAS_TELEMETRY_AUTH_SECRET_REFERENCE', value: 'env://OPENCANVAS_TELEMETRY_AUTH_TOKEN' }
  { name: 'OPENCANVAS_TELEMETRY_TLS_VERIFY', value: 'true' }
  { name: 'OPENCANVAS_TELEMETRY_EXPORT_TIMEOUT_SECONDS', value: '5' }
  { name: 'OPENCANVAS_TELEMETRY_RELEASE', value: release }
  { name: 'OPENCANVAS_TELEMETRY_DEPLOYMENT', value: prefix }
]
var common = concat(commonBase, apiRequestConcurrencyLimit > 0 ? [{ name: 'OPENCANVAS_API_REQUEST_CONCURRENCY_LIMIT', value: string(apiRequestConcurrencyLimit) }] : [])
var serviceSpecs = concat([
  { role: 'api', identityRole: 'api', service: 'mobius-api', cpu: json('0.5'), memory: '1Gi', replicas: 2, command: ['uvicorn', 'opencanvas_api.main:app', '--host', '0.0.0.0', '--port', '8000'] }
  { role: 'worker', identityRole: 'worker', service: 'mobius-worker', cpu: json('0.5'), memory: '1Gi', replicas: 1, command: ['python', '-m', 'scripts.worker'] }
], enableExternalDelivery ? [
  { role: 'outbox', identityRole: 'worker', service: 'mobius-outbox', cpu: json('0.25'), memory: '0.5Gi', replicas: 1, command: ['python', '-m', 'scripts.outbox_worker'] }
  { role: 'activity', identityRole: 'worker', service: 'mobius-activity', cpu: json('0.25'), memory: '0.5Gi', replicas: 1, command: ['python', '-m', 'scripts.activity_receiver'] }
] : [])
resource services 'Microsoft.App/containerApps@2025-01-01' = [for spec in serviceSpecs: if (applicationEnabled) {
  name: 'ca-${prefix}-${spec.role}'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[spec.identityRole].id}': {} } }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: spec.role == 'api' ? { external: true, targetPort: 8000, transport: 'http', allowInsecure: false } : spec.role == 'activity' ? { external: false, targetPort: 8011, transport: 'http', allowInsecure: false } : null
      registries: [{ server: registryServer, identity: identities[spec.identityRole].id }]
      secrets: concat(map(secretNames, name => { name: name, keyVaultUrl: '${vaultUri}secrets/${name}', identity: identities[spec.identityRole].id }), contains(['outbox', 'activity'], spec.role) ? [{ name: 'outbox-delivery-secret', keyVaultUrl: '${vaultUri}secrets/opencanvas-outbox-delivery-secret', identity: identities.worker.id }] : [])
    }
    template: {
      scale: { minReplicas: spec.replicas, maxReplicas: spec.replicas }
      containers: [{
        name: spec.role
        image: '${registryServer}/opencanvas-api@${apiImageDigest}'
        command: spec.command
        resources: { cpu: spec.cpu, memory: spec.memory }
        env: concat(common, secretEnvironment, contains(['outbox', 'activity'], spec.role) ? [{ name: 'OPENCANVAS_OUTBOX_RECEIVER_URL', value: 'https://ca-${prefix}-activity.internal.${environmentDomain}/v1/activity-deliveries' }, { name: 'OPENCANVAS_OUTBOX_DELIVERY_SECRET', secretRef: 'outbox-delivery-secret' }] : [], [
          { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${identities[spec.identityRole].name}@${postgresHost}:5432/opencanvas' }
          { name: 'OPENCANVAS_DATABASE_ROLE', value: spec.identityRole }
          { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: identities[spec.identityRole].clientId }
          { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: identities[spec.identityRole].clientId }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: identities[spec.identityRole].clientId }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: identities[spec.identityRole].principalId }
          { name: 'OPENCANVAS_TELEMETRY_SERVICE_NAME', value: spec.service }
        ])
      }]
    }
  }
}]

resource gateway 'Microsoft.App/containerApps@2025-01-01' = if (applicationEnabled) {
  name: 'ca-${prefix}-gateway'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities.gateway.id}': {} } }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 4318, transport: 'http', allowInsecure: false }
      registries: [{ server: registryServer, identity: identities.gateway.id }]
      secrets: [{ name: 'telemetry-token', keyVaultUrl: '${vaultUri}secrets/opencanvas-telemetry-token', identity: identities.gateway.id }]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [{
        name: 'gateway'
        image: '${registryServer}/opencanvas-api@${apiImageDigest}'
        command: ['python', '-m', 'scripts.telemetry_gateway']
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [
          { name: 'OPENCANVAS_TELEMETRY_GATEWAY_TOKEN', secretRef: 'telemetry-token' }
          { name: 'OPENCANVAS_TELEMETRY_GATEWAY_DESTINATION', value: 'azure_logs' }
          { name: 'OPENCANVAS_TELEMETRY_DCE_ENDPOINT', value: dceEndpoint }
          { name: 'OPENCANVAS_TELEMETRY_DCR_IMMUTABLE_ID', value: dcrImmutableId }
          { name: 'AZURE_CLIENT_ID', value: identities.gateway.clientId }
          { name: 'OPENCANVAS_TELEMETRY_GATEWAY_SOURCES_JSON', value: string(concat(map(serviceSpecs, spec => { service: spec.service, environment: 'staging', release: release, deployment: prefix }), [{ service: 'mobius-evidence', environment: 'staging', release: release, deployment: prefix }])) }
        ]
      }]
    }
  }
}

resource frontend 'Microsoft.App/containerApps@2025-01-01' = if (applicationEnabled) {
  name: 'ca-${prefix}-frontend'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities.frontend.id}': {} } }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 3000, transport: 'http', allowInsecure: false }
      registries: [{ server: registryServer, identity: identities.frontend.id }]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [{ name: 'frontend', image: '${registryServer}/opencanvas-web@${frontendImageDigest}', resources: { cpu: json('0.5'), memory: '1Gi' }, env: [{ name: 'NODE_ENV', value: 'production' }, { name: 'OPENCANVAS_PUBLIC_API_URL', value: '${apiUrl}/api/v1' }] }]
    }
  }
}

var manifest = string({
  version: 'm7.8-principal-manifest-v1'
  campaignId: campaignId
  generationId: generationId
  subscriptionCorrelation: subscriptionCorrelation
  principals: {
    bootstrap: { role: 'bootstrap', name: identities.bootstrap.name, objectId: identities.bootstrap.principalId }
    migration: { role: 'migration', name: identities.migration.name, objectId: identities.migration.principalId }
    api: { role: 'api', name: identities.api.name, objectId: identities.api.principalId }
    worker: { role: 'worker', name: identities.worker.name, objectId: identities.worker.principalId }
    evidence: { role: 'evidence', name: identities.evidence.name, objectId: identities.evidence.principalId }
    cleanup: { role: 'cleanup', name: cleanupPrincipal.name, objectId: cleanupPrincipal.principalId }
  }
})
var jobSpecs = [
  { role: 'artifact', identityRole: 'bootstrap', command: artifactCommand, databaseRole: 'migration', timeout: 600 }
  { role: 'bootstrap', identityRole: 'bootstrap', command: ['python', '-m', 'scripts.bootstrap_postgres'], databaseRole: 'provisioning', timeout: 1800 }
  { role: 'migration', identityRole: 'migration', command: ['python', '-m', 'scripts.migrate_and_grant'], databaseRole: 'migration', timeout: 1800 }
  { role: 'evidence', identityRole: proofRole, command: proofCommand, databaseRole: proofRole == 'evidence' ? 'observability' : proofRole, timeout: 7200 }
]
resource jobs 'Microsoft.App/jobs@2025-01-01' = [for spec in jobSpecs: {
  name: 'caj-${prefix}-${spec.role}'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[spec.identityRole].id}': {} } }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaRetryLimit: 0
      replicaTimeout: spec.timeout
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registryServer, identity: identities[spec.identityRole].id }]
      secrets: spec.role == 'evidence' && proofRole != 'migration' ? concat(proofRole == 'evidence' ? [] : map(secretNames, secret => { name: secret, keyVaultUrl: '${vaultUri}secrets/${secret}', identity: identities[proofRole].id }), [
        { name: 'pilot-email', keyVaultUrl: '${vaultUri}secrets/opencanvas-pilot-email', identity: identities[proofRole].id }
        { name: 'pilot-password', keyVaultUrl: '${vaultUri}secrets/opencanvas-pilot-password', identity: identities[proofRole].id }
        { name: 'pilot-secondary-email', keyVaultUrl: '${vaultUri}secrets/opencanvas-pilot-secondary-email', identity: identities[proofRole].id }
        { name: 'pilot-secondary-password', keyVaultUrl: '${vaultUri}secrets/opencanvas-pilot-secondary-password', identity: identities[proofRole].id }
        { name: 'telemetry-token', keyVaultUrl: '${vaultUri}secrets/opencanvas-telemetry-token', identity: identities[proofRole].id }
        { name: 'smtp-username', keyVaultUrl: '${vaultUri}secrets/opencanvas-smtp-username', identity: identities[proofRole].id }
        { name: 'smtp-password', keyVaultUrl: '${vaultUri}secrets/opencanvas-smtp-password', identity: identities[proofRole].id }
      ], enableExternalDelivery && proofRole == 'worker' ? [{ name: 'outbox-delivery-secret', keyVaultUrl: '${vaultUri}secrets/opencanvas-outbox-delivery-secret', identity: identities.worker.id }] : []) : []
    }
    template: {
      containers: [{
        name: spec.role
        image: '${registryServer}/opencanvas-api@${apiImageDigest}'
        command: spec.command
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: concat([
          // Database administration jobs are not application servers. Their existing
          // guarded scripts enforce managed TLS, principal bindings and exact revision.
          { name: 'OPENCANVAS_APP_MODE', value: 'development' }
          { name: 'OPENCANVAS_DATABASE_URL', value: 'postgresql+asyncpg://${identities[spec.identityRole].name}@${empty(proofDatabaseHost) || spec.role != 'evidence' ? postgresHost : proofDatabaseHost}:5432/opencanvas' }
          { name: 'OPENCANVAS_DATABASE_ROLE', value: spec.databaseRole }
          { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
          { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
          { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
          { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: identities[spec.identityRole].clientId }
          { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: identities[spec.identityRole].clientId }
          { name: 'AZURE_CLIENT_ID', value: identities[spec.identityRole].clientId }
          { name: 'OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST', value: manifest }
          { name: 'OPENCANVAS_CAMPAIGN_ID', value: campaignId }
          { name: 'OPENCANVAS_CAMPAIGN_GENERATION_ID', value: generationId }
          { name: 'OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID', value: identities[spec.identityRole].principalId }
        ], spec.role == 'evidence' ? (proofRole == 'migration' ? proofEnvironment : concat([
          { name: 'M78_PILOT_API_URL', value: '${apiUrl}/api/v1' }
          { name: 'M78_PILOT_FRONTEND_URL', value: appUrl }
          { name: 'OPENCANVAS_PILOT_EMAIL', secretRef: 'pilot-email' }
          { name: 'OPENCANVAS_PILOT_PASSWORD', secretRef: 'pilot-password' }
          { name: 'OPENCANVAS_PILOT_SECONDARY_EMAIL', secretRef: 'pilot-secondary-email' }
          { name: 'OPENCANVAS_PILOT_SECONDARY_PASSWORD', secretRef: 'pilot-secondary-password' }
          { name: 'OPENCANVAS_TELEMETRY_GATEWAY_TOKEN', secretRef: 'telemetry-token' }
          { name: 'OPENCANVAS_SMTP_USERNAME', secretRef: 'smtp-username' }
          { name: 'OPENCANVAS_SMTP_PASSWORD', secretRef: 'smtp-password' }
        ], enableExternalDelivery && proofRole == 'worker' ? [{ name: 'OPENCANVAS_OUTBOX_RECEIVER_URL', value: 'https://ca-${prefix}-activity.internal.${environmentDomain}/v1/activity-deliveries' }, { name: 'OPENCANVAS_OUTBOX_DELIVERY_SECRET', secretRef: 'outbox-delivery-secret' }] : [], proofRole == 'evidence' ? [] : [
          { name: 'OPENCANVAS_TELEMETRY_SERVICE_NAME', value: proofRole == 'worker' ? 'mobius-worker' : 'mobius-api' }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: identities[proofRole].clientId }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: identities[proofRole].principalId }
          { name: 'OPENCANVAS_PROCESSING_JOB_DEADLINE_SECONDS', value: '28800' }
        ], proofRole == 'evidence' ? [] : filter(common, item => !contains(['OPENCANVAS_APP_MODE', 'OPENCANVAS_DATABASE_AUTH_MODE', 'OPENCANVAS_DATABASE_TLS_MODE', 'PGSSLROOTCERT', 'OPENCANVAS_SMTP_USERNAME', 'OPENCANVAS_SMTP_PASSWORD'], item.name)), proofRole == 'evidence' ? [] : filter(secretEnvironment, item => !contains(['OPENCANVAS_SMTP_USERNAME', 'OPENCANVAS_SMTP_PASSWORD'], item.name)), proofEnvironment)) : spec.role == 'artifact' ? artifactEnvironment : [])
      }]
    }
  }
}]

output jobNames array = [for (spec, index) in jobSpecs: jobs[index].name]
output apiUrl string = apiUrl
output frontendUrl string = appUrl
