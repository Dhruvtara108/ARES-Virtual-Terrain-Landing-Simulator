from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from ares_terrain.image_inspection import inspect_image_set, write_manifest


def make_image(path: Path, color: str = "red", size: tuple[int, int] = (32, 24), exif: Image.Exif | None = None) -> Path:
    image = Image.new("RGB", size, color)
    image.save(path, exif=exif or Image.Exif())
    return path


def camera_exif(make: str, model: str, focal: tuple[int, int] = (50, 1)) -> Image.Exif:
    exif = Image.Exif()
    exif[271] = make
    exif[272] = model
    exif[37386] = focal
    exif[41989] = 75
    # These values must never be copied into the manifest.
    exif[36867] = "2026:01:02 03:04:05"
    return exif


def test_extracts_only_requested_camera_exif_and_missing_exif_is_valid(tmp_path: Path) -> None:
    make_image(tmp_path / "with_exif.jpg", exif=camera_exif("Nikon", "D750"))
    make_image(tmp_path / "without_exif.png", color="blue")

    inspection = inspect_image_set(tmp_path)
    first, second = inspection.manifest["images"]

    assert first["camera_manufacturer"] == "Nikon"
    assert first["camera_model"] == "D750"
    assert first["focal_length_mm"] == 50
    assert first["focal_length_35mm_equivalent_mm"] == 75
    assert second["camera_manufacturer"] is None
    assert second["camera_model"] is None
    assert len(inspection.manifest["images"]) == 2
    assert all("timestamp" not in key.lower() and "gps" not in key.lower() for key in first)
    assert any("metadata is missing" in warning for warning in inspection.manifest["warnings"])


def test_hash_duplicates_unique_count_and_duplicate_paths(tmp_path: Path) -> None:
    make_image(tmp_path / "a.png")
    shutil.copyfile(tmp_path / "a.png", tmp_path / "copy.png")
    make_image(tmp_path / "b.png", color="blue")

    manifest = inspect_image_set(tmp_path).manifest

    assert manifest["summary"] == {
        "total_images": 3,
        "valid_images": 3,
        "unique_images": 2,
        "duplicate_images": 1,
    }
    assert len(manifest["duplicate_groups"]) == 1
    assert manifest["duplicate_groups"][0]["file_paths"] == ["a.png", "copy.png"]
    assert [image["image_id"] for image in manifest["images"] if image["duplicate_group"]] == [
        "image_001",
        "image_003",
    ]
    assert any("duplicate photograph(s)" in warning for warning in manifest["warnings"])


def test_diagnostics_detect_resolution_and_camera_model_differences(tmp_path: Path) -> None:
    make_image(tmp_path / "a.jpg", size=(32, 24), exif=camera_exif("Nikon", "D750"))
    make_image(tmp_path / "b.jpg", size=(64, 48), exif=camera_exif("Canon", "R5"))

    warnings = inspect_image_set(tmp_path).manifest["warnings"]

    assert any("different resolutions" in warning for warning in warnings)
    assert any("Multiple camera models" in warning for warning in warnings)


def test_manifest_json_structure_is_utf8_and_deterministic(tmp_path: Path) -> None:
    make_image(tmp_path / "terrain_é.png", exif=camera_exif("Sony", "α7"))
    make_image(tmp_path / "second.webp", color="green")
    first = inspect_image_set(tmp_path).manifest
    second = inspect_image_set(tmp_path).manifest
    output = write_manifest(first, tmp_path / "nested" / "manifest.json")
    raw = output.read_bytes()

    assert first == second
    assert raw.decode("utf-8")
    assert json.loads(raw) == first
    assert first["project"] == "ARES"
    assert first["schema_version"] == "1.0"
    assert first["images"][0]["image_id"] == "image_001"
    assert first["images"][0]["relative_path"] == "second.webp"
    assert "2026:01:02" not in raw.decode("utf-8")
    assert "GPS" not in raw.decode("utf-8")
    assert any("overlap is not verified" in warning for warning in first["warnings"])


def test_inspection_does_not_modify_original_images(tmp_path: Path) -> None:
    original = make_image(tmp_path / "source.jpg", exif=camera_exif("Nikon", "D750"))
    before = original.read_bytes()

    inspect_image_set(tmp_path)

    assert original.read_bytes() == before


def test_inspect_cli_success_writes_manifest_and_reports_summary(tmp_path: Path) -> None:
    make_image(tmp_path / "a.png")
    make_image(tmp_path / "b.png", color="blue")
    output = tmp_path / "reports" / "manifest.json"
    result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "inspect-image-set", "--input", str(tmp_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Valid images: 2" in result.stdout
    assert "Unique images: 2" in result.stdout
    assert "Camera manufacturer/model available: 0/2" in result.stdout
    assert str(output) in result.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["unique_images"] == 2


def test_inspect_cli_duplicate_only_unique_count_fails(tmp_path: Path) -> None:
    make_image(tmp_path / "one.png")
    shutil.copyfile(tmp_path / "one.png", tmp_path / "two.png")
    output = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "inspect-image-set", "--input", str(tmp_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Unique images: 1" in result.stdout
    assert output.exists()


def test_inspect_cli_invalid_input_and_output_return_two(tmp_path: Path) -> None:
    missing_result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "inspect-image-set", "--input", str(tmp_path / "missing"), "--output", str(tmp_path / "manifest.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_result.returncode == 2

    make_image(tmp_path / "a.png")
    make_image(tmp_path / "b.png", color="blue")
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("x")
    output_result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "inspect-image-set", "--input", str(tmp_path), "--output", str(not_a_directory / "manifest.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert output_result.returncode == 2
