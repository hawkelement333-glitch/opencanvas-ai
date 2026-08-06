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
  'internal-azure-container-apps'
])
param computeTopology string = 'internal-azure-container-apps'

@allowed([
  'Consumption'
])
param workloadProfile string = 'Consumption'

@minValue(8)
@maxValue(8)
param imageBindingCount int = 8

@allowed([
  true
])
param imageDigestContractResolved bool = true

param applicationDeploymentEnabled bool = false

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param containerAppsSubnetId string = ''
@allowed([
  'rg-solarplexus-mobius-77-containerapps-infrastructure'
])
param infrastructureResourceGroupName string = 'rg-solarplexus-mobius-77-containerapps-infrastructure'
param apiIdentityId string = ''
param apiIdentityClientId string = ''
param apiIdentityName string = ''
param workerIdentityId string = ''
param workerIdentityClientId string = ''
param workerIdentityName string = ''
param telemetryIdentityId string = ''
param databaseAdministratorIdentityId string = ''
param databaseAdministratorClientId string = ''
param databaseAdministratorName string = ''
param keyVaultName string = ''
param registryLoginServer string = ''
param apiImageDigest string = ''
param postgresHost string = ''
param postgresPort int = 5432
param postgresDatabase string = ''
param redisHost string = ''
param redisPort int = 10000
param redisApiUsername string = ''
param redisWorkerUsername string = ''
param storageAccountUrl string = ''
param logAnalyticsWorkspaceCustomerId string = ''
@allowed([
  'sandbox.smtp.mailtrap.io'
])
param smtpHost string = 'sandbox.smtp.mailtrap.io'

@allowed([
  'mobius77-validation@example.invalid'
])
param smtpFromAddress string = 'mobius77-validation@example.invalid'
param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var appEnabled = enabled && applicationDeploymentEnabled
var environmentName = 'cae-mobius77-staging'
var apiName = 'ca-mobius77-api'
var workerName = 'ca-mobius77-worker'
var telemetryName = 'ca-mobius77-telemetry'
var migrationJobName = 'caj-mobius77-migration'
var internalApplicationUrl = 'https://${apiName}.${managedEnvironment.properties.defaultDomain}'
var telemetryEndpoint = 'https://${telemetryName}.${managedEnvironment.properties.defaultDomain}/v1/signals'
var keyVaultBaseUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/'
var applicationSecretNames = [
  'openai-api-key'
  'opencanvas-smtp-username'
  'opencanvas-smtp-password'
  'opencanvas-session-secret'
  'opencanvas-invitation-secret'
  'opencanvas-upload-capability-secret'
  'opencanvas-scanner-result-secret'
  'opencanvas-rate-limit-hmac-secret'
  'opencanvas-telemetry-token'
  'opencanvas-telemetry-pseudonymization-secret'
  'opencanvas-observability-operator-user-ids'
]
var commonSettings = [
  { name: 'OPENCANVAS_APP_MODE', value: 'staging' }
  { name: 'OPENCANVAS_APP_URL', value: internalApplicationUrl }
  { name: 'OPENCANVAS_CORS_ORIGINS', value: '["${internalApplicationUrl}"]' }
  { name: 'OPENCANVAS_AUTH_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_AUTH_TEST_BYPASS', value: 'false' }
  { name: 'OPENCANVAS_PASSWORD_RESET_PROVIDER', value: 'smtp' }
  { name: 'OPENCANVAS_SMTP_HOST', value: smtpHost }
  { name: 'OPENCANVAS_SMTP_PORT', value: '2525' }
  { name: 'OPENCANVAS_SMTP_FROM_ADDRESS', value: smtpFromAddress }
  { name: 'OPENCANVAS_SMTP_STARTTLS', value: 'true' }
  { name: 'OPENCANVAS_AI_PROVIDER', value: 'openai' }
  { name: 'OPENCANVAS_EMBEDDING_PROVIDER', value: 'openai' }
  { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
  { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20260726_0028' }
  { name: 'OPENCANVAS_STORAGE_PROVIDER', value: 'azure' }
  { name: 'OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL', value: storageAccountUrl }
  { name: 'OPENCANVAS_OBJECT_INGESTION_MODE', value: 'trusted' }
  { name: 'OPENCANVAS_MALWARE_SCANNER_IDENTITY', value: 'azure-defender-for-storage' }
  { name: 'OPENCANVAS_MALWARE_SCANNER_VERSION', value: 'defender-storage-dual-source-v1' }
  { name: 'OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS', value: '3600' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_MODE', value: 'private_pull' }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID', value: logAnalyticsWorkspaceCustomerId }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT', value: 'https://api.loganalytics.azure.com' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_BASE_SECONDS', value: '5' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS', value: '300' }
  { name: 'OPENCANVAS_JOB_PROVIDER', value: 'database' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER', value: 'redis' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_URL', value: 'rediss://${redisHost}:${redisPort}/0' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_NAMESPACE', value: 'mobius' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_DEPLOYMENT', value: 'milestone-7-7' }
  { name: 'OPENCANVAS_INDEXER_PUBLICATION_MODE', value: 'private_clean' }
  { name: 'OPENCANVAS_TELEMETRY_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_TELEMETRY_EXPORTER', value: 'http' }
  { name: 'OPENCANVAS_TELEMETRY_ENDPOINT', value: telemetryEndpoint }
  { name: 'OPENCANVAS_TELEMETRY_AUTH_SECRET_REFERENCE', value: 'env://OPENCANVAS_TELEMETRY_AUTH_TOKEN' }
  { name: 'OPENCANVAS_TELEMETRY_TLS_VERIFY', value: 'true' }
  { name: 'OPENCANVAS_TELEMETRY_RELEASE', value: 'milestone-7-7' }
  { name: 'OPENCANVAS_TELEMETRY_DEPLOYMENT', value: 'milestone-7-7' }
]
var applicationSecretEnvironment = [
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
var serviceShapeContract = {
  web: { cpuMilli: 250, memoryMiB: 512, minReplicas: 1, normalReplicas: 1, maxReplicas: 2 }
  api: { cpuMilli: 500, memoryMiB: 1024, minReplicas: 2, normalReplicas: 2, maxReplicas: 4 }
  sharedWorkerPool: {
    cpuMilli: 500
    memoryMiB: 1024
    minReplicas: 2
    normalReplicas: 2
    maxReplicas: 4
    workKinds: ['indexer', 'scan', 'workflow', 'agent']
  }
  telemetryGateway: { cpuMilli: 250, memoryMiB: 512, minReplicas: 1, normalReplicas: 1, maxReplicas: 1 }
}
var jobShapeContract = {
  migration: { cpuMilli: 500, memoryMiB: 1024, idleExecutions: 0, maxParallelExecutions: 1 }
  loadGenerator: { cpuMilli: 1000, memoryMiB: 2048, idleExecutions: 0, maxParallelExecutions: 1 }
  faultController: {
    cpuMilli: null
    memoryMiB: null
    idleExecutions: 0
    maxParallelExecutions: 1
    shapeResolutionStatus: 'deferred-to-failure-runner-checkpoint'
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' = if (enabled) {
  name: environmentName
  location: location
  tags: lifecycleTags
  properties: {
    appLogsConfiguration: { destination: 'azure-monitor' }
    publicNetworkAccess: 'Disabled'
    infrastructureResourceGroup: infrastructureResourceGroupName
    vnetConfiguration: { infrastructureSubnetId: containerAppsSubnetId, internal: true }
    zoneRedundant: false
  }
}

resource telemetryContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (appEnabled) {
  name: telemetryName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${telemetryIdentityId}': {} } }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { allowInsecure: false, external: false, targetPort: 4318, transport: 'http' }
      registries: [{ identity: telemetryIdentityId, server: registryLoginServer }]
      secrets: [
        {
          identity: telemetryIdentityId
          keyVaultUrl: '${keyVaultBaseUrl}opencanvas-telemetry-token'
          name: 'opencanvas-telemetry-token'
        }
      ]
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          args: ['-m', 'scripts.telemetry_gateway']
          command: ['python']
          env: [{ name: 'OPENCANVAS_TELEMETRY_GATEWAY_TOKEN', secretRef: 'opencanvas-telemetry-token' }]
          image: apiImageDigest
          name: 'telemetry-gateway'
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 4318, scheme: 'HTTP' }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 4318, scheme: 'HTTP' }
              initialDelaySeconds: 2
              periodSeconds: 5
            }
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { maxReplicas: 1, minReplicas: 1 }
    }
    workloadProfileName: 'Consumption'
  }
}

resource migrationJob 'Microsoft.App/jobs@2025-01-01' = if (appEnabled) {
  name: migrationJobName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${databaseAdministratorIdentityId}': {} } }
  properties: {
    configuration: {
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ identity: databaseAdministratorIdentityId, server: registryLoginServer }]
      replicaRetryLimit: 0
      replicaTimeout: 1800
      triggerType: 'Manual'
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          args: ['-m', 'scripts.bootstrap_postgres']
          command: ['python']
          env: [
            { name: 'OPENCANVAS_APP_MODE', value: 'development' }
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${databaseAdministratorName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'migration' }
            { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
            { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: databaseAdministratorClientId }
            { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20260726_0028' }
            { name: 'OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL', value: apiIdentityName }
            { name: 'OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL', value: workerIdentityName }
          ]
          image: apiImageDigest
          name: 'migration'
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [telemetryContainerApp]
}

resource apiContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (appEnabled) {
  name: apiName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentityId}': {} } }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { allowInsecure: false, external: false, targetPort: 8000, transport: 'auto' }
      registries: [{ identity: apiIdentityId, server: registryLoginServer }]
      secrets: [
        for secretName in applicationSecretNames: {
          identity: apiIdentityId
          keyVaultUrl: '${keyVaultBaseUrl}${secretName}'
          name: secretName
        }
      ]
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          env: concat(commonSettings, applicationSecretEnvironment, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${apiIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'api' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisApiUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
          ])
          image: apiImageDigest
          name: 'api'
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/api/v1/health/live', port: 8000, scheme: 'HTTP' }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/v1/health/ready', port: 8000, scheme: 'HTTP' }
              initialDelaySeconds: 5
              periodSeconds: 5
            }
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      initContainers: [
        {
          args: ['-m', 'scripts.runtime_dependency_gate', '--attempts', '120', '--delay-seconds', '5']
          command: ['python']
          env: concat(commonSettings, applicationSecretEnvironment, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${apiIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'api' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisApiUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
          ])
          image: apiImageDigest
          name: 'database-gate'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { maxReplicas: 4, minReplicas: 2 }
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [migrationJob]
}

resource workerContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (appEnabled) {
  name: workerName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${workerIdentityId}': {} } }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ identity: workerIdentityId, server: registryLoginServer }]
      secrets: [
        for secretName in applicationSecretNames: {
          identity: workerIdentityId
          keyVaultUrl: '${keyVaultBaseUrl}${secretName}'
          name: secretName
        }
      ]
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          args: ['-m', 'scripts.worker']
          command: ['python']
          env: concat(commonSettings, applicationSecretEnvironment, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${workerIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'worker' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisWorkerUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
          ])
          image: apiImageDigest
          name: 'worker'
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      initContainers: [
        {
          args: ['-m', 'scripts.runtime_dependency_gate', '--attempts', '120', '--delay-seconds', '5']
          command: ['python']
          env: concat(commonSettings, applicationSecretEnvironment, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${workerIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'worker' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisWorkerUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
          ])
          image: apiImageDigest
          name: 'database-gate'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { maxReplicas: 4, minReplicas: 2 }
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [migrationJob]
}

output moduleName string = 'compute'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output computeTopology string = computeTopology
output workloadProfile string = workloadProfile
output imageBindingCount int = imageBindingCount
output imageDigestContractResolved bool = imageDigestContractResolved
output serviceShapeContract object = serviceShapeContract
output jobShapeContract object = jobShapeContract
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output applicationDeploymentEnabled bool = appEnabled
output managedEnvironmentId string = enabled ? managedEnvironment.id : ''
output infrastructureResourceGroupName string = infrastructureResourceGroupName
output apiContainerAppId string = appEnabled ? apiContainerApp.id : ''
output workerContainerAppId string = appEnabled ? workerContainerApp.id : ''
output telemetryContainerAppId string = appEnabled ? telemetryContainerApp.id : ''
output migrationJobName string = appEnabled ? migrationJob.name : ''
output managedEnvironmentDefaultDomain string = enabled ? managedEnvironment.properties.defaultDomain : ''
output managedEnvironmentStaticIp string = enabled ? managedEnvironment.properties.staticIp : ''
output publicApplicationIngress bool = false
output configuredOpenAiAlias string = 'OPENAI_API_KEY'
output alternativeOpenAiAliasConfigured bool = false
