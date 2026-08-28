targetScope = 'subscription'

@minLength(16)
@maxLength(16)
param subscriptionCorrelation string
param controllerResourceGroupName string
param controllerLocation string
param automationAccountName string
param cleanupRunbookName string = 'Remove-M78Campaign'
param controllerAuthorizedUntilUtc string
@minLength(64)
@maxLength(64)
param cleanupScriptSha256 string
@minLength(64)
@maxLength(64)
param retentionAbsenceEvidenceSha256 string

var controllerTags = {
  'mobius.milestone': '7.8'
  'mobius.owner': 'managed-postgresql-evidence'
  'mobius.cleanup-controller': 'reusable-automation-controller-v1'
  'mobius.subscription-correlation': subscriptionCorrelation
  'mobius.controller-authorized-until-utc': controllerAuthorizedUntilUtc
  'mobius.cleanup-script-sha256': cleanupScriptSha256
  'mobius.retention-absence-sha256': retentionAbsenceEvidenceSha256
}

resource controllerResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: controllerResourceGroupName
  location: controllerLocation
  tags: controllerTags
}

module controller './modules/cleanup-controller.bicep' = {
  name: 'm78-reusable-cleanup-controller'
  scope: controllerResourceGroup
  params: {
    cleanupLocation: controllerLocation
    automationAccountName: automationAccountName
    cleanupRunbookName: cleanupRunbookName
    lifecycleTags: controllerTags
  }
}

// The controller can read and revalidate its own immutable control-plane
// contract. It cannot mutate or delete the account, runbook, group, schedules,
// or bindings. Campaign-scoped deletion authority is granted separately.
var readerRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'acdd72a7-3385-48ef-bd42-f606fba81ae7'
)

module controllerReaderAssignment './modules/cleanup-rbac.bicep' = {
  name: 'm78-controller-reader'
  scope: controllerResourceGroup
  params: {
    principalId: controller.outputs.cleanupPrincipalId
    roleDefinitionId: readerRoleDefinitionId
  }
}

output controllerResourceGroupName string = controllerResourceGroup.name
output automationAccountName string = controller.outputs.automationAccountName
output cleanupPrincipalId string = controller.outputs.cleanupPrincipalId
output runbookName string = controller.outputs.runbookName
output readerRoleAssignmentId string = controllerReaderAssignment.outputs.roleAssignmentId
output controllerLocation string = controllerLocation
output controllerAuthorizedUntilUtc string = controllerAuthorizedUntilUtc
output cleanupScriptSha256 string = cleanupScriptSha256
output retentionAbsenceEvidenceSha256 string = retentionAbsenceEvidenceSha256
