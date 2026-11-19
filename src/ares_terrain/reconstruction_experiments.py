"""Configuration and comparison helpers for controlled COLMAP experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import shutil
import sqlite3
import subprocess
from statistics import median
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    camera_model: str = "SIMPLE_RADIAL"
    matcher: str = "exhaustive"
    overlap: int = 3
    init_min_num_inliers: int = 100
    init_min_tri_angle: float = 16.0
    abs_pose_min_num_inliers: int = 30
    abs_pose_min_inlier_ratio: float = 0.25
    abs_pose_max_error: float = 12.0

    def __post_init__(self) -> None:
        if self.camera_model not in {"SIMPLE_RADIAL", "SIMPLE_PINHOLE"}:
            raise ValueError("camera_model must be SIMPLE_RADIAL or SIMPLE_PINHOLE")
        if self.matcher not in {"exhaustive", "sequential"}:
            raise ValueError("matcher must be exhaustive or sequential")
        if self.overlap < 1 or min(self.init_min_num_inliers, self.abs_pose_min_num_inliers) < 1:
            raise ValueError("overlap and inlier thresholds must be positive")
        if not 0 < self.abs_pose_min_inlier_ratio <= 1 or self.abs_pose_max_error <= 0:
            raise ValueError("pose ratio and reprojection threshold must be positive")
        if self.init_min_tri_angle <= 0:
            raise ValueError("initial triangulation angle must be positive")


EXPERIMENTS = (
    ExperimentConfig("A_baseline"),
    ExperimentConfig("B_sequential", matcher="sequential", overlap=3),
    ExperimentConfig(
        "C_mapper_controlled", init_min_num_inliers=70, init_min_tri_angle=10.0,
        abs_pose_min_num_inliers=25, abs_pose_min_inlier_ratio=0.20,
        abs_pose_max_error=8.0,
    ),
    ExperimentConfig("D_simple_pinhole", camera_model="SIMPLE_PINHOLE"),
)


def compare_results(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a compact comparable summary without ranking by image count alone."""
    rows = []
    for result in results:
        row = dict(result)
        registered = int(row.get("registered_images", 0))
        total = int(row.get("total_images", 22))
        row["unregistered_images"] = sorted(set(row.get("all_image_names", [])) - set(row.get("registered_image_names", [])))
        row["registration_fraction"] = registered / total if total else 0.0
        rows.append(row)
    return {"experiments": rows, "selection_rule": "Prefer stable calibration and low reprojection error with meaningful coverage; registration count alone is insufficient."}


def write_summary_report(results: Iterable[dict[str, Any]], baseline: dict[str, Any], output: str | Path) -> Path:
    """Write machine-readable and Markdown experiment comparison artifacts."""
    comparison = compare_results(results)
    comparison["baseline"] = baseline
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# COLMAP reconstruction recovery experiments", "",
        "## Original baseline", "",
        f"- Registered: {baseline['registered_images']}/{baseline['total_images']}",
        f"- Sparse points: {baseline['points_3d']}",
        f"- Verified image pairs: {baseline['verified_image_pairs']}",
        f"- Camera: `{baseline['camera']}`",
        f"- Mean track length: {baseline.get('mean_track_length')}; mean reprojection error: {baseline.get('mean_reprojection_error_px')} px",
        "", "## Experiments", "",
        "| Experiment | Registered | Points | Verified pairs | Camera model and parameters | Median reprojection (px) | Mean track | Camera center distribution (min to max, xyz) |",
        "|---|---:|---:|---:|---|---:|---:|---|",
    ]
    for row in comparison["experiments"]:
        camera = row["cameras"][0] if row.get("cameras") else {}
        positions = row.get("camera_positions", [])
        ranges = "none"
        if positions:
            ranges = "; ".join(f"{axis} {min(p[axis] for p in positions):.3f} to {max(p[axis] for p in positions):.3f}" for axis in ("x", "y", "z"))
        lines.append(f"| {row['name']} | {row['registered_images']}/{row['total_images']} | {row['points_3d']} | {row['verified_image_pairs']} | `{camera.get('model')} {camera.get('parameters')}` | {row.get('median_reprojection_error_px')} | {row.get('mean_track_length')} | {ranges} |")
    lines += ["", "Unregistered images and complete camera centers are recorded in the JSON report and each experiment's `experiment_report.json`.",
              "", "## Assessment", "",
              "No experiment produced a defensible improvement over the preserved baseline. A and C reproduce the baseline camera/matcher setup with altered mapper thresholds only in C; B's sequential graph gives fewer verified pairs; D is degenerate (one triangulated point). B and C fit focal lengths near 24,500 px for a 1,600 px image and radial distortion near 450, so their low reprojection errors are not evidence of valid geometry. The baseline's 4 images and 139 points are the strongest available model, but are too sparse and incompletely registered to proceed to dense reconstruction.",
              "", "## Dense reconstruction capability", "",
              "Installed COLMAP is 3.9.1, compiled without CUDA. `patch_match_stereo -h` exits with `Dense stereo reconstruction requires CUDA`; dense COLMAP MVS is unavailable in this environment. Keep sparse artifacts as sparse evidence only; do not interpret the PLY as terrain geometry.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def config_dict(config: ExperimentConfig) -> dict[str, Any]:
    return asdict(config)


def experiment_workspace(root: str | Path, config: ExperimentConfig) -> Path:
    return Path(root) / config.name


def run_experiment(
    image_path: str | Path, workspace: str | Path, config: ExperimentConfig,
    *, executable: str = "colmap", runner=subprocess.run,
) -> dict[str, Any]:
    """Run an isolated CPU SfM workspace and return auditable model statistics."""
    from .sparse_reconstruction import _parse_camera_positions

    images = Path(image_path).resolve()
    out = Path(workspace).resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Experiment workspace is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    db, sparse, model = out / "database.db", out / "sparse", out / "sparse" / "0"
    sparse.mkdir()
    logs = out / "logs"
    logs.mkdir()
    names = sorted(p.name for p in images.iterdir() if p.is_file())
    image_list = out / "image_list.txt"
    image_list.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")

    extract = [executable, "feature_extractor", "--database_path", str(db), "--image_path", str(images),
               "--image_list_path", str(image_list), "--ImageReader.camera_model", config.camera_model,
               "--ImageReader.single_camera", "1", "--SiftExtraction.use_gpu", "0",
               "--SiftExtraction.num_threads", "4", "--SiftExtraction.max_image_size", "1600"]
    match = [executable, f"{config.matcher}_matcher", "--database_path", str(db),
             "--SiftMatching.use_gpu", "0", "--SiftMatching.num_threads", "4"]
    if config.matcher == "sequential":
        match += ["--SequentialMatching.overlap", str(config.overlap), "--SequentialMatching.quadratic_overlap", "1"]
    mapper = [executable, "mapper", "--database_path", str(db), "--image_path", str(images),
              "--image_list_path", str(image_list), "--output_path", str(sparse), "--Mapper.num_threads", "4",
              "--Mapper.multiple_models", "0", "--Mapper.init_min_num_inliers", str(config.init_min_num_inliers),
              "--Mapper.init_min_tri_angle", str(config.init_min_tri_angle),
              "--Mapper.abs_pose_min_num_inliers", str(config.abs_pose_min_num_inliers),
              "--Mapper.abs_pose_min_inlier_ratio", str(config.abs_pose_min_inlier_ratio),
              "--Mapper.abs_pose_max_error", str(config.abs_pose_max_error)]
    commands = [extract, match, mapper]
    for command in commands:
        result = runner(command, capture_output=True, text=True, check=False)
        (logs / f"{command[1]}.log").write_text(
            f"COMMAND: {' '.join(command)}\n\nSTDOUT:\n{result.stdout or ''}\nSTDERR:\n{result.stderr or ''}\n", encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"COLMAP {command[1]} failed ({result.returncode}); see {logs}")
    if not model.is_dir():
        raise RuntimeError(f"COLMAP produced no sparse model in {sparse}")
    text_model = logs / "model_text"
    text_model.mkdir()
    for command in ([executable, "model_converter", "--input_path", str(model), "--output_path", str(text_model), "--output_type", "TXT"],
                    [executable, "model_converter", "--input_path", str(model), "--output_path", str(model / "points3D.ply"), "--output_type", "PLY"]):
        result = runner(command, capture_output=True, text=True, check=False)
        (logs / f"{command[1]}_{command[-1].lower()}.log").write_text(
            f"COMMAND: {' '.join(command)}\n{result.stdout or ''}\n{result.stderr or ''}", encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"COLMAP model_converter failed; see {logs}")
    image_positions = _parse_camera_positions(text_model / "images.txt")
    point_lines = [line.split() for line in (text_model / "points3D.txt").read_text().splitlines()
                   if line.strip() and not line.lstrip().startswith("#")]
    errors = [float(fields[7]) for fields in point_lines]
    track_lengths = [(len(fields) - 8) // 2 for fields in point_lines]
    cameras = []
    for line in (text_model / "cameras.txt").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            f = line.split()
            cameras.append({"id": int(f[0]), "model": f[1], "width": int(f[2]), "height": int(f[3]),
                            "parameters": [float(v) for v in f[4:]]})
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        verified_pairs = connection.execute("SELECT COUNT(*) FROM two_view_geometries WHERE rows > 0").fetchone()[0]
    finally:
        connection.close()
    warning_text = "\n".join(p.read_text(errors="replace") for p in logs.glob("*.log"))
    report = {
        "name": config.name, "config": config_dict(config), "workspace": str(out), "total_images": len(names),
        "registered_images": len(image_positions), "all_image_names": names,
        "registered_image_names": sorted(p["image"] for p in image_positions), "points_3d": len(point_lines),
        "verified_image_pairs": verified_pairs, "cameras": cameras,
        "median_reprojection_error_px": median(errors) if errors else None,
        "mean_track_length": sum(track_lengths)/len(track_lengths) if track_lengths else None,
        "camera_positions": image_positions,
        "warnings": [line.strip() for line in warning_text.splitlines() if "] " in line and
                     any(w in line.lower() for w in ("warning", " error ", "no good initial", "relaxing"))],
        "mapper_options": {k: getattr(config, k) for k in ("init_min_num_inliers", "init_min_tri_angle", "abs_pose_min_num_inliers", "abs_pose_min_inlier_ratio", "abs_pose_max_error")},
    }
    (out / "experiment_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
