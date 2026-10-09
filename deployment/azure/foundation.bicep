targetScope = 'resourceGroup'

@description('Short lowercase environment code, unique within the subscription.')
@minLength(2)
@maxLength(8)
param environment string
param location string = resourceGroup().location
@secure()
param mysqlAdminPassword string
param mysqlAdminLogin string
param mysqlSku string = 'Standard_B1ms'
param mysqlStorageGB int = 20
param mysqlBackupDays int = 7
param logRetentionDays int = 30

var stem = 'ayursage-${environment}'
var unique = take(uniqueString(resourceGroup().id, environment), 6)

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${stem}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.84.0.0/16'] }
    subnets: [
      { name: 'apps', properties: { addressPrefix: '10.84.0.0/23', delegations: [{ name: 'apps', properties: { serviceName: 'Microsoft.App/environments' } }] } }
      { name: 'mysql', properties: { addressPrefix: '10.84.2.0/24', delegations: [{ name: 'mysql', properties: { serviceName: 'Microsoft.DBforMySQL/flexibleServers' } }] } }
      { name: 'endpoints', properties: { addressPrefix: '10.84.3.0/24', privateEndpointNetworkPolicies: 'Disabled' } }
    ]
  }
}

resource mysqlDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: '${environment}.mysql.database.azure.com'
  location: 'global'
}
resource mysqlDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: mysqlDns
  name: 'app-vnet'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}

resource mysql 'Microsoft.DBforMySQL/flexibleServers@2024-12-30' = {
  name: '${stem}-${unique}-mysql'
  location: location
  sku: { name: mysqlSku, tier: 'Burstable' }
  properties: {
    administratorLogin: mysqlAdminLogin
    administratorLoginPassword: mysqlAdminPassword
    version: '8.0.21'
    backup: { backupRetentionDays: mysqlBackupDays, geoRedundantBackup: 'Disabled' }
    storage: { storageSizeGB: mysqlStorageGB, autoGrow: 'Enabled' }
    network: {
      delegatedSubnetResourceId: network.properties.subnets[1].id
      privateDnsZoneResourceId: mysqlDns.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [mysqlDnsLink]
}
resource tls 'Microsoft.DBforMySQL/flexibleServers/configurations@2024-12-30' = {
  parent: mysql
  name: 'require_secure_transport'
  properties: { value: 'ON', source: 'user-override' }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'ayursage${environment}${unique}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false, publicNetworkAccess: 'Enabled' }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'ayursage${environment}${unique}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'None' }
  }
}
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}
resource reports 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'reports'
  properties: { publicAccess: 'None' }
}
resource blobDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.blob.${az.environment().suffixes.storage}'
  location: 'global'
}
resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobDns
  name: 'app-vnet'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}
resource blobEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${stem}-blob-pe'
  location: location
  properties: {
    subnet: { id: network.properties.subnets[2].id }
    privateLinkServiceConnections: [{ name: 'blob', properties: { privateLinkServiceId: storage.id, groupIds: ['blob'] } }]
  }
}
resource blobZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobEndpoint
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: 'blob', properties: { privateDnsZoneId: blobDns.id } }] }
  dependsOn: [blobDnsLink]
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${stem}-logs'
  location: location
  properties: { retentionInDays: logRetentionDays, sku: { name: 'PerGB2018' } }
}
resource appEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${stem}-apps'
  location: location
  properties: {
    vnetConfiguration: { infrastructureSubnetId: network.properties.subnets[0].id, internal: false }
    appLogsConfiguration: { destination: 'log-analytics', logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey } }
  }
}
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${stem}-app-id'
  location: location
}
resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(reports.id, appIdentity.id, 'blob-contributor')
  scope: reports
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}
resource pullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, appIdentity.id, 'acr-pull')
  scope: registry
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}
resource site 'Microsoft.Web/staticSites@2023-12-01' = {
  name: '${stem}-web'
  location: location
  sku: { name: 'Standard', tier: 'Standard' }
  properties: { buildProperties: { appLocation: 'frontend', outputLocation: 'dist' } }
}

output registryLoginServer string = registry.properties.loginServer
output appEnvironmentId string = appEnvironment.id
output appIdentityId string = appIdentity.id
output mysqlFqdn string = mysql.properties.fullyQualifiedDomainName
output storageAccountUrl string = 'https://${storage.name}.blob.${az.environment().suffixes.storage}'
output staticSiteId string = site.id
