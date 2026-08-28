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
param cleanupCandidateRegions string
param cleanupOfferClassification string
param cleanupOfferEligibilityDisposition string
param cleanupOfferEligibleRegions string
param cleanupOfferEligibilitySource string
@minLength(64)
@maxLength(64)
param cleanupOfferEligibilitySha256 string
@minLength(64)
@maxLength(64)
param retentionAbsenceEvidenceSha256 string
param cleanupDeadlineUtc string
param cleanupAuthorityExpiresUtc string
param automationAccountName string
param cleanupRunbookName string
param cleanupScheduleName string
param cleanupBindingName string

@minValue(5000)
@maxValue(5000)
param costCeilingCents int = 5000

// The campaign path may only adopt the one separately provisioned reusable
// controller. This template cannot create, delete, or replace an Automation
// account, controller resource group, or runbook.
resource controllerResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' existing = {
  name: cleanupResourceGroupName
}

resource controllerAccount 'Microsoft.Automation/automationAccounts@2024-10-23' existing = {
  scope: controllerResourceGroup
  name: automationAccountName
}

resource controllerRunbook 'Microsoft.Automation/automationAccounts/runbooks@2024-10-23' existing = {
  parent: controllerAccount
  name: cleanupRunbookName
}

resource targetResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' existing = {
  name: targetResourceGroupName
}

// Temporary authority exists only at the exact campaign target scope. The
// target resource-group deletion removes both grants. The persistent controller
// has no permission to delete or mutate its own control plane.
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
    principalId: controllerAccount.identity.principalId
    roleDefinitionId: contributorRoleDefinitionId
  }
}

module targetRbacAssignment './modules/cleanup-rbac.bicep' = {
  name: 'm78-target-cleanup-rbac-${uniqueString(campaignId, generationId)}'
  scope: targetResourceGroup
  params: {
    principalId: controllerAccount.identity.principalId
    roleDefinitionId: rbacAdministratorRoleDefinitionId
  }
}

output automationAccountName string = controllerAccount.name
output cleanupPrincipalId string = controllerAccount.identity.principalId
output runbookName string = controllerRunbook.name
output scheduleName string = cleanupScheduleName
output bindingName string = cleanupBindingName
output cleanupRoleDefinitionIds object = {
  contributor: contributorRoleDefinitionId
  rbacAdministrator: rbacAdministratorRoleDefinitionId
}
output targetRoleAssignmentIds array = [
  targetContributorAssignment.outputs.roleAssignmentId
  targetRbacAssignment.outputs.roleAssignmentId
]
output campaignId string = campaignId
output generationId string = generationId
output subscriptionCorrelation string = subscriptionCorrelation
output targetResourceGroupName string = targetResourceGroupName
output cleanupResourceGroupName string = cleanupResourceGroupName
output cleanupLocation string = cleanupLocation
output cleanupRegionSelectionSha256 string = cleanupRegionSelectionSha256
output cleanupCandidateRegions string = cleanupCandidateRegions
output cleanupOfferClassification string = cleanupOfferClassification
output cleanupOfferEligibilityDisposition string = cleanupOfferEligibilityDisposition
output cleanupOfferEligibleRegions string = cleanupOfferEligibleRegions
output cleanupOfferEligibilitySource string = cleanupOfferEligibilitySource
output cleanupOfferEligibilitySha256 string = cleanupOfferEligibilitySha256
output retentionAbsenceEvidenceSha256 string = retentionAbsenceEvidenceSha256
output cleanupDeadlineUtc string = cleanupDeadlineUtc
output cleanupAuthorityExpiresUtc string = cleanupAuthorityExpiresUtc
output costCeilingCents int = costCeilingCents
output scheduleCount int = 0
output bindingCount int = 0
