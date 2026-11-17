// Selected temporary access option. Deployment still needs separate approval.
targetScope = 'resourceGroup'

@allowed(['eastus'])
param location string = 'eastus'
@minLength(10)
@maxLength(10)
param suffix string
param lifecycleTags object
param virtualNetworkName string
param workspaceName string
@minLength(36)
@maxLength(36)
@description('Native appId of the campaign-only, single-tenant audience with assignment required and exactly one approved user assignment.')
param audienceAppId string

var prefix = 'm78p-${suffix}'
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' existing = { name: virtualNetworkName }
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = { name: workspaceName }
resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-${prefix}-vpn'
  location: location
  tags: lifecycleTags
  sku: { name: 'Standard', tier: 'Regional' }
  zones: ['1', '2', '3']
  properties: { publicIPAllocationMethod: 'Static', publicIPAddressVersion: 'IPv4' }
}
resource gateway 'Microsoft.Network/virtualNetworkGateways@2024-05-01' = {
  name: 'vpngw-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    activeActive: false
    enableBgp: false
    sku: { name: 'VpnGw1AZ', tier: 'VpnGw1AZ' }
    vpnGatewayGeneration: 'Generation1'
    ipConfigurations: [{
      name: 'operator'
      properties: {
        privateIPAllocationMethod: 'Dynamic'
        publicIPAddress: { id: publicIp.id }
        subnet: { id: '${network.id}/subnets/GatewaySubnet' }
      }
    }]
    vpnClientConfiguration: {
      vpnClientAddressPool: { addressPrefixes: ['172.31.240.0/24'] }
      vpnClientProtocols: ['OpenVPN']
      vpnAuthenticationTypes: ['AAD']
      aadTenant: '${environment().authentication.loginEndpoint}${tenant().tenantId}'
      aadAudience: audienceAppId
      aadIssuer: 'https://sts.windows.net/${tenant().tenantId}/'
    }
  }
}
resource resolver 'Microsoft.Network/dnsResolvers@2022-07-01' = {
  name: 'dnsr-${prefix}'
  location: location
  tags: lifecycleTags
  properties: { virtualNetwork: { id: network.id } }
}
resource inbound 'Microsoft.Network/dnsResolvers/inboundEndpoints@2022-07-01' = {
  parent: resolver
  name: 'operator-inbound'
  location: location
  tags: lifecycleTags
  properties: {
    ipConfigurations: [{
      privateIpAllocationMethod: 'Static'
      privateIpAddress: '10.79.9.36'
      subnet: { id: '${network.id}/subnets/operator-dns' }
    }]
  }
}
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: gateway
  name: 'operator-route'
  properties: {
    workspaceId: workspace.id
    logs: [for category in ['GatewayDiagnosticLog', 'TunnelDiagnosticLog', 'RouteDiagnosticLog', 'IKEDiagnosticLog', 'P2SDiagnosticLog']: {
      category: category
      enabled: true
    }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}
// DNS Resolver metrics do not support diagnostic-settings export. Retain the
// exact native metric GET plus real client DNS results; do not invent log types.
output bindings object = {
  gatewayId: gateway.id
  publicIpId: publicIp.id
  resolverId: resolver.id
  inboundEndpointId: inbound.id
  gatewaySubnetId: '${network.id}/subnets/GatewaySubnet'
  resolverSubnetId: '${network.id}/subnets/operator-dns'
  clientPool: '172.31.240.0/24'
  dnsServer: '10.79.9.36'
  routePrefix: '10.79.0.0/16'
  audienceAppId: audienceAppId
  microsoftClientAppId: 'c632b3df-fb67-4d84-bdcf-b95ad541b5c8'
}
