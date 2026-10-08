"""Azure adapter contract with an SDK double, not actual Azure verification."""
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError

from backend.app.storage import AzureReportStorage, StorageError, MAX_PDF_BYTES


class Blob:
    data = None
    def upload_blob(self, data, **kwargs):
        assert kwargs["overwrite"] is False
        assert kwargs["content_settings"].content_type == "application/pdf"
        if self.data is not None:
            raise ResourceExistsError("synthetic existing blob")
        self.data = data

    def get_blob_properties(self):
        return SimpleNamespace(size=len(self.data))

    def download_blob(self, **kwargs):
        return SimpleNamespace(readall=lambda: self.data)


class Container:
    public = False
    def __init__(self):
        self.blob = Blob()

    def get_container_properties(self):
        return {"public_access": "blob" if self.public else None}

    def get_blob_client(self, key):
        return self.blob


def test_azure_create_only_private_container_and_integrity_contract():
    container = Container()
    client = SimpleNamespace(get_container_client=lambda name: container)
    storage = AzureReportStorage("https://synthetic.blob.core.windows.net", "reports", client=client)
    key = "reports/" + "a" * 32 + ".pdf"
    storage.put(key, b"%PDF-synthetic")
    storage.put(key, b"%PDF-synthetic")
    assert storage.read(key) == b"%PDF-synthetic"
    with pytest.raises(StorageError):
        storage.put(key, b"different")
    container.public = True
    with pytest.raises(StorageError):
        storage.read(key)
    with pytest.raises(StorageError):
        storage.put(key, b"%PDF-synthetic")
    container.public = False
    container.blob.get_blob_properties = lambda: SimpleNamespace(size=MAX_PDF_BYTES + 1)
    with pytest.raises(StorageError):
        storage.read(key)


@pytest.mark.parametrize("url", ["http://synthetic.blob.core.windows.net", "https://example.com", "https://synthetic.blob.core.windows.net?sig=secret", "https://user:secret@synthetic.blob.core.windows.net"])
def test_azure_rejects_non_account_or_secret_urls(url):
    with pytest.raises(ValueError):
        AzureReportStorage(url, "reports")


def test_azure_sdk_errors_stay_private():
    def fail():
        raise RuntimeError("secret credential/path synthetic")
    container = SimpleNamespace(get_container_properties=fail)
    client = SimpleNamespace(get_container_client=lambda name: container)
    storage = AzureReportStorage("https://synthetic.blob.core.windows.net", "reports", client=client)
    with pytest.raises(StorageError) as error:
        storage.read("reports/" + "b" * 32 + ".pdf")
    assert "secret" not in str(error.value)
