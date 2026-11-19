"""Unit tests for object store adapter selection."""
import pytest
from app.adapters.registry import object_stores
from app.core.exceptions import AdapterConfigurationError


@pytest.mark.unit
def test_unknown_backend_name_raises_adapter_configuration_error():
    with pytest.raises(AdapterConfigurationError):
        object_stores.create("unknown_store_backend")
