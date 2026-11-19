from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from pathlib import Path

import pytest
from PIL import Image

from ares_terrain.reconstruction_diagnostics import MAX_IMAGE_ID, diagnose_sparse_reconstruction


def create_diagnostic_fixture(root: Path) -> Path:
    reconstruction = root / "reconstruction"
    reconstruction.mkdir(parents=True)
    database_path = reconstruction / "database.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE images(image_id INTEGER PRIMARY KEY, name TEXT, camera_id INTEGER);
        CREATE TABLE keypoints(image_id INTEGER PRIMARY KEY, rows INTEGER, cols INTEGER, data BLOB);
        CREATE TABLE matches(pair_id INTEGER PRIMARY KEY, rows INTEGER, cols INTEGER, data BLOB);
        CREATE TABLE two_view_geometries(pair_id INTEGER PRIMARY KEY, rows INTEGER, cols INTEGER, data BLOB, config INTEGER);
        CREATE TABLE cameras(camera_id INTEGER PRIMARY KEY, model INTEGER, width INTEGER, height INTEGER, params BLOB);
        """
    )
    names = {
        1: "photo_a.jpg",
        2: "photo_b.jpg",
        3: "photo_c.jpg",
        4: "photo_d.jpg",
        5: "photo_e.jpg",
    }
    for image_id, name in names.items():
        connection.execute("INSERT INTO images VALUES (?, ?, 1)", (image_id, name))
    for image_id, rows in ((1, 100), (2, 80), (3, 30), (4, 25), (5, 0)):
        connection.execute("INSERT INTO keypoints VALUES (?, ?, 4, X'')", (image_id, rows))

    def pair_id(first: int, second: int) -> int:
        return min(first, second) * MAX_IMAGE_ID + max(first, second)

    for first, second, rows in ((1, 2, 30), (2, 3, 0), (3, 4, 10)):
        connection.execute("INSERT INTO matches VALUES (?, ?, 2, X'')", (pair_id(first, second), rows))
    for first, second, rows, config in ((1, 2, 20, 3), (2, 3, 0, 0), (3, 4, 14, 6)):
        connection.execute(
            "INSERT INTO two_view_geometries VALUES (?, ?, 2, X'', ?)",
            (pair_id(first, second), rows, config),
        )
    connection.execute(
        "INSERT INTO cameras VALUES (1, 2, 64, 48, ?)",
        (struct.pack("<4d", 50.0, 32.0, 24.0, 0.0),),
    )
    connection.commit()
    connection.close()

    run_dir = reconstruction / "logs" / "run-1"
    model_text = run_dir / "model_text"
    model_text.mkdir(parents=True)
    (run_dir / "mapper.log").write_text(
        "=> No good initial image pair found.\n"
        "=> Relaxing the initialization constraints.\n"
        "Initializing with image pair #1 and #2\n"
        "Registering image #3 (3)\n"
        "=> Image sees 32 / 187 points\n"
        "=> Could not register, trying another image.\n",
        encoding="utf-8",
    )
    (reconstruction / "sparse" / "0").mkdir(parents=True)
    (reconstruction / "sparse" / "0" / "project.ini").write_text(
        "[Mapper]\ninit_min_num_inliers=100\ninit_min_tri_angle=16\n"
        "abs_pose_min_num_inliers=30\nabs_pose_min_inlier_ratio=0.25\nabs_pose_max_error=12\n",
        encoding="utf-8",
    )
    (model_text / "cameras.txt").write_text(
        "# camera data\n1 SIMPLE_RADIAL 64 48 150 32 24 -1.2\n",
        encoding="utf-8",
    )
    (run_dir / "reconstruction_report.json").write_text(
        json.dumps({"camera_positions": [{"image": "photo_a.jpg"}, {"image": "photo_b.jpg"}]}),
        encoding="utf-8",
    )
    return reconstruction


def test_diagnostics_report_counts_connectivity_registration_and_calibration(tmp_path: Path) -> None:
    reconstruction = create_diagnostic_fixture(tmp_path)
    db_path = reconstruction / "database.db"
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    outputs = diagnose_sparse_reconstruction(db_path, reconstruction, tmp_path / "diagnostics")

    graph = json.loads(outputs["statistics"].read_text(encoding="utf-8"))
    report = outputs["report"].read_text(encoding="utf-8")
    stats = graph["statistics"]
    assert stats["image_count"] == 5
    assert stats["nonempty_matched_pairs"] == 2
    assert stats["verified_geometric_pairs"] == 2
    assert stats["verified_pairs_at_least_100_inliers"] == 0
    assert [len(component) for component in stats["verified_graph_components"]] == [2, 2, 1]
    assert stats["registered_images"] == ["photo_a.jpg", "photo_b.jpg"]
    assert stats["registered_subgraph_connected"] is True
    failed = {item["name"]: item for item in stats["failed_images"]}
    assert failed["photo_c.jpg"]["diagnosis"] == "has_verified_pairs_but_mapper_did_not_accept_pose"
    assert failed["photo_e.jpg"]["diagnosis"] == "no_verified_geometric_pair"
    assert stats["geometry_configuration_names"] == {"3": "UNCALIBRATED", "6": "PLANAR_OR_PANORAMIC"}
    assert graph["registration"]["mapper_log"]["options"]["init_min_tri_angle"] == "16"
    assert graph["registration"]["mapper_log"]["candidate_attempts"][0]["points_seen"] == 32
    assert graph["calibration"]["fitted_sparse_model_cameras"][0]["radial_distortion_parameter"] == -1.2
    assert graph["calibration"]["fitted_sparse_model_cameras"][0]["fitted_to_initial_focal_ratio"] == 3.0
    assert graph["nodes"][0]["keypoints"] == 100
    assert "No good initial image pair found." in report
    assert "32 / 187" in report
    assert "init_min_tri_angle=16" in report
    assert "SIMPLE_RADIAL" in report
    assert "not independently validated" in report
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    with Image.open(outputs["graph"]) as graph_image:
        assert graph_image.format == "PNG"
        assert graph_image.size == (1900, 1400)


def test_diagnostics_reject_missing_database(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="database does not exist"):
        diagnose_sparse_reconstruction(tmp_path / "missing.db", tmp_path, tmp_path / "out")
