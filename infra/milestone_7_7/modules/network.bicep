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
  'southcentralus'
])
param location string = 'southcentralus'

param lifecycleTags object = {}

@minValue(3)
@maxValue(3)
param infrastructurePublicIpCount int = 3

@allowed([
  false
])
param applicationAndDataPublicNetworkAccess bool = false

@allowed([
  false
])
param generalInternetEgressEnabled bool = false

@allowed([
  '10.77.0.0/20'
])
param vnetCidr string = '10.77.0.0/20'

@allowed([
  '10.77.0.0/23'
])
param containerAppsCidr string = '10.77.0.0/23'

@allowed([
  '10.77.2.0/24'
])
param privateEndpointsCidr string = '10.77.2.0/24'

@allowed([
  '10.77.3.0/28'
])
param managementCleanupCidr string = '10.77.3.0/28'

@allowed([
  '10.77.3.32/27'
])
param gatewayCidr string = '10.77.3.32/27'

@allowed([
  '10.77.4.0/26'
])
param azureFirewallCidr string = '10.77.4.0/26'

@allowed([
  '10.77.4.64/26'
])
param azureFirewallManagementCidr string = '10.77.4.64/26'

@allowed([
  '10.77.5.0/28'
])
param dnsResolverInboundCidr string = '10.77.5.0/28'

@allowed([
  '10.77.5.4'
])
param dnsResolverInboundAddress string = '10.77.5.4'

@allowed([
  '10.250.77.0/24'
])
param p2sClientCidr string = '10.250.77.0/24'

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var vnetName = 'vnet-mobius77-staging'
var containerAppsSubnetName = 'snet-mobius77-containerapps'
var privateEndpointSubnetName = 'snet-mobius77-private-endpoints'
var dnsResolverSubnetName = 'snet-mobius77-dns-inbound'
var keyVaultPrivateDnsZoneName = 'privatelink.vaultcore.azure.net'
var registryPrivateDnsZoneName = 'privatelink.azurecr.io'

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2026-01-01' = if (enabled) {
  name: vnetName
  location: location
  tags: lifecycleTags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetCidr
      ]
    }
    subnets: [
      {
        name: containerAppsSubnetName
        properties: {
          addressPrefix: containerAppsCidr
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: privateEndpointSubnetName
        properties: {
          addressPrefix: privateEndpointsCidr
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-mobius77-management-cleanup'
        properties: {
          addressPrefix: managementCleanupCidr
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'GatewaySubnet'
        properties: {
          addressPrefix: gatewayCidr
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'AzureFirewallSubnet'
        properties: {
          addressPrefix: azureFirewallCidr
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'AzureFirewallManagementSubnet'
        properties: {
          addressPrefix: azureFirewallManagementCidr
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: dnsResolverSubnetName
        properties: {
          addressPrefix: dnsResolverInboundCidr
          delegations: [
            {
              name: 'Microsoft.Network.dnsResolvers'
              properties: {
                serviceName: 'Microsoft.Network/dnsResolvers'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource keyVaultPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: keyVaultPrivateDnsZoneName
  location: 'global'
  tags: lifecycleTags
}

resource keyVaultDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: keyVaultPrivateDnsZone
  name: 'link-mobius77-keyvault'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource registryPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (enabled) {
  name: registryPrivateDnsZoneName
  location: 'global'
  tags: lifecycleTags
}

resource registryDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (enabled) {
  parent: registryPrivateDnsZone
  name: 'link-mobius77-acr'
  location: 'global'
  tags: lifecycleTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource privateDnsResolver 'Microsoft.Network/dnsResolvers@2025-05-01' = if (enabled) {
  name: 'dnspr-mobius77-staging'
  location: location
  tags: lifecycleTags
  properties: {
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource privateDnsInboundEndpoint 'Microsoft.Network/dnsResolvers/inboundEndpoints@2025-05-01' = if (enabled) {
  parent: privateDnsResolver
  name: 'dnsin-mobius77-staging'
  location: location
  tags: lifecycleTags
  properties: {
    ipConfigurations: [
      {
        privateIpAddress: dnsResolverInboundAddress
        privateIpAllocationMethod: 'Static'
        subnet: {
          id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, dnsResolverSubnetName)
        }
      }
    ]
  }
}

resource vpnGatewayPublicIp 'Microsoft.Network/publicIPAddresses@2026-01-01' = if (enabled) {
  name: 'pip-mobius77-vpn'
  location: location
  tags: lifecycleTags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource vpnGateway 'Microsoft.Network/virtualNetworkGateways@2026-01-01' = if (enabled) {
  name: 'vpngw-mobius77-staging'
  location: location
  tags: lifecycleTags
  properties: {
    activeActive: false
    enableBgp: false
    gatewayType: 'Vpn'
    ipConfigurations: [
      {
        name: 'default'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: vpnGatewayPublicIp.id
          }
          subnet: {
            id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'GatewaySubnet')
          }
        }
      }
    ]
    sku: {
      name: 'VpnGw1'
      tier: 'VpnGw1'
    }
    vpnClientConfiguration: {
      aadAudience: 'c632b3df-fb67-4d84-bdcf-b95ad541b5c8'
      aadIssuer: 'https://sts.windows.net/${tenant().tenantId}/'
      aadTenant: 'https://login.microsoftonline.com/${tenant().tenantId}/'
      vpnAuthenticationTypes: [
        'AAD'
      ]
      vpnClientAddressPool: {
        addressPrefixes: [
          p2sClientCidr
        ]
      }
      vpnClientProtocols: [
        'OpenVPN'
      ]
    }
    vpnType: 'RouteBased'
  }
}

output moduleName string = 'network'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output vnetCidr string = vnetCidr
output privateSubnetCount int = 6
output infrastructurePublicIpCount int = infrastructurePublicIpCount
output applicationAndDataPublicNetworkAccess bool = applicationAndDataPublicNetworkAccess
output generalInternetEgressEnabled bool = generalInternetEgressEnabled
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output virtualNetworkId string = enabled ? virtualNetwork.id : ''
output containerAppsSubnetId string = enabled ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, containerAppsSubnetName) : ''
output privateEndpointSubnetId string = enabled ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, privateEndpointSubnetName) : ''
output keyVaultPrivateDnsZoneId string = enabled ? keyVaultPrivateDnsZone.id : ''
output registryPrivateDnsZoneId string = enabled ? registryPrivateDnsZone.id : ''
output privateDnsResolverAddress string = enabled ? dnsResolverInboundAddress : ''
output publicApplicationIngress bool = false
output publicKeyVaultAccess bool = false
