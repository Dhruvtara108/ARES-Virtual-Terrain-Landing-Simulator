from __future__ import annotations

import ast
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image


NOTEBOOK = Path(__file__).parents[1] / "notebooks" / "ares_hloc_reconstruction.ipynb"


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def helpers(notebook: dict) -> dict:
    cell = next(
        cell for cell in notebook["cells"]
        if cell["cell_type"] == "code" and "def safe_extract_image_zip" in "".join(cell["source"])
    )
    namespace: dict = {}
    exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), namespace)
    return namespace


def make_zip(path: Path, count: int = 22, *, duplicate: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(count):
            image_path = path.parent / f"image-{index:02}.png"
            color = (index, 100, 200) if not duplicate or index == 0 else (0, 100, 200)
            Image.new("RGB", (64, 48), color).save(image_path)
            archive.write(image_path, f"corridor/{image_path.name}")


def test_notebook_json_and_task_pipeline(notebook: dict) -> None:
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] >= 4
    assert len(notebook["cells"]) >= 10
    code = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"] if cell["cell_type"] == "code")
    for required in (
        "torch.cuda.is_available()", "files.upload()", "safe_extract_image_zip", "validate_feature_preprocessing",
        "superpoint_max", "superpoint+lightglue", "pairs_from_exhaustive.main",
        "reconstruction.main", "CameraMode.SINGLE", "skip_geometric_verification=False",
        "ba_refine_focal_length", "export_PLY", "reconstruction_report.json",
        "files.download", "camera_positions", "median_reprojection_error_px",
    ):
        assert required in code
    assert all(cell.get("execution_count") is None and not cell.get("outputs") for cell in notebook["cells"] if cell["cell_type"] == "code")
    ast.parse(code)


def test_zip_validation_and_deterministic_image_order(tmp_path: Path, helpers: dict) -> None:
    archive = tmp_path / "photos.zip"
    make_zip(archive)
    names = helpers["safe_extract_image_zip"](archive, tmp_path / "images")
    assert len(names) == 22
    assert names == sorted(names)
    assert names[0] == "corridor/image-00.png"
    assert (tmp_path / "images" / names[-1]).is_file()


def test_zip_rejects_wrong_count_duplicate_and_traversal(tmp_path: Path, helpers: dict) -> None:
    wrong_count = tmp_path / "few.zip"
    make_zip(wrong_count, count=3)
    with pytest.raises(ValueError, match="Expected 22"):
        helpers["safe_extract_image_zip"](wrong_count, tmp_path / "few")

    duplicate = tmp_path / "duplicate.zip"
    make_zip(duplicate, duplicate=True)
    with pytest.raises(ValueError, match="Duplicate image contents"):
        helpers["safe_extract_image_zip"](duplicate, tmp_path / "duplicate")

    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.png", b"not extracted")
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        helpers["safe_extract_image_zip"](traversal, tmp_path / "unsafe")
    assert not (tmp_path.parent / "escape.png").exists()


def test_output_paths_and_report_generation(tmp_path: Path, helpers: dict) -> None:
    paths = helpers["create_output_paths"](tmp_path / "ares_hloc_outputs")
    assert set(paths) == {"features", "matches", "reconstruction", "sparse"}
    assert all(path.is_dir() for path in paths.values())
    assert (paths["sparse"] / "0").is_dir()
    assert helpers["validate_feature_preprocessing"]({
        "model": {"name": "superpoint", "max_keypoints": 4096},
        "preprocessing": {"grayscale": True, "resize_max": 1600},
    }) == {"grayscale": True, "resize_max": 1600, "max_keypoints": 4096}
    with pytest.raises(ValueError, match="1600 px"):
        helpers["validate_feature_preprocessing"]({
            "model": {"name": "superpoint", "max_keypoints": 4096},
            "preprocessing": {"grayscale": True, "resize_max": 1024},
        })

    camera = SimpleNamespace(camera_id=1, model=SimpleNamespace(name="SIMPLE_RADIAL"), width=1600, height=900, params=[1920, 800, 450, 0])
    images = {
        1: SimpleNamespace(name="a.jpg", projection_center=lambda: [0, 0, 0]),
        2: SimpleNamespace(name="b.jpg", projection_center=lambda: [1, 0, 0]),
    }
    points = {
        1: SimpleNamespace(error=0.2, track=SimpleNamespace(length=lambda: 2)),
        2: SimpleNamespace(error=0.4, track=SimpleNamespace(length=lambda: 3)),
    }
    model = SimpleNamespace(reg_image_ids=lambda: [1, 2], images=images, cameras={1: camera}, points3D=points)
    report = helpers["build_reconstruction_report"](
        model, ["a.jpg", "b.jpg", "c.jpg"], {"registered_images": 4}, False, [1920, 800, 450, 0]
    )
    assert report["registered_images"] == 2
    assert report["unregistered_images"] == ["c.jpg"]
    assert report["points_3d"] == 2
    assert report["mean_reprojection_error_px"] == pytest.approx(0.3)
    assert report["median_reprojection_error_px"] == pytest.approx(0.3)
    assert report["mean_track_length"] == pytest.approx(2.5)
    assert report["cameras"][0]["calibration_refined"] is False
    assert report["camera_positions"][1]["x"] == 1.0

    report_path = helpers["save_reconstruction_report"](report, paths["reconstruction"] / "reconstruction_report.json")
    saved = json.loads(report_path.read_text())
    assert saved["points_3d"] == 2


def test_reconstruction_report_handles_no_model(tmp_path: Path, helpers: dict) -> None:
    report = helpers["build_reconstruction_report"](None, ["one.jpg"], {}, False, [1920, 800, 450, 0])
    assert report["registered_images"] == 0
    assert report["unregistered_images"] == ["one.jpg"]
    assert report["mean_reprojection_error_px"] is None
    assert report["camera_positions"] == []
