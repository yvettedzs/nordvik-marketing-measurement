import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: re-runs the analysis scripts in a temp folder (deselect with -m 'not slow')")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def df() -> pd.DataFrame:
    """Independent pandas copy of the dataset, used to cross-check the server's DuckDB queries."""
    return pd.read_csv(REPO_ROOT / "data" / "simulated_weekly_data.csv")
