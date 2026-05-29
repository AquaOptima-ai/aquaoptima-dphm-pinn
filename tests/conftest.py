"""Root pytest conftest. Exposes the Sprint 23 Yilan synthetic fixture
(`yilan_csv`) to both tests/dataio and tests/training.
"""

from tests.conftest_yilan_helpers import yilan_csv, EXPECTED_GAP_COUNT  # noqa: F401
