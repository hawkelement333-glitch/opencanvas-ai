targetScope = 'subscription'

@description('Checkpoint 1 remains permanently contract-only.')
@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@description('The frozen Checkpoint 1 parameter can never enable deployment.')
@allowed([
  false
])
param deploymentEnabled bool = false

@allowed([
  'contract-only'
  'managed-binding-one-run'
])
param managedBindingMode string = 'contract-only'

@description('Permanent default is false; only the bound one-run lifecycle may pass true.')
param managedBindingDeploymentEnabled bool = false

@allowed([
  'none'
  'cleanup-control'
  'cleanup-job-binding'
  'cleanup-binding'
  'pre-secret'
  'post-secret'
])
param deploymentStage string = 'none'

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

@description('The cleanup-control Automation account is the sole split-region exception.')
@allowed([
  'westus'
])
param cleanupLocation string = 'westus'

@description('PostgreSQL-only split-region exception selected from verified live capability.')
@allowed([
  'centralus'
])
param postgresLocation string = 'centralus'

@description('Redis-only split-region exception selected from subscription-scoped SKU capability.')
@allowed([
  'australiacentral'
])
param redisLocation string = 'australiacentral'

@minLength(0)
@maxLength(64)
param authorizationLedgerSha256 string = ''

@description('Immutable private ACR digest reference. Required only for post-secret deployment.')
param apiImageDigest string = ''

@allowed([
  'sandbox.smtp.mailtrap.io'
])
param smtpHost string = 'sandbox.smtp.mailtrap.io'

@allowed([
  'mobius77-validation@example.invalid'
])
param smtpFromAddress string = 'mobius77-validation@example.invalid'

@allowed([
  'CONTRACT_UNDEFINED'
  'PROVIDER_UNAVAILABLE'
  'RESOURCES_UNDEPLOYED'
  'IDENTITY_UNPROVED'
  'RBAC_UNPROVED'
  'PRIVATE_PATH_UNPROVED'
  'PRODUCER_UNPROVED'
  'TRANSPORT_UNPROVED'
  'CONSUMER_UNPROVED'
  'SCHEMA_UNPROVED'
  'CORRELATION_UNPROVED'
  'REVOCATION_UNPROVED'
  'STALE_EVIDENCE'
  'RESOLVED'
])
param scannerResultBridgeState string = 'CONTRACT_UNDEFINED'

@minLength(0)
@maxLength(64)
param scannerResultBridgeEvidenceIntegrity string = ''

@allowed([
  'mobius.scanner-result-bridge.v1'
])
param scannerResultBridgeContractVersion string = 'mobius.scanner-result-bridge.v1'

param scannerResultBridgeObservedAtUtc string = ''
param scannerResultBridgeProviderProofIntegrity string = ''
param scannerResultBridgeProducerProofIntegrity string = ''
param scannerResultBridgeTransportProofIntegrity string = ''
param scannerResultBridgeConsumerProofIntegrity string = ''
param scannerResultBridgeIdentityRbacProofIntegrity string = ''
param scannerResultBridgePrivatePathProofIntegrity string = ''
param scannerResultBridgeCorrelationProofIntegrity string = ''
param scannerResultBridgeRevocationProofIntegrity string = ''
param scannerResultBridgeCleanupInventoryIntegrity string = ''
@minValue(0)
@maxValue(32)
param scannerResultBridgeUnresolvedReasonCount int = 32

param lifecycleTags object = {}
param cleanupAtUtc string = ''

@minValue(1)
@maxValue(12000)
param expectedUsdCents int = 1

@minValue(1)
@maxValue(25000)
param maximumPlausibleUsdCents int = 1

var oneRunEnabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled && length(authorizationLedgerSha256) == 64
var cleanupControlEnabled = oneRunEnabled && deploymentStage == 'cleanup-control'
var cleanupJobScheduleEnabled = oneRunEnabled && deploymentStage == 'cleanup-job-binding'
var cleanupBindingEnabled = oneRunEnabled && deploymentStage == 'cleanup-binding'
var preSecretEnabled = oneRunEnabled && deploymentStage == 'pre-secret'
var scannerResultBridgeResolved = scannerResultBridgeContractVersion == 'mobius.scanner-result-bridge.v1' && scannerResultBridgeState == 'RESOLVED' && scannerResultBridgeUnresolvedReasonCount == 0 && length(scannerResultBridgeEvidenceIntegrity) == 64 && length(scannerResultBridgeProviderProofIntegrity) == 64 && length(scannerResultBridgeProducerProofIntegrity) == 64 && length(scannerResultBridgeTransportProofIntegrity) == 64 && length(scannerResultBridgeConsumerProofIntegrity) == 64 && length(scannerResultBridgeIdentityRbacProofIntegrity) == 64 && length(scannerResultBridgePrivatePathProofIntegrity) == 64 && length(scannerResultBridgeCorrelationProofIntegrity) == 64 && length(scannerResultBridgeRevocationProofIntegrity) == 64 && length(scannerResultBridgeCleanupInventoryIntegrity) == 64 && !empty(scannerResultBridgeObservedAtUtc)
var postSecretEnabled = oneRunEnabled && deploymentStage == 'post-secret' && scannerResultBridgeResolved
var workloadEnabled = preSecretEnabled || postSecretEnabled
var targetEnabled = cleanupBindingEnabled || workloadEnabled

var targetResourceGroupName = 'rg-solarplexus-mobius-77-staging'
var cleanupResourceGroupName = 'rg-solarplexus-mobius-77-cleanup-control'
var containerAppsInfrastructureResourceGroupName = 'rg-solarplexus-mobius-77-containerapps-infrastructure'
var moduleBoundaries = [
  'policy'
  'network'
  'identities'
  'registry'
  'key-vault'
  'postgres'
  'redis'
  'storage-scanner'
  'scanner-result-bridge'
  'compute'
  'container-apps-dns'
  'observability'
  'cleanup-supervisor'
]
var unresolvedGates = [
  'scanner-result-bridge'
  'alert-destination'
  'evidence-retention'
]

resource targetResourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' = if (targetEnabled) {
  name: targetResourceGroupName
  location: location
  tags: lifecycleTags
}

resource cleanupResourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' = if (cleanupControlEnabled) {
  name: cleanupResourceGroupName
  location: location
  tags: lifecycleTags
}

resource existingCleanupResourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' existing = if (cleanupJobScheduleEnabled || targetEnabled) {
  name: cleanupResourceGroupName
}

resource existingCleanupAutomation 'Microsoft.Automation/automationAccounts@2024-10-23' existing = if (targetEnabled) {
  name: 'aa-mobius77-cleanup-recovery'
  scope: existingCleanupResourceGroup
}

module cleanupSupervisor './modules/cleanup-supervisor.bicep' = if (cleanupControlEnabled) {
  name: 'mobius77-cleanup-control'
  scope: cleanupResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    cleanupControlDeploymentEnabled: true
    cleanupJobScheduleDeploymentEnabled: false
    cleanupLocation: cleanupLocation
    targetResourceGroupName: targetResourceGroupName
    lifecycleTags: lifecycleTags
    cleanupAtUtc: cleanupAtUtc
    expectedUsdCents: expectedUsdCents
    maximumPlausibleUsdCents: maximumPlausibleUsdCents
  }
}

module cleanupJobBinding './modules/cleanup-supervisor.bicep' = if (cleanupJobScheduleEnabled) {
  name: 'mobius77-cleanup-job-binding'
  scope: existingCleanupResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    cleanupControlDeploymentEnabled: false
    cleanupJobScheduleDeploymentEnabled: true
    cleanupLocation: cleanupLocation
    targetResourceGroupName: targetResourceGroupName
    lifecycleTags: lifecycleTags
    cleanupAtUtc: cleanupAtUtc
    expectedUsdCents: expectedUsdCents
    maximumPlausibleUsdCents: maximumPlausibleUsdCents
  }
}

module network './modules/network.bicep' = if (workloadEnabled) {
  name: 'mobius77-managed-binding-network'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: location
    lifecycleTags: lifecycleTags
  }
}

module identities './modules/identities.bicep' = if (targetEnabled) {
  name: 'mobius77-managed-binding-identities'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    workloadIdentityDeploymentEnabled: workloadEnabled
    location: location
    targetResourceGroupId: targetResourceGroup.id
    cleanupAutomationPrincipalId: existingCleanupAutomation.identity.principalId
    lifecycleTags: lifecycleTags
  }
}

module observability './modules/observability.bicep' = if (workloadEnabled) {
  name: 'mobius77-managed-binding-observability'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: location
    lifecycleTags: lifecycleTags
  }
}

module postgres './modules/postgres.bicep' = if (postSecretEnabled) {
  name: 'mobius77-managed-binding-postgres'
  scope: targetResourceGroup
  params: {
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: postgresLocation
    stagingVirtualNetworkId: network.outputs.virtualNetworkId
    databaseAdministratorIdentityId: identities.outputs.databaseAdministratorIdentityId
    databaseAdministratorPrincipalId: identities.outputs.databaseAdministratorPrincipalId
    databaseAdministratorName: identities.outputs.databaseAdministratorName
    tenantId: tenant().tenantId
    lifecycleTags: lifecycleTags
  }
}

module redis './modules/redis.bicep' = if (postSecretEnabled) {
  name: 'mobius77-managed-binding-redis'
  scope: targetResourceGroup
  params: {
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    cacheLocation: redisLocation
    privateEndpointLocation: location
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    virtualNetworkId: network.outputs.virtualNetworkId
    apiIdentityPrincipalId: identities.outputs.workloadIdentityPrincipalId
    workerIdentityPrincipalId: identities.outputs.workerIdentityPrincipalId
    lifecycleTags: lifecycleTags
  }
}

module storage './modules/storage-scanner.bicep' = if (postSecretEnabled) {
  name: 'mobius77-managed-binding-storage'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: location
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    virtualNetworkId: network.outputs.virtualNetworkId
    apiIdentityPrincipalId: identities.outputs.workloadIdentityPrincipalId
    workerIdentityPrincipalId: identities.outputs.workerIdentityPrincipalId
    scannerResultBridgeResolved: scannerResultBridgeResolved
    lifecycleTags: lifecycleTags
  }
}

module scannerResultBridge './modules/scanner-result-bridge.bicep' = if (postSecretEnabled) {
  name: 'mobius77-managed-binding-scanner-result-bridge'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    scannerResultBridgeResolved: scannerResultBridgeResolved
    scannerResultBridgeState: scannerResultBridgeState
    scannerResultBridgeEvidenceIntegrity: scannerResultBridgeEvidenceIntegrity
    location: location
    storageAccountName: storage.outputs.storageAccountUrl == '' ? '' : 'stmobius7711564669'
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    virtualNetworkId: network.outputs.virtualNetworkId
    workerIdentityPrincipalId: identities.outputs.workerIdentityPrincipalId
    lifecycleTags: lifecycleTags
  }
}

module registry './modules/registry.bicep' = if (workloadEnabled) {
  name: 'mobius77-managed-binding-registry'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: location
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    workloadIdentityPrincipalId: identities.outputs.workloadIdentityPrincipalId
    workerIdentityPrincipalId: identities.outputs.workerIdentityPrincipalId
    telemetryIdentityPrincipalId: identities.outputs.telemetryIdentityPrincipalId
    databaseAdministratorPrincipalId: identities.outputs.databaseAdministratorPrincipalId
    lifecycleTags: lifecycleTags
  }
}

module keyVault './modules/key-vault.bicep' = if (workloadEnabled) {
  name: 'mobius77-managed-binding-key-vault'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: location
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    virtualNetworkId: network.outputs.virtualNetworkId
    workloadIdentityPrincipalId: identities.outputs.workloadIdentityPrincipalId
    workerIdentityPrincipalId: identities.outputs.workerIdentityPrincipalId
    telemetryIdentityPrincipalId: identities.outputs.telemetryIdentityPrincipalId
    lifecycleTags: lifecycleTags
  }
}

module compute './modules/compute.bicep' = if (workloadEnabled) {
  name: 'mobius77-managed-binding-compute'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    applicationDeploymentEnabled: postSecretEnabled
    location: location
    containerAppsSubnetId: network.outputs.containerAppsSubnetId
    infrastructureResourceGroupName: containerAppsInfrastructureResourceGroupName
    apiIdentityId: identities.outputs.workloadIdentityId
    apiIdentityClientId: identities.outputs.workloadIdentityClientId
    apiIdentityName: identities.outputs.workloadIdentityName
    workerIdentityId: identities.outputs.workerIdentityId
    workerIdentityClientId: identities.outputs.workerIdentityClientId
    workerIdentityName: identities.outputs.workerIdentityName
    telemetryIdentityId: identities.outputs.telemetryIdentityId
    databaseAdministratorIdentityId: identities.outputs.databaseAdministratorIdentityId
    databaseAdministratorClientId: identities.outputs.databaseAdministratorClientId
    databaseAdministratorName: identities.outputs.databaseAdministratorName
    keyVaultName: keyVault.outputs.keyVaultName
    registryLoginServer: registry.outputs.registryLoginServer
    apiImageDigest: apiImageDigest
    postgresHost: postSecretEnabled ? postgres.outputs.serverFqdn : ''
    postgresPort: postSecretEnabled ? postgres.outputs.serverPort : 5432
    postgresDatabase: postSecretEnabled ? postgres.outputs.databaseName : ''
    redisHost: postSecretEnabled ? redis.outputs.hostName : ''
    redisPort: postSecretEnabled ? redis.outputs.port : 10000
    redisApiUsername: postSecretEnabled ? redis.outputs.apiUsername : ''
    redisWorkerUsername: postSecretEnabled ? redis.outputs.workerUsername : ''
    storageAccountUrl: postSecretEnabled ? storage.outputs.storageAccountUrl : ''
    smtpHost: smtpHost
    smtpFromAddress: smtpFromAddress
    lifecycleTags: lifecycleTags
  }
}

module containerAppsDns './modules/container-apps-dns.bicep' = if (workloadEnabled) {
  name: 'mobius77-managed-binding-container-apps-dns'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    defaultDomain: compute.outputs.managedEnvironmentDefaultDomain
    staticIp: compute.outputs.managedEnvironmentStaticIp
    virtualNetworkId: network.outputs.virtualNetworkId
    lifecycleTags: lifecycleTags
  }
}

output contractVersion string = 'm7.7-infrastructure-contract-v1'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = postSecretEnabled
output moduleCount int = length(moduleBoundaries)
output unresolvedGateCount int = length(unresolvedGates)
output managedBindingContractVersion string = 'm7.7-managed-binding-deployment-v1'
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = oneRunEnabled
output deploymentStage string = deploymentStage
output targetResourceGroupName string = targetResourceGroupName
output cleanupResourceGroupName string = cleanupResourceGroupName
output containerAppsInfrastructureResourceGroupName string = containerAppsInfrastructureResourceGroupName
output stagingLocation string = location
output cleanupLocation string = cleanupLocation
output postgresLocation string = postgresLocation
output redisLocation string = redisLocation
output postgresServerFqdn string = postSecretEnabled ? postgres.outputs.serverFqdn : ''
output redisHostName string = postSecretEnabled ? redis.outputs.hostName : ''
output redisPort int = postSecretEnabled ? redis.outputs.port : 10000
output storageAccountUrl string = postSecretEnabled ? storage.outputs.storageAccountUrl : ''
output telemetryContainerAppId string = postSecretEnabled ? compute.outputs.telemetryContainerAppId : ''
output migrationJobName string = postSecretEnabled ? compute.outputs.migrationJobName : ''
output migrationJobResourceId string = postSecretEnabled && !empty(compute.outputs.migrationJobName) ? resourceId(targetResourceGroupName, 'Microsoft.App/jobs', compute.outputs.migrationJobName) : ''
output scannerResultBridgeResolved bool = scannerResultBridgeResolved
output scannerResultBridgeState string = scannerResultBridgeState
output scannerResultBridgeEvidenceIntegrity string = scannerResultBridgeEvidenceIntegrity
output scannerResultBridgeOutputVersion string = 'm7.7-scanner-result-bridge-output-v1'
output apiImageDigest string = postSecretEnabled ? apiImageDigest : ''
output workloadIdentityClientId string = workloadEnabled ? identities.outputs.workloadIdentityClientId : ''
output defaultProvisioningAuthorized bool = false
output secretValueAccessAuthorized bool = false
