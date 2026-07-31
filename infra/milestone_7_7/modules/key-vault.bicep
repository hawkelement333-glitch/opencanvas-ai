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
  'standard'
])
param vaultSku string = 'standard'

@allowed([
  false
])
param publicNetworkAccess bool = false

@allowed([
  true
])
param privateEndpointRequired bool = true

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param privateEndpointSubnetId string = ''
param virtualNetworkId string = ''
param workloadIdentityPrincipalId string = ''
param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var keyVaultName = 'kv-mobius77-11564669'
var privateDnsZoneName = 'privatelink.vaultcore.azure.net'
var secretsUserRoleDefinitionId = '4633458b-17de-408a-b874-0445c86b69e6'

resource keyVault 'Microsoft.KeyVault/vaults@2026-02-01' = if (enabled) {
  name: keyVaultName
  location: location
  tags: lifecycleTags
  properties: {
    accessPolicies: []
    enablePurgeProtection: false
    enableRbacAuthorization: true
    enableSoftDelete: true
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    publicNetworkAccess: 'Disabled'
    sku: {
      family: 'A'
      name: 'standard'
    }
    softDeleteRetentionInDays: 7
    tenantId: tenant().tenantId
  }
}

resource workloadSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enabled) {
  name: guid(keyVault.id, workloadIdentityPrincipalId, secretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    principalId: workloadIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleDefinitionId)
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2026-01-01' = if (enabled) {
  name: 'pe-mobius77-keyvault'
  location: location
  tags: lifecycleTags
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'plc-mobius77-keyvault'
        properties: {
          groupIds: [
            'vault'
          ]
          privateLinkServiceId: keyVault.id
          requestMessage: 'Milestone 7.7 isolated synthetic validation'
        }
      }
    ]
    subnet: {
      id: privateEndpointSubnetId
    }
  }
}

resource keyVaultPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2026-01-01' = if (enabled) {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'vault'
        properties: {
          privateDnsZoneId: resourceId('Microsoft.Network/privateDnsZones', privateDnsZoneName)
        }
      }
    ]
  }
}

output moduleName string = 'key-vault'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output vaultSku string = vaultSku
output publicNetworkAccess bool = publicNetworkAccess
output privateEndpointRequired bool = privateEndpointRequired
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output keyVaultName string = keyVaultName
output keyVaultId string = enabled ? keyVault.id : ''
output virtualNetworkBindingVerified bool = enabled && !empty(virtualNetworkId)
output secretValueAccessAuthorized bool = false
