"""Discover and validate photographs supplied for terrain reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class ImageRecord:
    path: Path
    width: int | None = None
    height: int | None = None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ValidationReport:
    input_path: Path
    total_files: int
    accepted: tuple[ImageRecord, ...]
    rejected: tuple[ImageRecord, ...]
    warnings: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return len(self.accepted) >= 2


def validate_images(input_path: str | Path) -> ValidationReport:
    """Validate one image or every file under a directory without modifying it."""
    path = Path(input_path)
    if path.is_dir():
        candidates = sorted(item for item in path.rglob("*") if item.is_file())
    elif path.is_file():
        candidates = [path]
    else:
        raise FileNotFoundError(f"Input path does not exist or is not accessible: {path}")

    accepted: list[ImageRecord] = []
    rejected: list[ImageRecord] = []
    for candidate in candidates:
        if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            rejected.append(ImageRecord(candidate, error="unsupported file type"))
            continue
        try:
            with Image.open(candidate) as image:
                image.verify()
            with Image.open(candidate) as image:
                width, height = image.size
                image.load()
            accepted.append(ImageRecord(candidate, width=width, height=height))
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            rejected.append(ImageRecord(candidate, error=f"could not decode image ({exc})"))

    warnings = ["Approximately 20–30 overlapping photographs are recommended for the intended reconstruction workflow."]
    if len(accepted) < 2:
        warnings.append("At least 2 valid images are required.")
    return ValidationReport(path, len(candidates), tuple(accepted), tuple(rejected), tuple(warnings))
