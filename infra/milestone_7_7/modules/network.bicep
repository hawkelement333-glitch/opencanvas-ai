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

output moduleName string = 'network'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output vnetCidr string = vnetCidr
output privateSubnetCount int = 6
output infrastructurePublicIpCount int = infrastructurePublicIpCount
output applicationAndDataPublicNetworkAccess bool = applicationAndDataPublicNetworkAccess
output generalInternetEgressEnabled bool = generalInternetEgressEnabled
