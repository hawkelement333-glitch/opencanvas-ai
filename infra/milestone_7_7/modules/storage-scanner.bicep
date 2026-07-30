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
  'Standard_LRS'
])
param storageSku string = 'Standard_LRS'

@allowed([
  'StorageV2'
])
param storageKind string = 'StorageV2'

@allowed([
  false
])
param sharedKeyAccess bool = false

@allowed([
  false
])
param anonymousAccess bool = false

@allowed([
  false
])
param publicNetworkAccess bool = false

@allowed([
  true
])
param versioningEnabled bool = true

@minValue(1)
@maxValue(1)
param defenderMonthlyCapGiB int = 1

@minValue(25)
@maxValue(25)
param scannerExerciseObjectCap int = 25

@minValue(26214400)
@maxValue(26214400)
param scannerExerciseBytesCap int = 26214400

@minValue(134217728)
@maxValue(134217728)
param totalSyntheticUploadBytesCap int = 134217728

@allowed([
  false
])
param scannerResultBridgeResolved bool = false

output moduleName string = 'storage-scanner'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output storageSku string = storageSku
output storageKind string = storageKind
output sharedKeyAccess bool = sharedKeyAccess
output anonymousAccess bool = anonymousAccess
output publicNetworkAccess bool = publicNetworkAccess
output versioningEnabled bool = versioningEnabled
output defenderMonthlyCapGiB int = defenderMonthlyCapGiB
output scannerExerciseObjectCap int = scannerExerciseObjectCap
output scannerExerciseBytesCap int = scannerExerciseBytesCap
output totalSyntheticUploadBytesCap int = totalSyntheticUploadBytesCap
output scannerResultBridgeResolved bool = scannerResultBridgeResolved
