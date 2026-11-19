"""CPU-based sparse reconstruction using the installed COLMAP CLI."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .image_validation import validate_images


class ReconstructionError(RuntimeError):
    """Raised when COLMAP fails or does not produce a valid sparse model."""


@dataclass(frozen=True)
class ReconstructionResult:
    report: dict[str, Any]
    report_path: Path
    log_directory: Path


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _run_stage(
    command: Sequence[str], log_path: Path, runner: CommandRunner
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(list(command), capture_output=True, text=True, check=False)
    except OSError as exc:
        log_path.write_text(f"COMMAND: {' '.join(command)}\nFAILED TO START: {exc}\n", encoding="utf-8")
        raise ReconstructionError(f"Could not run COLMAP command; see {log_path}: {exc}") from exc
    log_path.write_text(
        f"COMMAND: {' '.join(command)}\n\nSTDOUT:\n{result.stdout or ''}\nSTDERR:\n{result.stderr or ''}\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise ReconstructionError(
            f"COLMAP stage '{command[1]}' failed with exit code {result.returncode}; see {log_path}"
        )
    return result


def _non_comment_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _parse_camera_positions(images_path: Path) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    lines = images_path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.startswith("#"):
            index += 1
            continue
        fields = line.split(maxsplit=9)
        if len(fields) != 10:
            index += 1
            continue
        try:
            int(fields[0])
            qw, qx, qy, qz = map(float, fields[1:5])
            tx, ty, tz = map(float, fields[5:8])
            int(fields[8])
        except ValueError:
            index += 1
            continue

        # COLMAP stores world-to-camera pose; invert it to report camera center.
        rotation = (
            (1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)),
            (2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)),
            (2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)),
        )
        translation = (tx, ty, tz)
        center = tuple(-sum(rotation[row][column] * translation[row] for row in range(3)) for column in range(3))
        if not all(math.isfinite(value) for value in center):
            index += 1
            continue
        positions.append({"image": fields[9], "x": center[0], "y": center[1], "z": center[2]})
        # COLMAP images.txt stores a 2D observation line after each image line.
        index += 2
    return positions


def _model_statistics(model_text_path: Path) -> tuple[int, int, int, list[dict[str, Any]]]:
    cameras_path = model_text_path / "cameras.txt"
    images_path = model_text_path / "images.txt"
    points_path = model_text_path / "points3D.txt"
    if not all(path.is_file() and path.stat().st_size > 0 for path in (cameras_path, images_path, points_path)):
        raise ReconstructionError(f"COLMAP model text export is incomplete: {model_text_path}")
    cameras = len(_non_comment_lines(cameras_path))
    image_positions = _parse_camera_positions(images_path)
    points = len(_non_comment_lines(points_path))
    return cameras, len(image_positions), points, image_positions


def _ply_vertex_count(path: Path) -> int:
    if not path.is_file() or path.stat().st_size < 64:
        raise ReconstructionError(f"COLMAP did not produce a non-empty PLY point cloud: {path}")
    with path.open("rb") as ply_file:
        header = ply_file.read(65536).split(b"end_header", maxsplit=1)[0].decode("ascii", errors="replace")
    if not header.startswith("ply\n") or "format " not in header:
        raise ReconstructionError(f"PLY header is invalid: {path}")
    for line in header.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[:2] == ["element", "vertex"]:
            try:
                return int(fields[2])
            except ValueError as exc:
                raise ReconstructionError(f"PLY vertex count is invalid: {path}") from exc
    raise ReconstructionError(f"PLY header does not declare vertices: {path}")


def run_sparse_reconstruction(
    input_path: str | Path,
    output_path: str | Path,
    camera_mode: str = "single",
    *,
    colmap_executable: str | None = None,
    command_runner: CommandRunner | None = None,
) -> ReconstructionResult:
    """Run feature extraction, exhaustive matching, mapping, analysis, and PLY export."""
    if camera_mode not in {"single", "per-image"}:
        raise ValueError("camera_mode must be 'single' or 'per-image'")
    validation = validate_images(input_path)
    if len(validation.accepted) < 2:
        raise ReconstructionError("At least two valid input photographs are required.")
    if validation.rejected:
        names = ", ".join(str(item.path) for item in validation.rejected[:5])
        raise ReconstructionError(f"Input contains unsupported or invalid files: {names}")

    executable = colmap_executable or shutil.which("colmap")
    if not executable:
        raise FileNotFoundError("COLMAP executable was not found on PATH.")
    runner = command_runner or subprocess.run
    source = validation.input_path.resolve()
    output = Path(output_path).resolve()
    output.mkdir(parents=True, exist_ok=True)
    database_path = output / "database.db"
    sparse_path = output / "sparse"
    model_path = sparse_path / "0"
    resume_existing_model = model_path.exists()
    if database_path.exists() != resume_existing_model:
        raise ReconstructionError(
            f"Output has an incomplete prior run (database and sparse/0 must both exist or both be absent): {output}"
        )
    logs_root = output / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    log_directory = logs_root / run_id
    suffix = 1
    while log_directory.exists():
        log_directory = logs_root / f"{run_id}-{suffix}"
        suffix += 1
    log_directory.mkdir()
    image_list_path = log_directory / "image_list.txt"
    image_list_path.write_text(
        "".join(f"{record.path.relative_to(validation.input_path).as_posix()}\n" for record in validation.accepted),
        encoding="utf-8",
    )
    sparse_path.mkdir(parents=True, exist_ok=True)
    start_time = time.monotonic()

    camera_arguments = (
        ["--ImageReader.single_camera", "1"]
        if camera_mode == "single"
        else ["--ImageReader.single_camera_per_image", "1"]
    )
    common = [str(executable)]
    stages = [
        (
            "feature_extractor",
            [
                *common, "feature_extractor", "--database_path", str(database_path),
                "--image_path", str(source), "--image_list_path", str(image_list_path),
                "--ImageReader.camera_model", "SIMPLE_RADIAL", *camera_arguments,
                "--SiftExtraction.use_gpu", "0", "--SiftExtraction.num_threads", "4",
                "--SiftExtraction.max_image_size", "1600",
            ],
        ),
        (
            "exhaustive_matcher",
            [
                *common, "exhaustive_matcher", "--database_path", str(database_path),
                "--SiftMatching.use_gpu", "0", "--SiftMatching.num_threads", "4",
            ],
        ),
        (
            "mapper",
            [
                *common, "mapper", "--database_path", str(database_path),
                "--image_path", str(source), "--image_list_path", str(image_list_path),
                "--output_path", str(sparse_path), "--Mapper.num_threads", "4",
                "--Mapper.multiple_models", "0",
            ],
        ),
    ]

    if not resume_existing_model:
        for name, command in stages:
            _run_stage(command, log_directory / f"{name}.log", runner)
            if name == "exhaustive_matcher" and not database_path.is_file():
                raise ReconstructionError(f"COLMAP completed matching but did not create the database: {database_path}")

    expected_model_files = [model_path / name for name in ("cameras.bin", "images.bin", "points3D.bin")]
    if not model_path.is_dir() or not all(path.is_file() and path.stat().st_size > 0 for path in expected_model_files):
        raise ReconstructionError(f"COLMAP mapper returned success but did not produce a complete sparse/0 model: {model_path}")

    analyzer = _run_stage(
        [str(executable), "model_analyzer", "--path", str(model_path)],
        log_directory / "model_analyzer.log",
        runner,
    )
    model_text_path = log_directory / "model_text"
    model_text_path.mkdir(parents=True, exist_ok=True)
    _run_stage(
        [str(executable), "model_converter", "--input_path", str(model_path), "--output_path", str(model_text_path), "--output_type", "TXT"],
        log_directory / "model_converter_txt.log",
        runner,
    )
    camera_count, registered_count, point_count, camera_positions = _model_statistics(model_text_path)
    ply_path = model_path / "points3D.ply"
    _run_stage(
        [str(executable), "model_converter", "--input_path", str(model_path), "--output_path", str(ply_path), "--output_type", "PLY"],
        log_directory / "model_converter_ply.log",
        runner,
    )
    ply_point_count = _ply_vertex_count(ply_path)
    if registered_count < 2 or point_count < 1 or camera_count < 1 or ply_point_count < 1:
        raise ReconstructionError(
            "COLMAP produced model files, but the reconstruction has insufficient registered images, cameras, or points."
        )
    if point_count != ply_point_count:
        raise ReconstructionError(
            f"Sparse model has {point_count} points but PLY declares {ply_point_count} vertices."
        )

    elapsed = time.monotonic() - start_time
    processing_time_basis = "current pipeline wall time"
    if resume_existing_model:
        prior_runs = []
        for prior_log_dir in logs_root.iterdir():
            if prior_log_dir == log_directory or not prior_log_dir.is_dir():
                continue
            image_list = prior_log_dir / "image_list.txt"
            mapper_log = prior_log_dir / "mapper.log"
            required_logs = ("feature_extractor.log", "exhaustive_matcher.log", "mapper.log")
            if image_list.is_file() and all((prior_log_dir / name).is_file() for name in required_logs):
                duration = mapper_log.stat().st_mtime - image_list.stat().st_mtime
                if duration >= 0:
                    prior_runs.append((mapper_log.stat().st_mtime, duration))
        if prior_runs:
            elapsed += max(prior_runs)[1]
            processing_time_basis = "prior image-list-to-mapper log span plus current verification/export wall time"
    warnings = [
        "Camera EXIF metadata is missing; shared SIMPLE_RADIAL calibration was assumed and refined by COLMAP."
    ]
    unregistered = len(validation.accepted) - registered_count
    if unregistered:
        warnings.append(f"{unregistered} input photograph(s) were not registered by COLMAP.")
        warnings.append("The sparse model covers only part of the input image set; inspect matching and mapping logs before relying on it.")
    warnings.append("Sparse reconstruction only; no dense reconstruction or mesh was generated.")
    report: dict[str, Any] = {
        "input_photographs": len(validation.accepted),
        "registered_photographs": registered_count,
        "unregistered_photographs": unregistered,
        "cameras": camera_count,
        "points_3d": point_count,
        "ply_vertices": ply_point_count,
        "camera_mode": camera_mode,
        "camera_model": "SIMPLE_RADIAL",
        "sparse_model_path": str(model_path),
        "ply_path": str(ply_path),
        "processing_seconds": round(elapsed, 3),
        "processing_time_basis": processing_time_basis,
        "result_status": "PASS" if unregistered == 0 else "PARTIAL",
        "camera_positions": camera_positions,
        "model_analyzer_output": (analyzer.stdout or analyzer.stderr).strip(),
        "warnings": warnings,
        "log_directory": str(log_directory),
    }
    report_path = log_directory / "reconstruction_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ReconstructionResult(report, report_path, log_directory)
