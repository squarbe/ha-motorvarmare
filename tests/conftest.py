import os

import pytest

import custom_components

_OWN = os.path.join(os.path.dirname(os.path.dirname(__file__)), "custom_components")
if _OWN not in custom_components.__path__:
    custom_components.__path__.insert(0, _OWN)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
