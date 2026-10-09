targetScope = 'resourceGroup'

param environment string
param location string = resourceGroup().location
@description('Immutable ACR reference in the form registry.azurecr.io/ayursage@sha256:...')
param imageDigest string
@secure()
param databaseUrl string
@secure()
param jwtSecret string
param webOrigin string
param storageAccountName string
param registryName string
param cpu string = '0.5'
param memory string = '1Gi'
param minReplicas int = 1
param maxReplicas int = 3

var stem = 'ayursage-${environment}'
resource appEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = { name: '${stem}-apps' }
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = { name: '${stem}-app-id' }
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: registryName }
var runtimeEnv = [
  { name: 'AYURSAGE_ENV', value: 'production' }
  { name: 'ML_ENABLED', value: 'false' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'JWT_SECRET', secretRef: 'jwt-secret' }
  { name: 'COOKIE_SECURE', value: 'true' }
  { name: 'ALLOWED_ORIGINS', value: webOrigin }
  { name: 'REPORT_STORAGE_BACKEND', value: 'azure' }
  { name: 'AZURE_REPORT_ACCOUNT_URL', value: 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}' }
  { name: 'AZURE_REPORT_CONTAINER', value: 'reports' }
]

resource migration 'Microsoft.App/jobs@2024-03-01' = {
  name: '${stem}-migrate'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: appEnvironment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [{ name: 'database-url', value: databaseUrl }, { name: 'jwt-secret', value: jwtSecret }]
    }
    template: { containers: [{ name: 'migrate', image: imageDigest, args: ['migrate'], env: runtimeEnv, resources: { cpu: json(cpu), memory: memory } }] }
  }
}

@description('Set true only after the manual migration job has succeeded and schema revision is verified.')
param activateApp bool = false
resource app 'Microsoft.App/containerApps@2025-07-01' = if (activateApp) {
  name: '${stem}-api'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: appEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [{ name: 'database-url', value: databaseUrl }, { name: 'jwt-secret', value: jwtSecret }]
    }
    template: {
      containers: [{
        name: 'api'
        image: imageDigest
        env: runtimeEnv
        resources: { cpu: json(cpu), memory: memory }
        probes: [
          { type: 'Liveness', httpGet: { path: '/api/v1/health/live', port: 8000 }, initialDelaySeconds: 15, periodSeconds: 30 }
          { type: 'Readiness', httpGet: { path: '/api/v1/health/ready', port: 8000 }, initialDelaySeconds: 15, periodSeconds: 10 }
        ]
      }]
      scale: { minReplicas: minReplicas, maxReplicas: maxReplicas }
    }
  }
}

output migrationJobName string = migration.name
output appName string = activateApp ? app.name : ''
