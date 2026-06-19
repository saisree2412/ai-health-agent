"""Pytest config — enables asyncio mode for `pytest-asyncio`."""

import pytest

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
