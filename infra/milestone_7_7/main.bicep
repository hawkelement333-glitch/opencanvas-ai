targetScope = 'subscription'

@description('Checkpoint 1 is permanently contract-only.')
@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@description('Checkpoint 1 cannot enable deployment.')
@allowed([
  false
])
param deploymentEnabled bool = false

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

// No module is invoked in Checkpoint 1. Direct compilation remains resource-free.
output contractVersion string = 'm7.7-infrastructure-contract-v1'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output moduleCount int = length(moduleBoundaries)
output unresolvedGateCount int = length(unresolvedGates)
