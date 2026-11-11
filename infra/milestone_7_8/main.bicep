targetScope = 'subscription'

param campaignId string
param generationId string
@minLength(10)
@maxLength(10)
param resourceNameSuffix string
param subscriptionCorrelation string
param targetResourceGroupName string
param targetLocation string
param postgresLocation string
param cleanupLocation string
@minLength(64)
@maxLength(64)
param cleanupRegionSelectionSha256 string
param cleanupCandidateRegions string
param cleanupOfferClassification string
param cleanupOfferEligibilityDisposition string
param cleanupOfferEligibleRegions string
param cleanupOfferEligibilitySource string
param cleanupOfferEligibilitySha256 string
@minLength(64)
@maxLength(64)
param freshControllerAdmissionEvidenceSha256 string
param cleanupResourceGroupName string
param cleanupAutomationAccountName string
param tenantId string
param postgresServerName string
param postgresSkuName string = 'Standard_D2ds_v4'
param postgresVersion string = '17'
param postgresStorageGiB int = 64
param postgresPrimaryZone string
param postgresStandbyZone string
param backupRetentionDays int = 7
param maintenanceDay int
param maintenanceHour int
param maintenanceMinute int = 0
param registryName string
@allowed([ 'base', 'workload' ])
param deploymentStage string = 'base'
param imageDigest string = ''
param containerAppsEnvironmentName string
param virtualNetworkName string
param privateDnsZoneName string = 'private.postgres.database.azure.com'
param logAnalyticsWorkspaceName string
param administratorIdentityName string
param migrationIdentityName string
param apiIdentityName string
param workerIdentityName string
param evidenceIdentityName string
param cleanupIdentityName string
param cleanupDeadlineUtc string

@minValue(4)
@maxValue(4)
param maximumHours int = 4

@minValue(5000)
@maxValue(5000)
param costCeilingCents int = 5000

param lifecycleTags object

resource targetResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: targetResourceGroupName
  location: targetLocation
  tags: lifecycleTags
}

resource cleanupResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' existing = {
  name: cleanupResourceGroupName
}

resource cleanupAutomationAccount 'Microsoft.Automation/automationAccounts@2024-10-23' existing = {
  name: cleanupAutomationAccountName
  scope: cleanupResourceGroup
}

module identities './modules/identities.bicep' = {
  name: 'm78-identities-${uniqueString(campaignId, generationId)}'
  scope: targetResourceGroup
  params: {
    targetLocation: targetLocation
    administratorIdentityName: administratorIdentityName
    migrationIdentityName: migrationIdentityName
    apiIdentityName: apiIdentityName
    workerIdentityName: workerIdentityName
    evidenceIdentityName: evidenceIdentityName
    lifecycleTags: lifecycleTags
  }
}

module campaign './modules/campaign-resources.bicep' = {
  name: 'm78-campaign-${uniqueString(campaignId, generationId)}'
  scope: targetResourceGroup
  params: {
    campaignId: campaignId
    generationId: generationId
    resourceNameSuffix: resourceNameSuffix
    subscriptionCorrelation: subscriptionCorrelation
    targetLocation: targetLocation
    postgresLocation: postgresLocation
    cleanupLocation: cleanupLocation
    cleanupRegionSelectionSha256: cleanupRegionSelectionSha256
    cleanupCandidateRegions: cleanupCandidateRegions
    cleanupOfferClassification: cleanupOfferClassification
    cleanupOfferEligibilityDisposition: cleanupOfferEligibilityDisposition
    cleanupOfferEligibleRegions: cleanupOfferEligibleRegions
    cleanupOfferEligibilitySource: cleanupOfferEligibilitySource
    cleanupOfferEligibilitySha256: cleanupOfferEligibilitySha256
    freshControllerAdmissionEvidenceSha256: freshControllerAdmissionEvidenceSha256
    cleanupResourceGroupName: cleanupResourceGroupName
    tenantId: tenantId
    postgresServerName: postgresServerName
    postgresSkuName: postgresSkuName
    postgresVersion: postgresVersion
    postgresStorageGiB: postgresStorageGiB
    postgresPrimaryZone: postgresPrimaryZone
    postgresStandbyZone: postgresStandbyZone
    backupRetentionDays: backupRetentionDays
    maintenanceDay: maintenanceDay
    maintenanceHour: maintenanceHour
    maintenanceMinute: maintenanceMinute
    registryName: registryName
    imageDigest: imageDigest
    deploymentStage: deploymentStage
    containerAppsEnvironmentName: containerAppsEnvironmentName
    virtualNetworkName: virtualNetworkName
    privateDnsZoneName: privateDnsZoneName
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    administratorIdentityName: administratorIdentityName
    migrationIdentityName: migrationIdentityName
    apiIdentityName: apiIdentityName
    workerIdentityName: workerIdentityName
    evidenceIdentityName: evidenceIdentityName
    cleanupIdentityName: cleanupIdentityName
    bootstrapIdentity: identities.outputs.bootstrap
    migrationIdentity: identities.outputs.migration
    apiIdentity: identities.outputs.api
    workerIdentity: identities.outputs.worker
    evidenceIdentity: identities.outputs.evidence
    cleanupPrincipalId: cleanupAutomationAccount.identity.principalId
    cleanupDeadlineUtc: cleanupDeadlineUtc
    maximumHours: maximumHours
    costCeilingCents: costCeilingCents
    lifecycleTags: lifecycleTags
  }
}

output postgresServerName string = campaign.outputs.postgresServerName
output bootstrapJobName string = campaign.outputs.bootstrapJobName
output migrationJobName string = campaign.outputs.migrationJobName
output evidenceJobName string = campaign.outputs.evidenceJobName
output workerJobName string = campaign.outputs.workerJobName
output apiAppName string = campaign.outputs.apiAppName
output apiProbeJobName string = campaign.outputs.apiProbeJobName
output workerProbeJobName string = campaign.outputs.workerProbeJobName
output migrationProbeJobName string = campaign.outputs.migrationProbeJobName
output recoveryJobName string = campaign.outputs.recoveryJobName
output recoveryRestoreJobName string = campaign.outputs.recoveryRestoreJobName
output registryLoginServer string = campaign.outputs.registryLoginServer
output identityObjectIds object = campaign.outputs.identityObjectIds
output campaignBinding object = campaign.outputs.campaignBinding
output campaignId string = campaignId
output generationId string = generationId
output deploymentStage string = deploymentStage
output imageDigest string = imageDigest
