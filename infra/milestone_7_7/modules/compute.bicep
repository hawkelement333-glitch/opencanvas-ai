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
  'internal-azure-container-apps'
])
param computeTopology string = 'internal-azure-container-apps'

@allowed([
  'Consumption'
])
param workloadProfile string = 'Consumption'

@minValue(8)
@maxValue(8)
param imageBindingCount int = 8

@allowed([
  false
])
param imageDigestContractResolved bool = false

var serviceShapeContract = {
  web: {
    cpuMilli: 250
    memoryMiB: 512
    minReplicas: 1
    normalReplicas: 1
    maxReplicas: 2
  }
  api: {
    cpuMilli: 500
    memoryMiB: 1024
    minReplicas: 2
    normalReplicas: 2
    maxReplicas: 4
  }
  sharedWorkerPool: {
    cpuMilli: 500
    memoryMiB: 1024
    minReplicas: 2
    normalReplicas: 2
    maxReplicas: 4
    workKinds: [
      'indexer'
      'scan'
      'workflow'
      'agent'
    ]
  }
  telemetryGateway: {
    cpuMilli: 250
    memoryMiB: 512
    minReplicas: 1
    normalReplicas: 1
    maxReplicas: 1
  }
}

var jobShapeContract = {
  migration: {
    cpuMilli: 500
    memoryMiB: 1024
    idleExecutions: 0
    maxParallelExecutions: 1
  }
  loadGenerator: {
    cpuMilli: 1000
    memoryMiB: 2048
    idleExecutions: 0
    maxParallelExecutions: 1
  }
  faultController: {
    cpuMilli: null
    memoryMiB: null
    idleExecutions: 0
    maxParallelExecutions: 1
    shapeResolutionStatus: 'deferred-to-failure-runner-checkpoint'
  }
}

output moduleName string = 'compute'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output computeTopology string = computeTopology
output workloadProfile string = workloadProfile
output imageBindingCount int = imageBindingCount
output imageDigestContractResolved bool = imageDigestContractResolved
output serviceShapeContract object = serviceShapeContract
output jobShapeContract object = jobShapeContract
