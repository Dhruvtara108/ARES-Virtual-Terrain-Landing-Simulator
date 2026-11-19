"""Inspect a validated image set and write a portable dataset manifest."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .image_validation import ImageRecord, validate_images

EXIF_CAMERA_TAGS = {
    271: "camera_manufacturer",
    272: "camera_model",
    37386: "focal_length_mm",
    41989: "focal_length_35mm_equivalent_mm",
}


@dataclass(frozen=True)
class ImageSetInspection:
    input_path: Path
    total_files: int
    rejected: tuple[ImageRecord, ...]
    manifest: dict[str, Any]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip().replace("\x00", "")
    return text or None


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        result = float(value[0]) / float(value[1]) if isinstance(value, tuple) else float(value)
    except (IndexError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def _camera_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {field: None for field in EXIF_CAMERA_TAGS.values()}
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            values = dict(exif)
            try:
                values.update(exif.get_ifd(34665))
            except (KeyError, OSError, TypeError, ValueError):
                # Keep any valid top-level tags if the optional EXIF IFD is absent.
                pass
            for tag, field in EXIF_CAMERA_TAGS.items():
                value = values.get(tag)
                metadata[field] = (
                    _clean_text(value)
                    if field in {"camera_manufacturer", "camera_model"}
                    else _number(value)
                )
    except (UnidentifiedImageError, OSError, ValueError):
        # Validation already decodes the image. EXIF absence or malformed EXIF
        # must not cause an otherwise valid photograph to be rejected.
        pass
    return metadata


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def inspect_image_set(input_path: str | Path) -> ImageSetInspection:
    """Analyze all valid inputs without changing source files."""
    validation = validate_images(input_path)
    root = validation.input_path if validation.input_path.is_dir() else validation.input_path.parent

    images: list[dict[str, Any]] = []
    hash_to_images: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in validation.accepted:
        relative_path = _relative_path(record.path, root)
        file_size = record.path.stat().st_size
        with record.path.open("rb") as image_file:
            sha256 = hashlib.file_digest(image_file, "sha256").hexdigest()
        with Image.open(record.path) as image:
            image_format = image.format
            image_mode = image.mode
        image_data: dict[str, Any] = {
            "image_id": f"image_{len(images) + 1:03d}",
            "relative_path": relative_path,
            "file_size_bytes": file_size,
            "sha256": sha256,
            "format": image_format,
            "width": record.width,
            "height": record.height,
            "mode": image_mode,
            **_camera_metadata(record.path),
            "duplicate_group": None,
        }
        images.append(image_data)
        hash_to_images[sha256].append(image_data)

    duplicate_groups: list[dict[str, Any]] = []
    for sha256, group in sorted(hash_to_images.items(), key=lambda item: item[1][0]["relative_path"]):
        if len(group) < 2:
            continue
        group_id = f"duplicate_{len(duplicate_groups) + 1:03d}"
        for image in group:
            image["duplicate_group"] = group_id
        duplicate_groups.append(
            {
                "duplicate_group": group_id,
                "sha256": sha256,
                "image_ids": [image["image_id"] for image in group],
                "file_paths": [image["relative_path"] for image in group],
            }
        )

    duplicate_images = sum(len(group["image_ids"]) - 1 for group in duplicate_groups)
    unique_images = len(images) - duplicate_images
    warnings: list[str] = [
        "Overlapping photographs are recommended for reconstruction; overlap is not verified by this task."
    ]
    if unique_images < 20:
        warnings.append("Fewer than 20 unique photographs are available; approximately 20–30 overlapping photographs are recommended.")
    if duplicate_groups:
        warnings.append(f"{duplicate_images} duplicate photograph(s) were found; duplicates do not count as unique photographs.")

    resolutions = {(image["width"], image["height"]) for image in images}
    if len(resolutions) > 1:
        warnings.append("Images have different resolutions.")
    camera_models = {image["camera_model"] for image in images if image["camera_model"]}
    if len(camera_models) > 1:
        warnings.append("Multiple camera models are present.")
    missing_camera_count = sum(
        not image["camera_manufacturer"] or not image["camera_model"] for image in images
    )
    if missing_camera_count:
        warnings.append(f"Camera manufacturer or model metadata is missing for {missing_camera_count} image(s).")

    manifest = {
        "project": "ARES",
        "schema_version": "1.0",
        "summary": {
            "total_images": validation.total_files,
            "valid_images": len(images),
            "unique_images": unique_images,
            "duplicate_images": duplicate_images,
        },
        "images": images,
        "duplicate_groups": duplicate_groups,
        "warnings": warnings,
    }
    return ImageSetInspection(validation.input_path, validation.total_files, validation.rejected, manifest)


def write_manifest(manifest: dict[str, Any], output_path: str | Path) -> Path:
    """Write UTF-8 JSON, creating parent directories when needed."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
