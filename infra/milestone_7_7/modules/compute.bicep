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

param applicationDeploymentEnabled bool = false

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param containerAppsSubnetId string = ''
@allowed([
  'rg-solarplexus-mobius-77-containerapps-infrastructure'
])
param infrastructureResourceGroupName string = 'rg-solarplexus-mobius-77-containerapps-infrastructure'
param workloadIdentityId string = ''
param keyVaultName string = ''
param registryLoginServer string = ''
param apiImageDigest string = ''
@allowed([
  'sandbox.smtp.mailtrap.io'
])
param smtpHost string = 'sandbox.smtp.mailtrap.io'

@allowed([
  'mobius77-validation@example.invalid'
])
param smtpFromAddress string = 'mobius77-validation@example.invalid'
param lifecycleTags object = {}

var enabled = managedBindingMode == 'managed-binding-one-run' && managedBindingDeploymentEnabled
var appEnabled = enabled && applicationDeploymentEnabled
var environmentName = 'cae-mobius77-staging'
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

resource managedEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' = if (enabled) {
  name: environmentName
  location: location
  tags: lifecycleTags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    publicNetworkAccess: 'Disabled'
    infrastructureResourceGroup: infrastructureResourceGroupName
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnetId
      internal: true
    }
    zoneRedundant: false
  }
}

resource apiContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (appEnabled) {
  name: 'ca-mobius77-api'
  location: location
  tags: lifecycleTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workloadIdentityId}': {}
    }
  }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: false
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          identity: workloadIdentityId
          server: registryLoginServer
        }
      ]
      secrets: [
        {
          identity: workloadIdentityId
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/openai-api-key'
          name: 'openai-api-key'
        }
        {
          identity: workloadIdentityId
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/opencanvas-smtp-username'
          name: 'opencanvas-smtp-username'
        }
        {
          identity: workloadIdentityId
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/opencanvas-smtp-password'
          name: 'opencanvas-smtp-password'
        }
      ]
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          env: [
            {
              name: 'OPENAI_API_KEY'
              secretRef: 'openai-api-key'
            }
            {
              name: 'OPENCANVAS_SMTP_USERNAME'
              secretRef: 'opencanvas-smtp-username'
            }
            {
              name: 'OPENCANVAS_SMTP_PASSWORD'
              secretRef: 'opencanvas-smtp-password'
            }
            {
              name: 'OPENCANVAS_AI_PROVIDER'
              value: 'openai'
            }
            {
              name: 'OPENCANVAS_EMBEDDING_PROVIDER'
              value: 'openai'
            }
            {
              name: 'OPENCANVAS_PASSWORD_RESET_PROVIDER'
              value: 'smtp'
            }
            {
              name: 'OPENCANVAS_SMTP_HOST'
              value: smtpHost
            }
            {
              name: 'OPENCANVAS_SMTP_FROM_ADDRESS'
              value: smtpFromAddress
            }
            {
              name: 'OPENCANVAS_SMTP_PORT'
              value: '2525'
            }
            {
              name: 'OPENCANVAS_SMTP_STARTTLS'
              value: 'true'
            }
          ]
          image: apiImageDigest
          name: 'api'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        maxReplicas: 4
        minReplicas: 2
      }
    }
    workloadProfileName: 'Consumption'
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
output managedBindingMode string = managedBindingMode
output managedBindingDeploymentEnabled bool = enabled
output applicationDeploymentEnabled bool = appEnabled
output managedEnvironmentId string = enabled ? managedEnvironment.id : ''
output infrastructureResourceGroupName string = infrastructureResourceGroupName
output apiContainerAppId string = appEnabled ? apiContainerApp.id : ''
output managedEnvironmentDefaultDomain string = enabled ? managedEnvironment.properties.defaultDomain : ''
output managedEnvironmentStaticIp string = enabled ? managedEnvironment.properties.staticIp : ''
output publicApplicationIngress bool = false
output configuredOpenAiAlias string = 'OPENAI_API_KEY'
output alternativeOpenAiAliasConfigured bool = false
