"""Test configuration: protects config.yaml from test side-effects.

The config endpoint tests call ``cfg_module.update()`` which writes to the
real ``config.yaml``. This conftest backs up and restores it for the
entire test session so tests don't clobber the developer's config.
"""

import os
import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@pytest.fixture(scope="session", autouse=True)
def backup_config():
    """Back up config.yaml before tests, restore after."""
    backup = None
    if CONFIG_PATH.exists():
        backup = str(CONFIG_PATH) + ".test_backup"
        shutil.copy2(str(CONFIG_PATH), backup)
    yield
    if backup and os.path.exists(backup):
        shutil.copy2(backup, str(CONFIG_PATH))
        os.unlink(backup)
