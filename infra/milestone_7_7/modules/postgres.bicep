targetScope = 'subscription'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

@minValue(17)
@maxValue(17)
param majorVersion int = 17

@allowed([
  'Standard_D2ds_v5'
])
param serverSku string = 'Standard_D2ds_v5'

@minValue(64)
@maxValue(64)
param storageGiB int = 64

@allowed([
  false
])
param storageAutogrow bool = false

@allowed([
  'ZoneRedundant'
])
param highAvailability string = 'ZoneRedundant'

@minValue(7)
@maxValue(7)
param backupRetentionDays int = 7

@allowed([
  'LRS'
])
param backupRedundancy string = 'LRS'

@allowed([
  false
])
param publicNetworkAccess bool = false

output moduleName string = 'postgres'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output majorVersion int = majorVersion
output serverSku string = serverSku
output storageGiB int = storageGiB
output storageAutogrow bool = storageAutogrow
output highAvailability string = highAvailability
output backupRetentionDays int = backupRetentionDays
output backupRedundancy string = backupRedundancy
output publicNetworkAccess bool = publicNetworkAccess
