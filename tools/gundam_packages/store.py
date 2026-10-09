"""Where packages data lives and reading/writing it."""
from __future__ import annotations

import json
from pathlib import Path

from tools.gundam_meta.store import write_atomic
from tools.gundam_packages.models import DataSource, DriftFile, NamesFile, PackageId, PackagesFile, RatesFile
from tools.gundam_packages.naming import NAMES_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "shared" / "data" / "gundam_packages"


def _pretty(compact_json: str) -> str:
    return json.dumps(json.loads(compact_json), ensure_ascii=False, indent=1) + "\n"


def _file_name(stem: str, source: DataSource) -> str:
    """`packages.json` for tournament decks, `packages_online.json` for online ones."""
    return f"{stem}.json" if source is DataSource.TOURNAMENT else f"{stem}_{source.value}.json"


def write_packages(file: PackagesFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / _file_name("packages", file.source)
    write_atomic(path, _pretty(file.model_dump_json()))
    return path


def load_packages(out_dir: Path = OUT_DIR, source: DataSource = DataSource.TOURNAMENT) -> PackagesFile | None:
    path = out_dir / _file_name("packages", source)
    return PackagesFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_rates(file: RatesFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / _file_name("rates", file.source)
    write_atomic(path, _pretty(file.model_dump_json()))
    return path


def load_rates(out_dir: Path = OUT_DIR, source: DataSource = DataSource.TOURNAMENT) -> RatesFile | None:
    path = out_dir / _file_name("rates", source)
    return RatesFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_drift(file: DriftFile, out_dir: Path = OUT_DIR) -> Path:
    path = out_dir / "drift.json"
    write_atomic(path, _pretty(file.model_dump_json()))
    return path


def load_drift(out_dir: Path = OUT_DIR) -> DriftFile | None:
    path = out_dir / "drift.json"
    return DriftFile.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_name_overrides(path: Path = NAMES_PATH) -> dict[PackageId, str]:
    return NamesFile.model_validate_json(path.read_text(encoding="utf-8")).data if path.is_file() else {}
