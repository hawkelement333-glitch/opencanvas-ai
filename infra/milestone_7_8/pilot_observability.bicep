// Only the isolated pilot validation destination. No historical campaign adoption.
targetScope = 'resourceGroup'

@allowed(['eastus', 'canadacentral'])
param location string = 'eastus'
@minLength(10)
@maxLength(10)
param suffix string
param lifecycleTags object
param workspaceName string
param monitorScopeName string
param virtualNetworkId string
param privateEndpointSubnetId string
param gatewayPrincipalId string
param evidencePrincipalId string
param operatorPrincipalId string
param operatorPrincipalType string = 'User'
@description('Only exact compiled catalog queries. Generate with pilot_validation prepare.')
param catalog object

var prefix = 'm78p-${suffix}'
var columns = [
  { name: 'TimeGenerated', type: 'datetime' }
  { name: 'SignalId', type: 'string' }
  { name: 'Kind', type: 'string' }
  { name: 'Name', type: 'string' }
  { name: 'Service', type: 'string' }
  { name: 'Environment', type: 'string' }
  { name: 'Release', type: 'string' }
  { name: 'Deployment', type: 'string' }
  { name: 'Component', type: 'string' }
  { name: 'Payload', type: 'dynamic' }
]
var classes = [
  { table: 'MobiusApplication_CL', kind: 'application_log', days: 30 }
  { table: 'MobiusSecurity_CL', kind: 'security_log', days: 90 }
  { table: 'MobiusMetric_CL', kind: 'metric', days: 30 }
  { table: 'MobiusSpan_CL', kind: 'span', days: 14 }
  { table: 'MobiusIncident_CL', kind: 'incident', days: 365 }
]
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}
resource monitorScope 'Microsoft.Insights/privateLinkScopes@2021-09-01' existing = {
  name: monitorScopeName
}
resource tables 'Microsoft.OperationalInsights/workspaces/tables@2025-07-01' = [for spec in classes: {
  parent: workspace
  name: spec.table
  properties: {
    plan: 'Analytics'
    retentionInDays: spec.days
    totalRetentionInDays: spec.days
    schema: { name: spec.table, columns: columns }
  }
}]
resource endpoint 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name: 'dce-${prefix}'
  location: location
  tags: lifecycleTags
  properties: { networkAcls: { publicNetworkAccess: 'Disabled' } }
}
resource scopedEndpoint 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-09-01' = {
  parent: monitorScope
  name: endpoint.name
  properties: { linkedResourceId: endpoint.id }
}
resource rule 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: 'dcr-${prefix}'
  location: location
  tags: lifecycleTags
  properties: {
    dataCollectionEndpointId: endpoint.id
    streamDeclarations: { 'Custom-MobiusOperational': { columns: columns } }
    destinations: { logAnalytics: [{ name: 'private-workspace', workspaceResourceId: workspace.id }] }
    dataFlows: [for spec in classes: {
      streams: ['Custom-MobiusOperational']
      destinations: ['private-workspace']
      transformKql: 'source | where Kind == "${spec.kind}"'
      outputStream: 'Custom-${spec.table}'
    }]
  }
  dependsOn: [tables]
}
resource exporterGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: rule
  name: guid(rule.id, gatewayPrincipalId, 'publisher')
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
  }
}
// Foundation already supplies the evidence identity's sole query grant.
// A second grant here would make exact-grant revocation ineffective.
resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principal in [
  { id: operatorPrincipalId, type: operatorPrincipalType }
]: {
  scope: workspace
  name: guid(workspace.id, principal.id, 'query')
  properties: {
    principalId: principal.id
    principalType: principal.type
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')
  }
}]

// Private alert delivery only; this is not the application's domain-event bus.
resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'eh-${prefix}'
  location: location
  tags: lifecycleTags
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    isAutoInflateEnabled: false
  }
}
resource eventHubNetwork 'Microsoft.EventHub/namespaces/networkRuleSets@2024-01-01' = {
  parent: eventHubNamespace
  name: 'default'
  properties: {
    publicNetworkAccess: 'Disabled'
    defaultAction: 'Deny'
    trustedServiceAccessEnabled: true
    ipRules: []
    virtualNetworkRules: []
  }
}
resource alertHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubNamespace
  name: 'alerts'
  properties: { partitionCount: 1, messageRetentionInDays: 1, status: 'Active' }
}
resource alertConsumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: alertHub
  name: 'managed-proof'
}
resource alertIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-alerts'
  location: location
  tags: lifecycleTags
}
resource sender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: alertHub
  name: guid(alertHub.id, alertIdentity.id, 'send')
  properties: {
    principalId: alertIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2b629674-e913-4c01-ae53-ef4638d8f975')
  }
}
resource receiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: alertHub
  name: guid(alertHub.id, evidencePrincipalId, 'receive')
  properties: {
    principalId: evidencePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde')
  }
}
resource hubDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.servicebus.windows.net'
  location: 'global'
  tags: toObject(filter(items(lifecycleTags), tag => tag.key != 'mobius.expiry'), tag => tag.key, tag => tag.value)
}
resource hubDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: hubDns
  name: prefix
  location: 'global'
  properties: { virtualNetwork: { id: virtualNetworkId }, registrationEnabled: false }
}
resource hubEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${prefix}-alerts'
  location: location
  tags: lifecycleTags
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [{
      name: 'alerts'
      properties: { privateLinkServiceId: eventHubNamespace.id, groupIds: ['namespace'] }
    }]
  }
}
resource hubEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: hubEndpoint
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: 'eventhub', properties: { privateDnsZoneId: hubDns.id } }] }
}
resource actions 'Microsoft.Insights/actionGroups@2024-10-01-preview' = {
  name: 'ag-${prefix}'
  location: 'global'
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${alertIdentity.id}': {} } }
  properties: {
    enabled: true
    groupShortName: 'M78pilot'
    eventHubReceivers: [{
      name: 'private-evidence'
      eventHubName: alertHub.name
      eventHubNameSpace: eventHubNamespace.name
      subscriptionId: subscription().subscriptionId
      tenantId: subscription().tenantId
      managedIdentity: alertIdentity.id
      useCommonAlertSchema: true
    }]
  }
  dependsOn: [sender, eventHubNetwork]
}
resource workbooks 'Microsoft.Insights/workbooks@2023-06-01' = [for dashboard in catalog.workbooks: {
  name: guid(resourceGroup().id, dashboard.id)
  location: location
  kind: 'shared'
  tags: lifecycleTags
  properties: {
    displayName: dashboard.title
    category: 'workbook'
    sourceId: workspace.id
    serializedData: string(dashboard.workbook)
  }
}]
resource alerts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for alert in catalog.alerts: {
  name: '${prefix}-${alert.id}'
  location: location
  tags: lifecycleTags
  properties: {
    displayName: alert.id
    description: alert.description
    enabled: alert.enabled
    severity: alert.severity
    scopes: [workspace.id]
    evaluationFrequency: alert.evaluationFrequency
    windowSize: 'P2D'
    autoMitigate: alert.autoMitigate
    checkWorkspaceAlertsStorageConfigured: false
    skipQueryValidation: false
    criteria: { allOf: [{
      query: alert.query
      timeAggregation: 'Count'
      operator: 'GreaterThan'
      threshold: 0
      failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
    }] }
    actions: { actionGroups: [actions.id], customProperties: { catalog: 'mobius-alerts-v1', alertId: alert.id } }
  }
  dependsOn: [tables]
}]

output dceEndpoint string = endpoint.properties.logsIngestion.endpoint
output dcrImmutableId string = rule.properties.immutableId
output dcrId string = rule.id
output alertNamespace string = '${eventHubNamespace.name}.servicebus.windows.net'
output actionGroupId string = actions.id
output alertIds array = [for (alert, index) in catalog.alerts: alerts[index].id]
output workbookIds array = [for (dashboard, index) in catalog.workbooks: workbooks[index].id]
output tableRetention array = classes
