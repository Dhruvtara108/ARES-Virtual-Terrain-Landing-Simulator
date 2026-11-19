from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from ares_terrain.sparse_reconstruction import ReconstructionError, run_sparse_reconstruction


def make_photo(path: Path, color: str = "red") -> Path:
    Image.new("RGB", (64, 48), color).save(path)
    return path


def successful_runner(*, omit_model: bool = False):
    def run(command, **kwargs):
        command = list(command)
        stage = command[1]
        if stage == "feature_extractor":
            database = Path(command[command.index("--database_path") + 1])
            database.write_bytes(b"mock colmap database")
        elif stage == "mapper" and not omit_model:
            sparse_path = Path(command[command.index("--output_path") + 1])
            model_path = sparse_path / "0"
            model_path.mkdir(parents=True)
            for name in ("cameras.bin", "images.bin", "points3D.bin"):
                (model_path / name).write_bytes(b"mock binary model")
        elif stage == "model_converter":
            output_path = Path(command[command.index("--output_path") + 1])
            output_type = command[command.index("--output_type") + 1]
            if output_type == "TXT":
                output_path.mkdir(parents=True, exist_ok=True)
                (output_path / "cameras.txt").write_text(
                    "# CAMERA_ID MODEL WIDTH HEIGHT PARAMS[]\n1 SIMPLE_RADIAL 64 48 50 32 24 0\n",
                    encoding="utf-8",
                )
                (output_path / "images.txt").write_text(
                    "# IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME\n"
                    "1 1 0 0 0 -1 -2 -3 1 room one.jpg\n10 10 1\n"
                    "2 1 0 0 0 -4 -5 -6 1 room two.jpg\n20 20 2\n",
                    encoding="utf-8",
                )
                (output_path / "points3D.txt").write_text(
                    "# POINT3D_ID X Y Z R G B ERROR TRACK[]\n1 0 0 0 255 0 0 0.1 1 0 2 0\n2 1 1 1 0 255 0 0.2 1 1 2 1\n",
                    encoding="utf-8",
                )
            else:
                output_path.write_text(
                    "ply\nformat ascii 1.0\nelement vertex 2\n"
                    "property float x\nproperty float y\nproperty float z\nend_header\n"
                    "0 0 0\n1 1 1\n",
                    encoding="ascii",
                )
        stdout = "Registered images: 2\nPoints: 2\n" if stage == "model_analyzer" else "stage complete\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return run


def test_missing_colmap_executable_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    make_photo(input_dir / "one.png")
    make_photo(input_dir / "two.png", "blue")
    monkeypatch.setattr("ares_terrain.sparse_reconstruction.shutil.which", lambda _: None)

    with pytest.raises(FileNotFoundError, match="COLMAP executable"):
        run_sparse_reconstruction(input_dir, tmp_path / "output")


def test_invalid_input_directory_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        run_sparse_reconstruction(tmp_path / "missing", tmp_path / "output", colmap_executable="colmap")


def test_incorrect_camera_mode_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="camera_mode"):
        run_sparse_reconstruction(tmp_path / "missing", tmp_path / "output", "shared")


def test_colmap_subprocess_failure_is_logged(tmp_path: Path) -> None:
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    make_photo(input_dir / "one.png")
    make_photo(input_dir / "two.png", "blue")
    output = tmp_path / "nested" / "output"

    def fail(command, **kwargs):
        return subprocess.CompletedProcess(command, 17, stdout="partial", stderr="matcher exploded")

    with pytest.raises(ReconstructionError, match="feature_extractor.*exit code 17"):
        run_sparse_reconstruction(input_dir, output, colmap_executable="colmap", command_runner=fail)
    logs = list((output / "logs").glob("run-*/feature_extractor.log"))
    assert len(logs) == 1
    assert "matcher exploded" in logs[0].read_text(encoding="utf-8")


def test_missing_sparse_model_output_is_failure(tmp_path: Path) -> None:
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    make_photo(input_dir / "one.png")
    make_photo(input_dir / "two.png", "blue")

    with pytest.raises(ReconstructionError, match="did not produce a complete sparse/0 model"):
        run_sparse_reconstruction(
            input_dir,
            tmp_path / "output",
            colmap_executable="colmap",
            command_runner=successful_runner(omit_model=True),
        )


def test_successful_mocked_reconstruction_and_cpu_single_camera_flags(tmp_path: Path) -> None:
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    make_photo(input_dir / "one.png")
    make_photo(input_dir / "two.png", "blue")
    output = tmp_path / "created" / "output"
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_dir.iterdir()}
    commands: list[list[str]] = []

    def recording_runner(command, **kwargs):
        commands.append(list(command))
        return successful_runner() (command, **kwargs)

    result = run_sparse_reconstruction(
        input_dir,
        output,
        "single",
        colmap_executable="colmap",
        command_runner=recording_runner,
    )

    assert result.report["input_photographs"] == 2
    assert result.report["registered_photographs"] == 2
    assert result.report["unregistered_photographs"] == 0
    assert result.report["cameras"] == 1
    assert result.report["points_3d"] == 2
    assert result.report["result_status"] == "PASS"
    assert result.report["camera_positions"][0] == {"image": "room one.jpg", "x": 1.0, "y": 2.0, "z": 3.0}
    assert result.report_path.is_file()
    assert (output / "database.db").is_file()
    assert (output / "sparse" / "0" / "points3D.ply").is_file()
    extraction = next(command for command in commands if command[1] == "feature_extractor")
    matcher = next(command for command in commands if command[1] == "exhaustive_matcher")
    assert "SIMPLE_RADIAL" in extraction
    assert extraction[extraction.index("--ImageReader.single_camera") + 1] == "1"
    assert extraction[extraction.index("--SiftExtraction.use_gpu") + 1] == "0"
    assert extraction[extraction.index("--SiftExtraction.num_threads") + 1] == "4"
    assert extraction[extraction.index("--SiftExtraction.max_image_size") + 1] == "1600"
    assert matcher[matcher.index("--SiftMatching.use_gpu") + 1] == "0"
    assert matcher[matcher.index("--SiftMatching.num_threads") + 1] == "4"
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_dir.iterdir()} == before


def test_per_image_camera_mode_uses_installed_option(tmp_path: Path) -> None:
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    make_photo(input_dir / "one.png")
    make_photo(input_dir / "two.png", "blue")
    commands: list[list[str]] = []

    def recording_runner(command, **kwargs):
        commands.append(list(command))
        return successful_runner()(command, **kwargs)

    run_sparse_reconstruction(
        input_dir,
        tmp_path / "output",
        "per-image",
        colmap_executable="colmap",
        command_runner=recording_runner,
    )

    extraction = next(command for command in commands if command[1] == "feature_extractor")
    assert extraction[extraction.index("--ImageReader.single_camera_per_image") + 1] == "1"


def test_existing_database_is_not_overwritten(tmp_path: Path) -> None:
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    make_photo(input_dir / "one.png")
    make_photo(input_dir / "two.png", "blue")
    output = tmp_path / "output"
    output.mkdir()
    database = output / "database.db"
    database.write_bytes(b"preserve me")

    with pytest.raises(ReconstructionError, match="incomplete prior run"):
        run_sparse_reconstruction(input_dir, output, colmap_executable="colmap", command_runner=successful_runner())
    assert database.read_bytes() == b"preserve me"
