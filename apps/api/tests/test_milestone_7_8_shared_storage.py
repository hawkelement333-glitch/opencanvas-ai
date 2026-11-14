from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from opencanvas_api.services.documents.storage import LocalDocumentStorage

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def compiled_storage(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    compiler = shutil.which("bicep") or str(Path.home() / ".azure/bin/bicep.exe")
    if not Path(compiler).is_file():
        pytest.skip("installed Bicep is required for the compiled storage contract")
    output = tmp_path_factory.mktemp("m78-shared-storage") / "campaign.json"
    result = subprocess.run(
        [compiler, "build", str(ROOT / "infra/milestone_7_8/modules/campaign-resources.bicep"),
         "--no-restore", "--outfile", str(output)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _resource(compiled: dict[str, Any], kind: str, name_fragment: str = "") -> dict[str, Any]:
    matches = [
        value for value in compiled["resources"]
        if value["type"] == kind and name_fragment in value["name"]
    ]
    assert len(matches) == 1
    result: dict[str, Any] = matches[0]
    return result


def test_shared_document_store_is_bounded_private_smb(compiled_storage: dict[str, Any]) -> None:
    account = _resource(compiled_storage, "Microsoft.Storage/storageAccounts")
    assert "stm78" in account["name"] and "resourceNameSuffix" in account["name"]
    assert account["kind"] == "StorageV2"
    assert account["sku"] == {"name": "Standard_LRS"}
    properties = account["properties"]
    assert properties["publicNetworkAccess"] == "Disabled"
    assert properties["allowBlobPublicAccess"] is False
    assert properties["allowSharedKeyAccess"] is True
    assert properties["supportsHttpsTrafficOnly"] is True
    assert properties["minimumTlsVersion"] == "TLS1_2"
    assert properties["networkAcls"]["defaultAction"] == "Deny"
    assert properties["networkAcls"]["bypass"] == "None"
    assert properties["networkAcls"]["ipRules"] == []
    assert properties["networkAcls"]["virtualNetworkRules"] == []
    assert properties["encryption"]["services"]["file"]["enabled"] is True
    share = _resource(compiled_storage, "Microsoft.Storage/storageAccounts/fileServices/shares")
    assert share["properties"] == {
        "accessTier": "TransactionOptimized", "enabledProtocols": "SMB", "shareQuota": 1,
    }
    service = _resource(compiled_storage, "Microsoft.Storage/storageAccounts/fileServices")
    assert service["properties"]["protocolSettings"]["smb"]["versions"] == "SMB3.1.1"
    assert service["properties"]["protocolSettings"]["smb"]["authenticationMethods"] == "NTLMv2"
    assert service["properties"]["protocolSettings"]["smb"]["channelEncryption"] == (
        "AES-128-GCM;AES-256-GCM"
    )
    assert service["properties"]["shareDeleteRetentionPolicy"] == {"enabled": False}
    endpoint = _resource(compiled_storage, "Microsoft.Network/privateEndpoints", "documents")
    connection = endpoint["properties"]["privateLinkServiceConnections"]
    assert len(connection) == 1 and connection[0]["properties"]["groupIds"] == ["file"]
    assert endpoint["properties"]["subnet"]["id"] == "[variables('privateEndpointSubnetId')]"
    assert "private-endpoints" in compiled_storage["variables"]["privateEndpointSubnetId"]
    zone = _resource(compiled_storage, "Microsoft.Network/privateDnsZones", "privatelink.file")
    assert zone["name"] == "[format('privatelink.file.{0}', environment().suffixes.storage)]"
    assert zone["tags"] == "[variables('privateDnsTags')]"
    assert "condition" not in account and "condition" not in share


def test_api_and_worker_share_only_the_private_document_mount(
    compiled_storage: dict[str, Any],
) -> None:
    storage = _resource(compiled_storage, "Microsoft.App/managedEnvironments/storages")
    azure_file = storage["properties"]["azureFile"]
    assert azure_file["accessMode"] == "ReadWrite"
    assert "listKeys(" in azure_file["accountKey"]
    assert "Microsoft.Storage/storageAccounts" in azure_file["accountKey"]
    assert "m78-documents" in azure_file["shareName"]
    api = _resource(compiled_storage, "Microsoft.App/containerApps")
    worker = _resource(compiled_storage, "Microsoft.App/jobs", "job-m78-{0}-worker")
    for resource in (api, worker):
        assert resource["condition"] == "[variables('workloadEnabled')]"
        template = resource["properties"]["template"]
        assert template["containers"][0]["volumeMounts"] == [
            {"mountPath": "/app/data/documents", "volumeName": "documents"},
        ]
        assert template["volumes"] == [{
            "name": "documents", "storageType": "AzureFile", "storageName": "m78-documents",
            "mountOptions": "uid=100,gid=101,dir_mode=0770,file_mode=0770,vers=3.1.1,seal",
        }]
        assert any("managedEnvironments/storages" in item for item in resource["dependsOn"])
        assert "listKeys(" not in json.dumps(template)
        env = template["containers"][0]["env"]
        assert "'OPENCANVAS_DOCUMENT_STORAGE_ROOT', 'value', '/app/data/documents'" in env
        assert "'OPENCANVAS_STORAGE_PROVIDER', 'value', 'local'" in env
    assert "listKeys(" not in json.dumps(compiled_storage["outputs"])
    for job in compiled_storage["resources"]:
        if job["type"] == "Microsoft.App/jobs" and job is not worker:
            assert "volumes" not in job["properties"]["template"]


def test_migration_identity_probe_receives_exact_private_api_target(
    compiled_storage: dict[str, Any],
) -> None:
    probe = _resource(compiled_storage, "Microsoft.App/jobs", "-probe-migrate")
    env = probe["properties"]["template"]["containers"][0]["env"]
    assert "M78_PRIVATE_API_URL" in env
    assert "https://{0}" in env and "Microsoft.App/containerApps" in env
    assert "properties.configuration.ingress.fqdn" not in env  # ARM reference is properties.
    assert "configuration.ingress.fqdn" in env
    assert "migrationIdentity" in json.dumps(probe["identity"])
    assert probe["properties"]["template"]["containers"][0]["args"] == ["--phase", "migration"]


async def test_existing_adapter_reads_api_upload_from_independent_worker(tmp_path: Path) -> None:
    # Local filesystem integration proves the adapter handoff, not Azure SMB mounting.
    api = LocalDocumentStorage(tmp_path / "documents")
    worker = LocalDocumentStorage(tmp_path / "documents")
    content = b"bounded synthetic PostgreSQL campaign document"
    uploaded = await api.store(uuid.uuid4(), ".txt", content)
    assert await worker.read(uploaded.storage_key) == content
    await worker.delete(uploaded.storage_key)
    assert not list((tmp_path / "documents").iterdir())
