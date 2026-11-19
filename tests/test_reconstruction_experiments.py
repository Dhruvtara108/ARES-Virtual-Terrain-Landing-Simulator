from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from ares_terrain.reconstruction_experiments import (
    EXPERIMENTS,
    ExperimentConfig,
    compare_results,
    run_experiment,
)


def test_experiment_matrix_is_separate_and_cpu_controlled() -> None:
    assert [item.name for item in EXPERIMENTS] == [
        "A_baseline", "B_sequential", "C_mapper_controlled", "D_simple_pinhole"
    ]
    assert EXPERIMENTS[1].matcher == "sequential"
    assert EXPERIMENTS[1].overlap == 3
    assert EXPERIMENTS[3].camera_model == "SIMPLE_PINHOLE"
    assert all(item.camera_model in {"SIMPLE_RADIAL", "SIMPLE_PINHOLE"} for item in EXPERIMENTS)


@pytest.mark.parametrize("kwargs", [
    {"camera_model": "OPENCV"}, {"matcher": "vocab_tree"}, {"overlap": 0},
    {"abs_pose_min_inlier_ratio": 1.1}, {"init_min_tri_angle": 0},
])
def test_invalid_experiment_configuration_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ExperimentConfig("bad", **kwargs)


def test_comparison_lists_unregistered_images_and_does_not_claim_quality() -> None:
    result = compare_results([{
        "name": "small", "total_images": 3, "registered_images": 1,
        "all_image_names": ["a", "b", "c"], "registered_image_names": ["a"],
    }])
    row = result["experiments"][0]
    assert row["unregistered_images"] == ["b", "c"]
    assert row["registration_fraction"] == pytest.approx(1 / 3)
    assert "count alone" in result["selection_rule"]


def test_run_experiment_uses_mocked_colmap_stages(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.jpg").write_bytes(b"a")
    (images / "b.jpg").write_bytes(b"b")
    seen: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        if command[1] == "feature_extractor":
            database = Path(command[command.index("--database_path") + 1])
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE two_view_geometries (rows INTEGER)")
            connection.execute("INSERT INTO two_view_geometries VALUES (12)")
            connection.commit()
            connection.close()
        if command[1] == "mapper":
            model = Path(command[command.index("--output_path") + 1]) / "0"
            model.mkdir(parents=True)
            for filename in ("cameras.bin", "images.bin", "points3D.bin"):
                (model / filename).write_bytes(b"model")
        if command[1] == "model_converter":
            output = Path(command[command.index("--output_path") + 1])
            if command[-1] == "TXT":
                output.mkdir(exist_ok=True)
                (output / "cameras.txt").write_text("1 SIMPLE_RADIAL 1600 900 1800 800 450 0\n")
                (output / "images.txt").write_text(
                    "1 1 0 0 0 0 0 0 1 a.jpg\n0 0 -1\n2 1 0 0 0 1 0 0 1 b.jpg\n0 0 -1\n"
                )
                (output / "points3D.txt").write_text("1 0 0 1 1 2 3 0.5 1 0 2 0\n")
            else:
                output.write_text("ply\nformat ascii 1.0\nelement vertex 1\nend_header\n0 0 0\n")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    report = run_experiment(images, tmp_path / "run", ExperimentConfig("mock"), executable="colmap", runner=runner)
    assert [cmd[1] for cmd in seen] == ["feature_extractor", "exhaustive_matcher", "mapper", "model_converter", "model_converter"]
    assert report["registered_images"] == 2
    assert report["points_3d"] == 1
    assert report["cameras"][0]["model"] == "SIMPLE_RADIAL"
    assert report["mean_track_length"] == 2
    assert json.loads((tmp_path / "run" / "experiment_report.json").read_text())["name"] == "mock"
