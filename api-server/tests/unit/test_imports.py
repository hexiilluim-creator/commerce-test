from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import omnicall_v9  # noqa: E402


def _discover_omnicall_modules() -> list[str]:
    modules = [omnicall_v9.__name__]
    modules.extend(
        sorted(
            module_info.name
            for module_info in pkgutil.walk_packages(
                omnicall_v9.__path__,
                prefix=f"{omnicall_v9.__name__}.",
            )
        )
    )
    return modules


MODULES_TO_IMPORT = _discover_omnicall_modules()


@pytest.mark.unit
@pytest.mark.parametrize("module_name", MODULES_TO_IMPORT)
def test_all_omnicall_v9_modules_import_without_error(module_name: str) -> None:
    """Garantit en CI que tous les modules omnicall_v9 s'importent proprement."""
    importlib.invalidate_caches()

    try:
        importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - exercised only on failure
        pytest.fail(f"Import échoué pour {module_name}: {exc!r}")
