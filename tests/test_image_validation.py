from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

from ares_terrain.image_validation import validate_images


def make_image(path: Path, color: str = "red") -> Path:
    Image.new("RGB", (32, 24), color).save(path)
    return path


def test_accepts_supported_images_and_reports_dimensions(tmp_path: Path) -> None:
    for suffix in ("jpg", "jpeg", "png", "webp"):
        make_image(tmp_path / f"photo.{suffix}")

    report = validate_images(tmp_path)

    assert report.total_files == 4
    assert len(report.accepted) == 4
    assert {(item.width, item.height) for item in report.accepted} == {(32, 24)}
    assert report.is_valid
    assert any("20–30" in warning for warning in report.warnings)


def test_rejects_corrupted_and_unsupported_files(tmp_path: Path) -> None:
    make_image(tmp_path / "good.png")
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    (tmp_path / "notes.txt").write_text("not a supported image")

    report = validate_images(tmp_path)

    assert report.total_files == 3
    assert len(report.accepted) == 1
    assert len(report.rejected) == 2
    assert "could not decode" in report.rejected[0].error
    assert report.rejected[1].error == "unsupported file type"
    assert not report.is_valid


def test_fewer_than_two_valid_images_fails(tmp_path: Path) -> None:
    make_image(tmp_path / "only.png")

    report = validate_images(tmp_path)

    assert not report.is_valid
    assert any("At least 2" in warning for warning in report.warnings)


def test_discovers_images_recursively(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    make_image(tmp_path / "one.png")
    make_image(nested / "two.webp")

    report = validate_images(tmp_path)

    assert report.total_files == 2
    assert len(report.accepted) == 2


def test_cli_prints_summary_and_returns_success(tmp_path: Path) -> None:
    make_image(tmp_path / "one.png")
    make_image(tmp_path / "two.jpg")
    result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "validate-images", "--input", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Total files discovered: 2" in result.stdout
    assert "Valid images: 2" in result.stdout
    assert "Overall validation result: PASS" in result.stdout
    assert "20–30" in result.stdout


def test_cli_insufficient_images_returns_failure(tmp_path: Path) -> None:
    make_image(tmp_path / "one.png")
    result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "validate-images", "--input", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Overall validation result: FAIL" in result.stdout


def test_missing_path_returns_usage_error(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ares_terrain.cli", "validate-images", "--input", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "does not exist" in result.stderr
