targetScope = 'subscription'

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

@allowed([
  true
])
param managedBindingDeploymentEnabled bool

@allowed([
  'rg-solarplexus-mobius-77-staging'
])
param targetResourceGroupName string = 'rg-solarplexus-mobius-77-staging'

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

@allowed([
  'centralus'
])
param postgresLocation string = 'centralus'

param apiImageDigest string
param lifecycleTags object

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var virtualNetworkName = 'vnet-mobius77-staging'
var containerAppsSubnetName = 'snet-mobius77-containerapps'
var apiIdentityName = 'id-mobius77-api'
var workerIdentityName = 'id-mobius77-worker'
var databaseAdministratorIdentityName = 'id-mobius77-db-admin'
var databaseMigrationIdentityName = 'id-mobius77-db-migration'
var keyVaultName = 'kv-mobius77-11564669'
var registryLoginServer = 'acrmobius7711564669.azurecr.io'

resource targetResourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' existing = if (enabled) {
  name: targetResourceGroupName
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' existing = if (enabled) {
  scope: targetResourceGroup
  name: virtualNetworkName
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (enabled) {
  scope: targetResourceGroup
  name: apiIdentityName
}

resource workerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (enabled) {
  scope: targetResourceGroup
  name: workerIdentityName
}

resource databaseAdministratorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (enabled) {
  scope: targetResourceGroup
  name: databaseAdministratorIdentityName
}

resource databaseMigrationIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (enabled) {
  scope: targetResourceGroup
  name: databaseMigrationIdentityName
}

module postgres './postgres.bicep' = if (enabled) {
  name: 'mobius77-observability-owner-bootstrap-postgres'
  scope: targetResourceGroup
  params: {
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    location: postgresLocation
    stagingVirtualNetworkId: virtualNetwork!.id
    databaseAdministratorIdentityId: databaseAdministratorIdentity!.id
    databaseAdministratorPrincipalId: databaseAdministratorIdentity!.properties.principalId
    databaseAdministratorName: databaseAdministratorIdentity!.name
    tenantId: tenant().tenantId
    lifecycleTags: lifecycleTags
  }
}

module compute './compute.bicep' = if (enabled) {
  name: 'mobius77-observability-owner-bootstrap-compute'
  scope: targetResourceGroup
  params: {
    checkpointMode: checkpointMode
    deploymentEnabled: deploymentEnabled
    managedBindingMode: managedBindingMode
    managedBindingDeploymentEnabled: true
    applicationDeploymentEnabled: false
    ownerBootstrapDeploymentEnabled: true
    location: location
    containerAppsSubnetId: '${virtualNetwork!.id}/subnets/${containerAppsSubnetName}'
    infrastructureResourceGroupName: 'rg-solarplexus-mobius-77-containerapps-infrastructure'
    apiIdentityId: apiIdentity!.id
    apiIdentityClientId: apiIdentity!.properties.clientId
    apiIdentityPrincipalId: apiIdentity!.properties.principalId
    apiIdentityName: apiIdentity!.name
    workerIdentityId: workerIdentity!.id
    workerIdentityClientId: workerIdentity!.properties.clientId
    workerIdentityPrincipalId: workerIdentity!.properties.principalId
    workerIdentityName: workerIdentity!.name
    telemetryIdentityId: ''
    databaseAdministratorIdentityId: databaseAdministratorIdentity!.id
    databaseAdministratorClientId: databaseAdministratorIdentity!.properties.clientId
    databaseAdministratorName: databaseAdministratorIdentity!.name
    databaseMigrationIdentityId: databaseMigrationIdentity!.id
    databaseMigrationClientId: databaseMigrationIdentity!.properties.clientId
    databaseMigrationPrincipalId: databaseMigrationIdentity!.properties.principalId
    databaseMigrationName: databaseMigrationIdentity!.name
    keyVaultName: keyVaultName
    registryLoginServer: registryLoginServer
    apiImageDigest: apiImageDigest
    postgresHost: postgres!.outputs.serverFqdn
    postgresPort: postgres!.outputs.serverPort
    postgresDatabase: postgres!.outputs.databaseName
    redisHost: ''
    redisPort: 10000
    redisApiUsername: ''
    redisWorkerUsername: ''
    storageAccountUrl: ''
    logAnalyticsWorkspaceCustomerId: ''
    logAnalyticsWorkspaceId: ''
    lifecycleTags: lifecycleTags
  }
}

output ownerBootstrapEnabled bool = enabled && compute!.outputs.ownerBootstrapDeploymentEnabled
output postgresServerFqdn string = enabled ? postgres!.outputs.serverFqdn : ''
output postgresDatabase string = enabled ? postgres!.outputs.databaseName : ''
output apiContainerAppId string = enabled ? compute!.outputs.apiContainerAppId : ''
output privateApplicationUrl string = enabled ? 'https://ca-mobius77-api.${compute!.outputs.managedEnvironmentDefaultDomain}' : ''
output migrationJobName string = enabled ? compute!.outputs.migrationJobName : ''
output databasePrincipalBootstrapJobName string = enabled
  ? compute!.outputs.databasePrincipalBootstrapJobName
  : ''
output ownerReadbackJobName string = enabled ? compute!.outputs.ownerReadbackJobName : ''
output publicApplicationIngress bool = false
output sessionSecretReferenceCount int = enabled ? 1 : 0
output fullApplicationDeploymentEnabled bool = false
output workerDeploymentEnabled bool = false
output telemetryDeploymentEnabled bool = false
output redisDeploymentEnabled bool = false
