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
@maxValue(12000)
param expectedUsdCents int = 1

@minValue(1)
@maxValue(14999)
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
  'observability'
  'cleanup-supervisor'
]
var unresolvedGates = [
  'region-and-subscription-availability'
  'exact-provider-api-versions'
  'managed-identity-environment-mapping'
  'redis-custom-acl-support'
  'private-acr-source-path'
  'telemetry-gateway'
  'scanner-result-bridge'
  'alert-destination'
  'openai-smtp-test-providers'
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
    virtualNetworkId: network.outputs.virtualNetworkId
    workloadIdentityPrincipalId: identities.outputs.workloadIdentityPrincipalId
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
    workloadIdentityId: identities.outputs.workloadIdentityId
    keyVaultName: keyVault.outputs.keyVaultName
    registryLoginServer: registry.outputs.registryLoginServer
    apiImageDigest: apiImageDigest
    smtpHost: smtpHost
    smtpFromAddress: smtpFromAddress
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
output stagingLocation string = location
output cleanupLocation string = cleanupLocation
output defaultProvisioningAuthorized bool = false
output secretValueAccessAuthorized bool = false
