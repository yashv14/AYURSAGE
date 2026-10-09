targetScope = 'resourceGroup'

param environment string
param location string = resourceGroup().location
resource site 'Microsoft.Web/staticSites@2023-12-01' existing = { name: 'ayursage-${environment}-web' }
resource production 'Microsoft.Web/staticSites/builds@2023-12-01' existing = { parent: site, name: 'default' }
resource api 'Microsoft.App/containerApps@2025-07-01' existing = { name: 'ayursage-${environment}-api' }
resource link 'Microsoft.Web/staticSites/builds/linkedBackends@2025-03-01' = {
  parent: production
  name: 'api'
  properties: { backendResourceId: api.id, region: location }
}
