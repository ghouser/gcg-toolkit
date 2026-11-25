"""Where packages data lives and reading/writing it.

The packages, appearance rates, drift and meta reports are tracked in `shared/data/gundam_packages/` under `tool_data_root()` (the
repository unless `$GCG_TOOL_DATA_DIR` stands in, see `shared/dataset.py`), resolved on every call.
"""
from __future__ import annotations

import json
from pathlib import Path

from shared.dataset import tool_data_root, write_atomic
from tools.gundam_packages.models import DataSource, DriftFile, NamesFile, PackageId, PackagesFile, RatesFile
from tools.gundam_packages.naming import NAMES_PATH



def tracked_folder() -> Path:
    """The tracked packages folder under `tool_data_root()`."""
    return tool_data_root() / "shared" / "data" / "gundam_packages"


def _pretty(compact_json: str) -> str:
    return json.dumps(json.loads(compact_json), ensure_ascii=False, indent=1) + "\n"


def _file_name(stem: str, source: DataSource) -> str:
    """`packages.json` for tournament decks, `packages_online.json` for online ones."""
    return f"{stem}.json" if source is DataSource.TOURNAMENT else f"{stem}_{source.value}.json"


def write_packages(file: PackagesFile, out_dir: Path | None = None) -> Path:
    path = (out_dir or tracked_folder()) / _file_name("packages", file.source)
    write_atomic(path, _pretty(file.model_dump_json()))
    return path


def load_packages(out_dir: Path | None = None, source: DataSource = DataSource.TOURNAMENT) -> PackagesFile | None:
    path = (out_dir or tracked_folder()) / _file_name("packages", source)
    return PackagesFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_rates(file: RatesFile, out_dir: Path | None = None) -> Path:
    path = (out_dir or tracked_folder()) / _file_name("rates", file.source)
    write_atomic(path, _pretty(file.model_dump_json()))
    return path


def load_rates(out_dir: Path | None = None, source: DataSource = DataSource.TOURNAMENT) -> RatesFile | None:
    path = (out_dir or tracked_folder()) / _file_name("rates", source)
    return RatesFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_drift(file: DriftFile, out_dir: Path | None = None) -> Path:
    path = (out_dir or tracked_folder()) / "drift.json"
    write_atomic(path, _pretty(file.model_dump_json()))
    return path


def load_drift(out_dir: Path | None = None) -> DriftFile | None:
    path = (out_dir or tracked_folder()) / "drift.json"
    return DriftFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_name_overrides(path: Path = NAMES_PATH) -> dict[PackageId, str]:
    return NamesFile.model_validate_json(path.read_text(encoding="utf-8")).data if path.is_file() else {}
