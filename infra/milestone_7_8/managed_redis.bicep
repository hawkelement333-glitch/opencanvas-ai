// M78-D-002 only. Independent cleanup authority must be armed before deployment.
// Reuses the admitted image; the probe is a separate hash-bound execution input.
targetScope = 'resourceGroup'

@allowed(['canadacentral'])
param location string = 'canadacentral'
@minLength(10)
@maxLength(10)
param resourceNameSuffix string
param lifecycleTags object
@allowed(['foundation', 'workload'])
param deploymentStage string = 'foundation'
param imageDigest string = ''
param probeSource string = ''
param probeSha256 string = ''
param probeEnvironment array = []
@secure()
param hmacSecret string = ''
param sourceBaseCommit string = ''

var prefix = 'm78r-${resourceNameSuffix}'
var namespace = 'm78r${resourceNameSuffix}'
var workloadEnabled = deploymentStage == 'workload'
var replicas = ['leader', 'follower']
var dnsNames = ['privatelink.redis.azure.net', 'privatelink.azurecr.io']
var dnsTags = toObject(filter(items(lifecycleTags), tag => tag.key != 'mobius.expiry'), tag => tag.key, tag => tag.value)
var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
// RateLimitService._key uses namespace:rl:v1:{limits}:... . The frozen 7.7
// ~mobius:v1:* ACL cannot authorize these keys. No category-wide commands granted.
var redisAccessString = '+ping +eval +time +hmget +hset +pexpire +get +set +pttl +exists ~${namespace}:rl:v1:{limits}:* ~${namespace}:control:{limits}:*'
var sourceVerifier = 'import hashlib,hmac,os,sys; s=os.environ["M78_EXECUTION_SOURCE"]; hmac.compare_digest(hashlib.sha256(s.encode("utf-8")).hexdigest(),os.environ["M78_EXECUTION_SHA256"]) or sys.exit("execution source hash mismatch"); exec(compile(s,"<m78-d002-bound-probe>","exec"))'

// Exact outbound Redis failure rule is injected/removed separately under the
// approved execution package. Initial rules are empty; all other traffic is unchanged.
resource workloadNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${prefix}'
  location: location
  tags: lifecycleTags
  properties: { securityRules: [] }
}
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    addressSpace: { addressPrefixes: ['10.80.0.0/16'] }
    subnets: [
      {
        name: 'container-apps'
        properties: {
          addressPrefix: '10.80.4.0/23'
          networkSecurityGroup: { id: workloadNsg.id }
          delegations: [{ name: 'container-apps', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      { name: 'private-endpoints', properties: { addressPrefix: '10.80.8.0/24', privateEndpointNetworkPolicies: 'Disabled' } }
    ]
  }
}
resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = [for replica in replicas: {
  name: 'id-${prefix}-${replica}'
  location: location
  tags: lifecycleTags
}]
resource cache 'Microsoft.Cache/redisEnterprise@2026-05-01-preview' = {
  name: 'redis-${prefix}'
  location: location
  tags: lifecycleTags
  sku: { name: 'Balanced_B0' }
  properties: {
    minimumTlsVersion: '1.2'
    highAvailability: 'Enabled'
    publicNetworkAccess: 'Disabled'
  }
}
resource database 'Microsoft.Cache/redisEnterprise/databases@2026-05-01-preview' = {
  parent: cache
  name: 'default'
  properties: {
    accessKeysAuthentication: 'Disabled'
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'NoCluster'
    evictionPolicy: 'NoEviction'
    modules: []
    port: 10000
  }
}
resource redisAssignments 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2026-05-01-preview' = [for (replica, index) in replicas: {
  parent: database
  name: 'm78${resourceNameSuffix}${replica}'
  properties: { accessString: redisAccessString, user: { objectId: identities[index].properties.principalId } }
}]
resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'crm78r${resourceNameSuffix}'
  location: location
  tags: lifecycleTags
  sku: { name: 'Premium' }
  properties: { adminUserEnabled: false, publicNetworkAccess: 'Disabled', zoneRedundancy: 'Disabled' }
}
resource registryReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (replica, index) in replicas: {
  scope: registry
  name: guid(registry.id, identities[index].id, 'acr-pull')
  properties: { roleDefinitionId: acrPullRoleId, principalId: identities[index].properties.principalId, principalType: 'ServicePrincipal' }
}]
resource dnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for dnsName in dnsNames: {
  name: dnsName
  location: 'global'
  tags: dnsTags
}]
resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (dnsName, index) in dnsNames: {
  parent: dnsZones[index]
  name: prefix
  location: 'global'
  tags: dnsTags
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}]
var endpoints = [
  { key: 'redis', id: cache.id, group: 'redisEnterprise' }
  { key: 'registry', id: registry.id, group: 'registry' }
]
resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-10-01' = [for endpoint in endpoints: {
  name: 'pe-${prefix}-${endpoint.key}'
  location: location
  tags: lifecycleTags
  properties: {
    subnet: { id: '${network.id}/subnets/private-endpoints' }
    privateLinkServiceConnections: [{ name: endpoint.key, properties: { privateLinkServiceId: endpoint.id, groupIds: [endpoint.group] } }]
  }
  dependsOn: [database]
}]
resource endpointDnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-10-01' = [for (endpoint, index) in endpoints: {
  parent: privateEndpoints[index]
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: endpoint.key, properties: { privateDnsZoneId: dnsZones[index].id } }] }
  dependsOn: [dnsLinks]
}]
resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: 'cae-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    appLogsConfiguration: { destination: 'none' }
    vnetConfiguration: { infrastructureSubnetId: '${network.id}/subnets/container-apps', internal: true }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    zoneRedundant: false
  }
  dependsOn: [endpointDnsGroups]
}
resource jobs 'Microsoft.App/jobs@2025-01-01' = [for (replica, index) in replicas: if (workloadEnabled) {
  name: 'caj-${prefix}-${replica}'
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identities[index].id}': {} } }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      secrets: [{ name: 'rate-limit-hmac', value: hmacSecret }]
      replicaRetryLimit: 0
      replicaTimeout: 1200
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ identity: identities[index].id, server: registry.properties.loginServer }]
    }
    template: {
      containers: [{
        name: 'managed-redis'
        image: '${registry.properties.loginServer}/opencanvas-api@${imageDigest}'
        command: ['python']
        args: ['-c', sourceVerifier]
        env: concat([
          { name: 'M78_EXECUTION_SOURCE', value: probeSource }
          { name: 'M78_EXECUTION_SHA256', value: probeSha256 }
          { name: 'OPENCANVAS_REDIS_PROBE_SHA256', value: probeSha256 }
          { name: 'OPENCANVAS_REDIS_PROBE_IMAGE_DIGEST', value: imageDigest }
          { name: 'OPENCANVAS_REDIS_PROBE_SOURCE_COMMIT', value: sourceBaseCommit }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET', secretRef: 'rate-limit-hmac' }
          { name: 'OPENCANVAS_REDIS_PROBE_REPLICA', value: replica }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER', value: 'redis' }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_AUTH_MODE', value: 'entra' }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_URL', value: 'rediss://${cache.properties.hostName}:10000/0' }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: identities[index].properties.principalId }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: identities[index].properties.clientId }
          { name: 'OPENCANVAS_SHARED_RATE_LIMIT_NAMESPACE', value: namespace }
        ], probeEnvironment)
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
    }
  }
  dependsOn: [redisAssignments, registryReaders]
}]

output jobNames array = [for replica in replicas: 'caj-${prefix}-${replica}']
output redisId string = cache.id
output redisDatabaseId string = database.id
output redisHostName string = cache.properties.hostName
output redisPort int = 10000
output redisAccessString string = redisAccessString
output rateLimitNamespace string = namespace
output registryId string = registry.id
output registryLoginServer string = registry.properties.loginServer
output environmentId string = managedEnvironment.id
output virtualNetworkId string = network.id
output nsgId string = workloadNsg.id
output workloadSubnetId string = '${network.id}/subnets/container-apps'
output endpointIds array = [for endpoint in endpoints: resourceId('Microsoft.Network/privateEndpoints', 'pe-${prefix}-${endpoint.key}')]
output privateDnsZoneIds array = [for dnsName in dnsNames: resourceId('Microsoft.Network/privateDnsZones', dnsName)]
output identityBindings array = [for (replica, index) in replicas: {
  replica: replica
  id: identities[index].id
  name: identities[index].name
  principalId: identities[index].properties.principalId
  clientId: identities[index].properties.clientId
  jobId: resourceId('Microsoft.App/jobs', 'caj-${prefix}-${replica}')
  redisAssignmentId: resourceId('Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments', cache.name, 'default', 'm78${resourceNameSuffix}${replica}')
  registryRoleAssignmentId: extensionResourceId(registry.id, 'Microsoft.Authorization/roleAssignments', guid(registry.id, identities[index].id, 'acr-pull'))
}]
