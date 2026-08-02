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

param lifecycleTags object = {}
param cleanupAtUtc string = ''

@minValue(1)
@maxValue(10000)
param expectedUsdCents int = 1

@minValue(1)
@maxValue(10000)
param maximumPlausibleUsdCents int = 1

var oneRunEnabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled && length(authorizationLedgerSha256) == 64
var cleanupControlEnabled = oneRunEnabled && deploymentStage == 'cleanup-control'
var cleanupJobScheduleEnabled = oneRunEnabled && deploymentStage == 'cleanup-job-binding'
var cleanupBindingEnabled = oneRunEnabled && deploymentStage == 'cleanup-binding'
var preSecretEnabled = oneRunEnabled && deploymentStage == 'pre-secret'
var postSecretEnabled = oneRunEnabled && deploymentStage == 'post-secret'
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
  name: 'aa-mobius77-cleanup'
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
    location: location
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
output deploymentEnabled bool = deploymentEnabled
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
output postgresServerFqdn string = postSecretEnabled ? postgres.outputs.serverFqdn : ''
output redisHostName string = postSecretEnabled ? redis.outputs.hostName : ''
output redisPort int = postSecretEnabled ? redis.outputs.port : 10000
output storageAccountUrl string = postSecretEnabled ? storage.outputs.storageAccountUrl : ''
output telemetryContainerAppId string = postSecretEnabled ? compute.outputs.telemetryContainerAppId : ''
output migrationJobName string = postSecretEnabled ? compute.outputs.migrationJobName : ''
output workloadIdentityClientId string = workloadEnabled ? identities.outputs.workloadIdentityClientId : ''
output defaultProvisioningAuthorized bool = false
output secretValueAccessAuthorized bool = false
