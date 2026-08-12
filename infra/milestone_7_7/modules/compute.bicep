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
  true
])
param imageDigestContractResolved bool = true

param applicationDeploymentEnabled bool = false

@description('Narrow private signup bootstrap; it cannot enable the full application graph.')
param ownerBootstrapDeploymentEnabled bool = false

@allowed([
  'southcentralus'
])
param location string = 'southcentralus'

param containerAppsSubnetId string = ''
@allowed([
  'rg-solarplexus-mobius-77-containerapps-infrastructure'
])
param infrastructureResourceGroupName string = 'rg-solarplexus-mobius-77-containerapps-infrastructure'
param apiIdentityId string = ''
param apiIdentityClientId string = ''
param apiIdentityPrincipalId string = ''
param apiIdentityName string = ''
param workerIdentityId string = ''
param workerIdentityClientId string = ''
param workerIdentityPrincipalId string = ''
param workerIdentityName string = ''
param telemetryIdentityId string = ''
param databaseAdministratorIdentityId string = ''
param databaseAdministratorClientId string = ''
param databaseAdministratorName string = ''
param keyVaultName string = ''
param registryLoginServer string = ''
param apiImageDigest string = ''
param postgresHost string = ''
param postgresPort int = 5432
param postgresDatabase string = ''
param redisHost string = ''
param redisPort int = 10000
param redisApiUsername string = ''
param redisWorkerUsername string = ''
param storageAccountUrl string = ''
param logAnalyticsWorkspaceCustomerId string = ''
param logAnalyticsWorkspaceId string = ''
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
var ownerBootstrapEnabled = enabled && ownerBootstrapDeploymentEnabled && !applicationDeploymentEnabled
var databaseRuntimeEnabled = appEnabled || ownerBootstrapEnabled
var apiEnabled = appEnabled || ownerBootstrapEnabled
var environmentName = 'cae-mobius77-staging'
var apiName = 'ca-mobius77-api'
var workerName = 'ca-mobius77-worker'
var telemetryName = 'ca-mobius77-telemetry'
var migrationJobName = 'caj-mobius77-migration'
var ownerReadbackJobName = 'caj-mobius77-owner-readback'
var effectiveManagedEnvironmentId = ownerBootstrapEnabled ? existingOwnerBootstrapEnvironment!.id : managedEnvironment!.id
var effectiveManagedEnvironmentDefaultDomain = ownerBootstrapEnabled ? existingOwnerBootstrapEnvironment!.properties.defaultDomain : managedEnvironment!.properties.defaultDomain
var effectiveManagedEnvironmentStaticIp = ownerBootstrapEnabled ? existingOwnerBootstrapEnvironment!.properties.staticIp : managedEnvironment!.properties.staticIp
var internalApplicationUrl = 'https://${apiName}.${effectiveManagedEnvironmentDefaultDomain}'
var telemetryEndpoint = 'https://${telemetryName}.${effectiveManagedEnvironmentDefaultDomain}/v1/signals'
var keyVaultBaseUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/'
var applicationSecretNames = [
  'openai-api-key'
  'opencanvas-smtp-username'
  'opencanvas-smtp-password'
  'opencanvas-session-secret'
  'opencanvas-invitation-secret'
  'opencanvas-upload-capability-secret'
  'opencanvas-scanner-result-secret'
  'opencanvas-rate-limit-hmac-secret'
  'opencanvas-telemetry-token'
  'opencanvas-telemetry-pseudonymization-secret'
  'opencanvas-observability-operator-user-ids'
]
var commonSettings = [
  { name: 'OPENCANVAS_APP_MODE', value: 'staging' }
  { name: 'OPENCANVAS_APP_URL', value: internalApplicationUrl }
  { name: 'OPENCANVAS_CORS_ORIGINS', value: '["${internalApplicationUrl}"]' }
  { name: 'OPENCANVAS_AUTH_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_AUTH_TEST_BYPASS', value: 'false' }
  { name: 'OPENCANVAS_PASSWORD_RESET_PROVIDER', value: 'smtp' }
  { name: 'OPENCANVAS_SMTP_HOST', value: smtpHost }
  { name: 'OPENCANVAS_SMTP_PORT', value: '2525' }
  { name: 'OPENCANVAS_SMTP_FROM_ADDRESS', value: smtpFromAddress }
  { name: 'OPENCANVAS_SMTP_STARTTLS', value: 'true' }
  { name: 'OPENCANVAS_AI_PROVIDER', value: 'openai' }
  { name: 'OPENCANVAS_EMBEDDING_PROVIDER', value: 'openai' }
  { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
  { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
  { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20260726_0028' }
  { name: 'OPENCANVAS_STORAGE_PROVIDER', value: 'azure' }
  { name: 'OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL', value: storageAccountUrl }
  { name: 'OPENCANVAS_OBJECT_INGESTION_MODE', value: 'trusted' }
  { name: 'OPENCANVAS_MALWARE_SCANNER_IDENTITY', value: 'azure-defender-for-storage' }
  { name: 'OPENCANVAS_MALWARE_SCANNER_VERSION', value: 'defender-storage-dual-source-v1' }
  { name: 'OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS', value: '3600' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_MODE', value: 'private_pull' }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID', value: logAnalyticsWorkspaceCustomerId }
  { name: 'OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT', value: 'https://api.loganalytics.azure.com' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_BASE_SECONDS', value: '5' }
  { name: 'OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS', value: '300' }
  { name: 'OPENCANVAS_JOB_PROVIDER', value: 'database' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER', value: 'redis' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_URL', value: 'rediss://${redisHost}:${redisPort}/0' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_NAMESPACE', value: 'mobius' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_DEPLOYMENT', value: 'milestone-7-7' }
  { name: 'OPENCANVAS_INDEXER_PUBLICATION_MODE', value: 'private_clean' }
  { name: 'OPENCANVAS_TELEMETRY_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_TELEMETRY_EXPORTER', value: 'http' }
  { name: 'OPENCANVAS_TELEMETRY_ENDPOINT', value: telemetryEndpoint }
  { name: 'OPENCANVAS_TELEMETRY_AUTH_SECRET_REFERENCE', value: 'env://OPENCANVAS_TELEMETRY_AUTH_TOKEN' }
  { name: 'OPENCANVAS_TELEMETRY_TLS_VERIFY', value: 'true' }
  { name: 'OPENCANVAS_TELEMETRY_RELEASE', value: 'milestone-7-7' }
  { name: 'OPENCANVAS_TELEMETRY_DEPLOYMENT', value: 'milestone-7-7' }
]
var applicationSecretEnvironment = [
  { name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }
  { name: 'OPENCANVAS_SMTP_USERNAME', secretRef: 'opencanvas-smtp-username' }
  { name: 'OPENCANVAS_SMTP_PASSWORD', secretRef: 'opencanvas-smtp-password' }
  { name: 'OPENCANVAS_SESSION_SECRET', secretRef: 'opencanvas-session-secret' }
  { name: 'OPENCANVAS_INVITATION_SECRET', secretRef: 'opencanvas-invitation-secret' }
  { name: 'OPENCANVAS_UPLOAD_CAPABILITY_SECRET', secretRef: 'opencanvas-upload-capability-secret' }
  { name: 'OPENCANVAS_SCANNER_RESULT_SECRET', secretRef: 'opencanvas-scanner-result-secret' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET', secretRef: 'opencanvas-rate-limit-hmac-secret' }
  { name: 'OPENCANVAS_TELEMETRY_AUTH_TOKEN', secretRef: 'opencanvas-telemetry-token' }
  { name: 'OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET', secretRef: 'opencanvas-telemetry-pseudonymization-secret' }
  { name: 'OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS', secretRef: 'opencanvas-observability-operator-user-ids' }
]
var ownerBootstrapSecretNames = [
  'opencanvas-session-secret'
]
var ownerBootstrapSettings = [
  { name: 'OPENCANVAS_APP_MODE', value: 'development' }
  { name: 'OPENCANVAS_APP_URL', value: internalApplicationUrl }
  { name: 'OPENCANVAS_CORS_ORIGINS', value: '["${internalApplicationUrl}"]' }
  { name: 'OPENCANVAS_AUTH_ENABLED', value: 'true' }
  { name: 'OPENCANVAS_AUTH_TEST_BYPASS', value: 'false' }
  { name: 'OPENCANVAS_PASSWORD_RESET_PROVIDER', value: 'development_token' }
  { name: 'OPENCANVAS_AI_PROVIDER', value: 'mock' }
  { name: 'OPENCANVAS_EMBEDDING_PROVIDER', value: 'mock' }
  { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
  { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
  { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
  { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20260726_0028' }
  { name: 'OPENCANVAS_STORAGE_PROVIDER', value: 'memory' }
  { name: 'OPENCANVAS_OBJECT_INGESTION_MODE', value: 'disabled' }
  { name: 'OPENCANVAS_JOB_PROVIDER', value: 'inline' }
  { name: 'OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER', value: 'memory' }
  { name: 'OPENCANVAS_INDEXER_PUBLICATION_MODE', value: 'disabled' }
  { name: 'OPENCANVAS_TELEMETRY_ENABLED', value: 'false' }
  { name: 'OPENCANVAS_TELEMETRY_EXPORTER', value: 'disabled' }
]
var ownerBootstrapSecretEnvironment = [
  { name: 'OPENCANVAS_SESSION_SECRET', secretRef: 'opencanvas-session-secret' }
]
var databaseApiSettings = [
  {
    name: 'OPENCANVAS_DATABASE_URL'
    value: 'postgresql+asyncpg://${apiIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
  }
  { name: 'OPENCANVAS_DATABASE_ROLE', value: 'api' }
  { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
  { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
]
var migrationBootstrapProgram = '''
import asyncio
import os
import re
import sys

import asyncpg
from sqlalchemy.engine import make_url

from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION, get_settings
from opencanvas_api.db.session import _POSTGRES_ENTRA_AUDIENCE
from opencanvas_api.services.managed_identity import ManagedIdentityTokenProvider
from scripts.migrate import run as run_migration


class PhaseFailure(Exception):
    pass


_SAFE_RUNTIME_PRINCIPAL = re.compile(r"^id-mobius77-(?:api|worker)$")
_SAFE_ADMIN_PRINCIPAL = re.compile(r"^id-mobius77-db-admin$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def fail(code):
    print(code, file=sys.stderr, flush=True)
    raise SystemExit(1)


async def read_revision(phase):
    try:
        settings = get_settings()
    except Exception:
        raise PhaseFailure(f"observability-bootstrap-{phase}-settings-validation-failed")
    provider = ManagedIdentityTokenProvider(
        endpoint=settings.database_managed_identity_endpoint or "",
        resource=_POSTGRES_ENTRA_AUDIENCE,
        client_id=settings.database_managed_identity_client_id or "",
        identity_header=settings.database_managed_identity_header,
        timeout_seconds=settings.database_connect_timeout_seconds,
    )
    try:
        token = await provider.token()
    except Exception:
        raise PhaseFailure(f"observability-bootstrap-{phase}-managed-identity-token-failed")
    url = make_url(settings.database_url_value)
    try:
        connection = await asyncpg.connect(
            user=url.username,
            password=token,
            database=url.database,
            host=url.host,
            port=url.port or 5432,
            ssl=settings.database_tls_mode,
            timeout=settings.database_connect_timeout_seconds,
        )
    except Exception:
        raise PhaseFailure(f"observability-bootstrap-{phase}-database-connect-failed")
    try:
        try:
            version_table = await connection.fetchval(
                "SELECT to_regclass('public.alembic_version')::text"
            )
        except Exception:
            raise PhaseFailure(f"observability-bootstrap-{phase}-version-table-read-failed")
        if version_table is None:
            return "base"
        try:
            revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        except Exception:
            raise PhaseFailure(f"observability-bootstrap-{phase}-revision-value-read-failed")
        if not isinstance(revision, str):
            raise PhaseFailure(f"observability-bootstrap-{phase}-revision-value-invalid")
        return revision
    finally:
        try:
            await connection.close()
        except Exception:
            pass


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def raise_principal_provider_failure(default_code, error):
    message = str(error).casefold()
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate == "42883" or "no function matches" in message:
        raise PhaseFailure("observability-bootstrap-runtime-principal-provider-function-absent")
    if sqlstate == "42703":
        raise PhaseFailure("observability-bootstrap-runtime-principal-provider-column-invalid")
    if sqlstate == "42501" or "permission denied" in message:
        raise PhaseFailure("observability-bootstrap-runtime-principal-provider-permission-denied")
    if "not found in the tenant" in message:
        raise PhaseFailure("observability-bootstrap-runtime-principal-provider-identity-not-found")
    if sqlstate == "42710" or "already exists" in message:
        raise PhaseFailure("observability-bootstrap-runtime-principal-provider-duplicate")
    raise PhaseFailure(default_code)


async def runtime_principal_rows(connection, principal):
    rows = await connection.fetch(
        "SELECT * FROM pg_catalog.pgaadauth_list_principals(false)"
    )
    result = []
    for row in rows:
        if len(row) != 6:
            raise PhaseFailure("observability-bootstrap-runtime-principal-mapping-invalid")
        if str(row[0]) == principal:
            result.append(
                {
                    "role_name": str(row[0]),
                    "principal_type": str(row[1]),
                    "object_id": str(row[2]),
                    "is_admin": int(row[5]),
                }
            )
    return result


async def grant_runtime_roles():
    principals = (
        (
            os.getenv("OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL", ""),
            os.getenv("OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL_ID", ""),
        ),
        (
            os.getenv("OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL", ""),
            os.getenv("OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL_ID", ""),
        ),
    )
    if any(
        _SAFE_RUNTIME_PRINCIPAL.fullmatch(principal) is None
        or _UUID.fullmatch(object_id) is None
        for principal, object_id in principals
    ):
        raise PhaseFailure("observability-bootstrap-runtime-principal-contract-invalid")
    settings = get_settings()
    provider = ManagedIdentityTokenProvider(
        endpoint=settings.database_managed_identity_endpoint or "",
        resource=_POSTGRES_ENTRA_AUDIENCE,
        client_id=settings.database_managed_identity_client_id or "",
        identity_header=settings.database_managed_identity_header,
        timeout_seconds=settings.database_connect_timeout_seconds,
    )
    try:
        token = await provider.token()
    except Exception:
        raise PhaseFailure("observability-bootstrap-runtime-managed-identity-token-failed")
    url = make_url(settings.database_url_value)
    if _SAFE_ADMIN_PRINCIPAL.fullmatch(url.username or "") is None:
        raise PhaseFailure("observability-bootstrap-runtime-principal-contract-invalid")
    connection_arguments = {
        "user": url.username,
        "password": token,
        "host": url.host,
        "port": url.port or 5432,
        "ssl": settings.database_tls_mode,
        "timeout": settings.database_connect_timeout_seconds,
    }
    try:
        principal_connection = await asyncpg.connect(
            database="postgres", **connection_arguments
        )
    except Exception:
        raise PhaseFailure("observability-bootstrap-runtime-principal-catalog-connect-failed")
    try:
        for principal, object_id in principals:
            try:
                rows = await runtime_principal_rows(principal_connection, principal)
            except PhaseFailure:
                raise
            except Exception as exc:
                raise_principal_provider_failure(
                    "observability-bootstrap-runtime-principal-list-failed", exc
                )
            if rows == []:
                try:
                    await principal_connection.fetchval(
                        "SELECT * FROM pg_catalog.pgaadauth_create_principal_with_oid("
                        "$1::text, $2::text, 'service'::text, false, false)",
                        principal,
                        object_id,
                    )
                except PhaseFailure:
                    raise
                except Exception as exc:
                    raise_principal_provider_failure(
                        "observability-bootstrap-runtime-principal-create-failed", exc
                    )
                try:
                    rows = await runtime_principal_rows(principal_connection, principal)
                except PhaseFailure:
                    raise
                except Exception as exc:
                    raise_principal_provider_failure(
                        "observability-bootstrap-runtime-principal-readback-failed", exc
                    )
            if (
                len(rows) != 1
                or rows[0]["role_name"] != principal
                or rows[0]["principal_type"] != "service"
                or str(rows[0]["object_id"]).lower() != object_id.lower()
                or rows[0]["is_admin"] != 0
            ):
                raise PhaseFailure("observability-bootstrap-runtime-principal-mapping-invalid")
            privileges = await principal_connection.fetchrow(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = $1",
                principal,
            )
            if privileges is None or any(bool(value) for value in privileges):
                raise PhaseFailure("observability-bootstrap-runtime-principal-privilege-invalid")
    finally:
        await principal_connection.close()
    try:
        application_connection = await asyncpg.connect(
            database=url.database, **connection_arguments
        )
    except Exception:
        raise PhaseFailure("observability-bootstrap-runtime-grant-database-connect-failed")
    try:
        try:
            async with application_connection.transaction():
                current_user = await application_connection.fetchval("SELECT current_user")
                if current_user != url.username:
                    raise PhaseFailure("observability-bootstrap-runtime-principal-contract-invalid")
                quoted_admin = quote_identifier(current_user)
                await application_connection.execute(
                    "REVOKE CREATE ON SCHEMA public FROM PUBLIC"
                )
                for principal, _object_id in principals:
                    quoted = quote_identifier(principal)
                    await application_connection.execute(
                        f"REVOKE ALL ON DATABASE opencanvas FROM {quoted}"
                    )
                    await application_connection.execute(
                        f"GRANT CONNECT ON DATABASE opencanvas TO {quoted}"
                    )
                    await application_connection.execute(
                        f"GRANT USAGE ON SCHEMA public TO {quoted}"
                    )
                    await application_connection.execute(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                        f"IN SCHEMA public TO {quoted}"
                    )
                    await application_connection.execute(
                        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES "
                        f"IN SCHEMA public TO {quoted}"
                    )
                    await application_connection.execute(
                        f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {quoted}"
                    )
                    await application_connection.execute(
                        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted}"
                    )
                    await application_connection.execute(
                        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
                        f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {quoted}"
                    )
                    await application_connection.execute(
                        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
                        f"GRANT EXECUTE ON FUNCTIONS TO {quoted}"
                    )
        except PhaseFailure:
            raise
        except Exception:
            raise PhaseFailure("observability-bootstrap-runtime-role-grant-failed")
    finally:
        await application_connection.close()


try:
    revision = asyncio.run(read_revision("initial"))
except PhaseFailure as exc:
    fail(str(exc))

if revision == "base":
    try:
        result = run_migration(expected_current="base", target=EXPECTED_DATABASE_REVISION)
    except Exception:
        fail("observability-bootstrap-migration-apply-failed")
    if result != 0:
        fail("observability-bootstrap-migration-apply-failed")
elif revision != EXPECTED_DATABASE_REVISION:
    fail("observability-bootstrap-revision-drift")

try:
    asyncio.run(grant_runtime_roles())
except PhaseFailure as exc:
    fail(str(exc))
except Exception:
    fail("observability-bootstrap-runtime-role-grant-failed")

try:
    final_revision = asyncio.run(read_revision("final"))
except PhaseFailure as exc:
    fail(str(exc))
if final_revision != EXPECTED_DATABASE_REVISION:
    fail("observability-bootstrap-final-revision-mismatch")

print("observability-bootstrap-migration-succeeded", flush=True)
'''
var ownerReadbackProgram = '''
import asyncio
import json

from sqlalchemy import text

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.session import Database


async def run():
    settings = get_settings()
    database = Database.from_settings(settings, expected_role=DatabaseRole.API)
    try:
        async with database.engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT DISTINCT u.id::text
                FROM users AS u
                JOIN user_sessions AS s ON s.user_id = u.id
                WHERE u.is_active = TRUE
                  AND u.deleted_at IS NULL
                  AND u.password_hash <> 'login-disabled'
                  AND COALESCE((u.settings_payload ->> 'migrationPrincipal')::boolean, FALSE) = FALSE
                  AND s.revoked_at IS NULL
                ORDER BY u.id::text
            """))
            rows = [row[0] for row in result.all()]
    finally:
        await database.dispose()
    if len(rows) != 1:
        raise RuntimeError("observability-owner-readback-cardinality-invalid")
    print(json.dumps({
        "marker": "GENUINE_OWNER_APPLICATION_UUID_PROVED",
        "userId": rows[0],
    }, separators=(",", ":"), sort_keys=True))


asyncio.run(run())
'''
var serviceShapeContract = {
  web: { cpuMilli: 250, memoryMiB: 512, minReplicas: 1, normalReplicas: 1, maxReplicas: 2 }
  api: { cpuMilli: 500, memoryMiB: 1024, minReplicas: 2, normalReplicas: 2, maxReplicas: 4 }
  sharedWorkerPool: {
    cpuMilli: 500
    memoryMiB: 1024
    minReplicas: 2
    normalReplicas: 2
    maxReplicas: 4
    workKinds: ['indexer', 'scan', 'workflow', 'agent']
  }
  telemetryGateway: { cpuMilli: 250, memoryMiB: 512, minReplicas: 1, normalReplicas: 1, maxReplicas: 1 }
}
var jobShapeContract = {
  migration: { cpuMilli: 500, memoryMiB: 1024, idleExecutions: 0, maxParallelExecutions: 1 }
  loadGenerator: { cpuMilli: 1000, memoryMiB: 2048, idleExecutions: 0, maxParallelExecutions: 1 }
  faultController: {
    cpuMilli: null
    memoryMiB: null
    idleExecutions: 0
    maxParallelExecutions: 1
    shapeResolutionStatus: 'deferred-to-failure-runner-checkpoint'
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' = if (enabled && !ownerBootstrapEnabled) {
  name: environmentName
  location: location
  tags: lifecycleTags
  properties: {
    appLogsConfiguration: { destination: 'azure-monitor' }
    publicNetworkAccess: 'Disabled'
    infrastructureResourceGroup: infrastructureResourceGroupName
    vnetConfiguration: { infrastructureSubnetId: containerAppsSubnetId, internal: true }
    zoneRedundant: false
  }
}

resource existingOwnerBootstrapEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' existing = if (ownerBootstrapEnabled) {
  name: environmentName
}

resource proofConsoleDiagnostic 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enabled && !ownerBootstrapEnabled) {
  scope: managedEnvironment
  name: 'mobius77-scanner-proof-console'
  properties: {
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
    ]
    metrics: []
    workspaceId: logAnalyticsWorkspaceId
  }
}

resource telemetryContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (appEnabled) {
  name: telemetryName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${telemetryIdentityId}': {} } }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { allowInsecure: false, external: false, targetPort: 4318, transport: 'http' }
      registries: [{ identity: telemetryIdentityId, server: registryLoginServer }]
      secrets: [
        {
          identity: telemetryIdentityId
          keyVaultUrl: '${keyVaultBaseUrl}opencanvas-telemetry-token'
          name: 'opencanvas-telemetry-token'
        }
      ]
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          args: ['-m', 'scripts.telemetry_gateway']
          command: ['python']
          env: [{ name: 'OPENCANVAS_TELEMETRY_GATEWAY_TOKEN', secretRef: 'opencanvas-telemetry-token' }]
          image: apiImageDigest
          name: 'telemetry-gateway'
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 4318, scheme: 'HTTP' }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 4318, scheme: 'HTTP' }
              initialDelaySeconds: 2
              periodSeconds: 5
            }
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { maxReplicas: 1, minReplicas: 1 }
    }
    workloadProfileName: 'Consumption'
  }
}

resource migrationJob 'Microsoft.App/jobs@2025-01-01' = if (databaseRuntimeEnabled) {
  name: migrationJobName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${databaseAdministratorIdentityId}': {} } }
  properties: {
    configuration: {
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ identity: databaseAdministratorIdentityId, server: registryLoginServer }]
      replicaRetryLimit: 0
      replicaTimeout: 1800
      triggerType: 'Manual'
    }
    environmentId: effectiveManagedEnvironmentId
    template: {
      containers: [
        {
          args: ['-c', migrationBootstrapProgram]
          command: ['python']
          env: concat(ownerBootstrapSettings, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${databaseAdministratorName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'migration' }
            { name: 'OPENCANVAS_DATABASE_AUTH_MODE', value: 'entra' }
            { name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: databaseAdministratorClientId }
            { name: 'OPENCANVAS_DATABASE_EXPECTED_REVISION', value: '20260726_0028' }
            { name: 'OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL', value: apiIdentityName }
            { name: 'OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL_ID', value: apiIdentityPrincipalId }
            { name: 'OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL', value: workerIdentityName }
            { name: 'OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL_ID', value: workerIdentityPrincipalId }
          ])
          image: apiImageDigest
          name: 'migration'
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: appEnabled ? [telemetryContainerApp] : []
}

resource ownerReadbackJob 'Microsoft.App/jobs@2025-01-01' = if (ownerBootstrapEnabled) {
  name: ownerReadbackJobName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentityId}': {} } }
  properties: {
    configuration: {
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ identity: apiIdentityId, server: registryLoginServer }]
      replicaRetryLimit: 0
      replicaTimeout: 300
      triggerType: 'Manual'
    }
    environmentId: effectiveManagedEnvironmentId
    template: {
      containers: [
        {
          args: ['-c', ownerReadbackProgram]
          command: ['python']
          env: concat(ownerBootstrapSettings, databaseApiSettings)
          image: apiImageDigest
          name: 'owner-readback'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [migrationJob]
}

resource apiContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (apiEnabled) {
  name: apiName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentityId}': {} } }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { allowInsecure: false, external: false, targetPort: 8000, transport: 'auto' }
      registries: [{ identity: apiIdentityId, server: registryLoginServer }]
      secrets: [
        for secretName in (appEnabled ? applicationSecretNames : ownerBootstrapSecretNames): {
          identity: apiIdentityId
          keyVaultUrl: '${keyVaultBaseUrl}${secretName}'
          name: secretName
        }
      ]
    }
    environmentId: effectiveManagedEnvironmentId
    template: {
      containers: [
        {
          env: appEnabled ? concat(commonSettings, applicationSecretEnvironment, databaseApiSettings, [
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisApiUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
          ]) : concat(ownerBootstrapSettings, ownerBootstrapSecretEnvironment, databaseApiSettings)
          image: apiImageDigest
          name: 'api'
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/api/v1/health/live', port: 8000, scheme: 'HTTP' }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/v1/health/ready', port: 8000, scheme: 'HTTP' }
              initialDelaySeconds: 5
              periodSeconds: 5
            }
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      initContainers: [
        {
          args: ['-m', 'scripts.runtime_dependency_gate', '--attempts', '120', '--delay-seconds', '5']
          command: ['python']
          env: appEnabled ? concat(commonSettings, applicationSecretEnvironment, databaseApiSettings, [
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisApiUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: apiIdentityClientId }
          ]) : concat(ownerBootstrapSettings, ownerBootstrapSecretEnvironment, databaseApiSettings)
          image: apiImageDigest
          name: 'database-gate'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: appEnabled ? { maxReplicas: 4, minReplicas: 2 } : { maxReplicas: 1, minReplicas: 1 }
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [migrationJob]
}

resource workerContainerApp 'Microsoft.App/containerApps@2026-01-01' = if (appEnabled) {
  name: workerName
  location: location
  tags: lifecycleTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${workerIdentityId}': {} } }
  properties: {
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ identity: workerIdentityId, server: registryLoginServer }]
      secrets: [
        for secretName in applicationSecretNames: {
          identity: workerIdentityId
          keyVaultUrl: '${keyVaultBaseUrl}${secretName}'
          name: secretName
        }
      ]
    }
    environmentId: managedEnvironment.id
    template: {
      containers: [
        {
          args: ['-m', 'scripts.worker']
          command: ['python']
          env: concat(commonSettings, applicationSecretEnvironment, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${workerIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'worker' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisWorkerUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
          ])
          image: apiImageDigest
          name: 'worker'
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      initContainers: [
        {
          args: ['-m', 'scripts.runtime_dependency_gate', '--attempts', '120', '--delay-seconds', '5']
          command: ['python']
          env: concat(commonSettings, applicationSecretEnvironment, [
            {
              name: 'OPENCANVAS_DATABASE_URL'
              value: 'postgresql+asyncpg://${workerIdentityName}@${postgresHost}:${postgresPort}/${postgresDatabase}'
            }
            { name: 'OPENCANVAS_DATABASE_ROLE', value: 'worker' }
            { name: 'OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME', value: redisWorkerUsername }
            { name: 'OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID', value: workerIdentityClientId }
          ])
          image: apiImageDigest
          name: 'database-gate'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { maxReplicas: 4, minReplicas: 2 }
    }
    workloadProfileName: 'Consumption'
  }
  dependsOn: [migrationJob]
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
output ownerBootstrapDeploymentEnabled bool = ownerBootstrapEnabled
output managedEnvironmentId string = enabled ? effectiveManagedEnvironmentId : ''
output proofConsoleDiagnosticId string = enabled && !ownerBootstrapEnabled ? proofConsoleDiagnostic.id : ''
output infrastructureResourceGroupName string = infrastructureResourceGroupName
output apiContainerAppId string = apiEnabled ? apiContainerApp.id : ''
output workerContainerAppId string = appEnabled ? workerContainerApp.id : ''
output telemetryContainerAppId string = appEnabled ? telemetryContainerApp.id : ''
output migrationJobName string = databaseRuntimeEnabled ? migrationJob.name : ''
output ownerReadbackJobName string = ownerBootstrapEnabled ? ownerReadbackJob.name : ''
output managedEnvironmentDefaultDomain string = enabled ? effectiveManagedEnvironmentDefaultDomain : ''
output managedEnvironmentStaticIp string = enabled ? effectiveManagedEnvironmentStaticIp : ''
output publicApplicationIngress bool = false
output configuredOpenAiAlias string = 'OPENAI_API_KEY'
output alternativeOpenAiAliasConfigured bool = false
