targetScope = 'subscription'

@minLength(8)
@maxLength(48)
param campaignId string

@minLength(15)
@maxLength(24)
param generationId string

@minLength(16)
@maxLength(16)
param subscriptionCorrelation string

param targetResourceGroupName string
param cleanupResourceGroupName string
param cleanupLocation string
@minLength(64)
@maxLength(64)
param cleanupRegionSelectionSha256 string
param cleanupOfferClassification string
param cleanupOfferEligibilityDisposition string
param cleanupOfferEligibleRegions string
param cleanupOfferEligibilitySource string
@minLength(64)
@maxLength(64)
param cleanupOfferEligibilitySha256 string
param cleanupDeadlineUtc string
param automationAccountName string
param cleanupRunbookName string
param cleanupScheduleName string

@minValue(5000)
@maxValue(5000)
param costCeilingCents int = 5000

param lifecycleTags object

resource cleanupResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: cleanupResourceGroupName
  location: cleanupLocation
  tags: lifecycleTags
}

module controller './modules/cleanup-controller.bicep' = {
  name: 'm78-cleanup-${uniqueString(campaignId, generationId)}'
  scope: cleanupResourceGroup
  params: {
    campaignId: campaignId
    generationId: generationId
    subscriptionCorrelation: subscriptionCorrelation
    targetResourceGroupName: targetResourceGroupName
    cleanupResourceGroupName: cleanupResourceGroupName
    cleanupLocation: cleanupLocation
    cleanupRegionSelectionSha256: cleanupRegionSelectionSha256
    cleanupOfferClassification: cleanupOfferClassification
    cleanupOfferEligibilityDisposition: cleanupOfferEligibilityDisposition
    cleanupOfferEligibleRegions: cleanupOfferEligibleRegions
    cleanupOfferEligibilitySource: cleanupOfferEligibilitySource
    cleanupOfferEligibilitySha256: cleanupOfferEligibilitySha256
    cleanupDeadlineUtc: cleanupDeadlineUtc
    automationAccountName: automationAccountName
    cleanupRunbookName: cleanupRunbookName
    cleanupScheduleName: cleanupScheduleName
    costCeilingCents: costCeilingCents
    lifecycleTags: lifecycleTags
  }
}

resource targetResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' existing = {
  name: targetResourceGroupName
}

// The cleanup identity receives resource deletion plus RBAC-extension deletion only
// at the two exact campaign resource-group scopes. Built-ins avoid a persistent
// subscription custom-role definition after the campaign groups are gone.
var contributorRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b24988ac-6180-42a0-ab88-20f7382dd24c'
)
var rbacAdministratorRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
)

module targetContributorAssignment './modules/cleanup-rbac.bicep' = {
  name: 'm78-target-cleanup-contributor-${uniqueString(campaignId, generationId)}'
  scope: targetResourceGroup
  params: {
    principalId: controller.outputs.cleanupPrincipalId
    roleDefinitionId: contributorRoleDefinitionId
  }
}

module targetRbacAssignment './modules/cleanup-rbac.bicep' = {
  name: 'm78-target-cleanup-rbac-${uniqueString(campaignId, generationId)}'
  scope: targetResourceGroup
  params: {
    principalId: controller.outputs.cleanupPrincipalId
    roleDefinitionId: rbacAdministratorRoleDefinitionId
  }
}

module selfContributorAssignment './modules/cleanup-rbac.bicep' = {
  name: 'm78-self-cleanup-contributor-${uniqueString(campaignId, generationId)}'
  scope: cleanupResourceGroup
  params: {
    principalId: controller.outputs.cleanupPrincipalId
    roleDefinitionId: contributorRoleDefinitionId
  }
}

module selfRbacAssignment './modules/cleanup-rbac.bicep' = {
  name: 'm78-self-cleanup-rbac-${uniqueString(campaignId, generationId)}'
  scope: cleanupResourceGroup
  params: {
    principalId: controller.outputs.cleanupPrincipalId
    roleDefinitionId: rbacAdministratorRoleDefinitionId
  }
}

output automationAccountName string = controller.outputs.automationAccountName
output cleanupPrincipalId string = controller.outputs.cleanupPrincipalId
output runbookName string = controller.outputs.runbookName
output scheduleName string = controller.outputs.scheduleName
output bindingName string = controller.outputs.bindingName
output cleanupRoleDefinitionIds object = {
  contributor: contributorRoleDefinitionId
  rbacAdministrator: rbacAdministratorRoleDefinitionId
}
output targetRoleAssignmentIds array = [
  targetContributorAssignment.outputs.roleAssignmentId
  targetRbacAssignment.outputs.roleAssignmentId
]
output selfRoleAssignmentIds array = [
  selfContributorAssignment.outputs.roleAssignmentId
  selfRbacAssignment.outputs.roleAssignmentId
]
output cleanupDeadlineUtc string = cleanupDeadlineUtc
output campaignId string = campaignId
output generationId string = generationId
output subscriptionCorrelation string = subscriptionCorrelation
output targetResourceGroupName string = targetResourceGroupName
output cleanupResourceGroupName string = cleanupResourceGroupName
output cleanupLocation string = cleanupLocation
output cleanupRegionSelectionSha256 string = cleanupRegionSelectionSha256
output cleanupOfferClassification string = cleanupOfferClassification
output cleanupOfferEligibilityDisposition string = cleanupOfferEligibilityDisposition
output cleanupOfferEligibleRegions string = cleanupOfferEligibleRegions
output cleanupOfferEligibilitySource string = cleanupOfferEligibilitySource
output cleanupOfferEligibilitySha256 string = cleanupOfferEligibilitySha256
output costCeilingCents int = costCeilingCents
output scheduleCount int = 1
