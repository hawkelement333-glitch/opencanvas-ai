targetScope = 'resourceGroup'

param targetLocation string
param administratorIdentityName string
param migrationIdentityName string
param apiIdentityName string
param workerIdentityName string
param evidenceIdentityName string
param lifecycleTags object

resource bootstrap 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: administratorIdentityName
  location: targetLocation
  tags: lifecycleTags
}

resource migration 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: migrationIdentityName
  location: targetLocation
  tags: lifecycleTags
}

resource api 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: apiIdentityName
  location: targetLocation
  tags: lifecycleTags
}

resource worker 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: workerIdentityName
  location: targetLocation
  tags: lifecycleTags
}

resource evidence 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: evidenceIdentityName
  location: targetLocation
  tags: lifecycleTags
}

output bootstrap object = { id: bootstrap.id, principalId: bootstrap.properties.principalId, clientId: bootstrap.properties.clientId }
output migration object = { id: migration.id, principalId: migration.properties.principalId, clientId: migration.properties.clientId }
output api object = { id: api.id, principalId: api.properties.principalId, clientId: api.properties.clientId }
output worker object = { id: worker.id, principalId: worker.properties.principalId, clientId: worker.properties.clientId }
output evidence object = { id: evidence.id, principalId: evidence.properties.principalId, clientId: evidence.properties.clientId }
