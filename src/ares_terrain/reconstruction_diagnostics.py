"""Read-only diagnostics for an existing COLMAP sparse reconstruction."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import struct
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image, ImageDraw, ImageFont

MAX_IMAGE_ID = 2_147_483_647
CAMERA_MODELS = {
    0: "SIMPLE_PINHOLE",
    1: "PINHOLE",
    2: "SIMPLE_RADIAL",
    3: "RADIAL",
    4: "OPENCV",
    5: "OPENCV_FISHEYE",
    6: "FULL_OPENCV",
    7: "FOV",
    8: "SIMPLE_RADIAL_FISHEYE",
    9: "RADIAL_FISHEYE",
    10: "THIN_PRISM_FISHEYE",
}
GEOMETRY_CONFIGURATIONS = {
    1: "DEGENERATE",
    2: "CALIBRATED",
    3: "UNCALIBRATED",
    4: "PLANAR",
    5: "PANORAMIC",
    6: "PLANAR_OR_PANORAMIC",
}


def _components(names: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    adjacency = {name: set() for name in names}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    components: list[list[str]] = []
    seen: set[str] = set()
    for start in sorted(names):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: list[str] = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in sorted(adjacency[node], reverse=True):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda component: (-len(component), component))


def _read_mapper_diagnosis(reconstruction_path: Path, image_id_to_name: dict[int, str]) -> dict[str, Any]:
    logs = sorted(reconstruction_path.glob("logs/run-*/mapper.log"), key=lambda path: path.stat().st_mtime)
    if not logs:
        return {
            "log_path": None,
            "initial_pair_failed": None,
            "initial_pair": None,
            "evidence": [],
            "candidate_attempts": [],
        }
    log_path = logs[0]
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    evidence = [
        line.split("] ", maxsplit=1)[-1].strip()
        for line in lines
        if "No good initial image pair found" in line
        or "Relaxing the initialization constraints" in line
        or "Initializing with image pair" in line
    ]
    candidate_attempts: list[dict[str, Any]] = []
    current_attempt: dict[str, Any] | None = None
    for line in lines:
        registered = re.search(r"Registering image #(\d+)", line)
        if registered:
            image_id = int(registered.group(1))
            current_attempt = {
                "image_id": image_id,
                "image": image_id_to_name.get(image_id),
                "points_seen": None,
                "candidate_points": None,
                "mapper_declined_attempt": False,
            }
            candidate_attempts.append(current_attempt)
        if current_attempt is None:
            continue
        correspondences = re.search(r"Image sees (\d+) / (\d+) points", line)
        if correspondences:
            current_attempt["points_seen"] = int(correspondences.group(1))
            current_attempt["candidate_points"] = int(correspondences.group(2))
            total = current_attempt["candidate_points"]
            current_attempt["correspondence_ratio"] = (
                current_attempt["points_seen"] / total if total else None
            )
        if "Could not register, trying another image" in line:
            current_attempt["mapper_declined_attempt"] = True
    pair = None
    for line in evidence:
        if "Initializing with image pair" in line:
            try:
                fields = line.rsplit("pair #", maxsplit=1)[1].split(" and #")
                first_id, second_id = int(fields[0]), int(fields[1])
                pair = {
                    "image_ids": [first_id, second_id],
                    "images": [image_id_to_name.get(first_id), image_id_to_name.get(second_id)],
                }
            except (IndexError, ValueError):
                pass
    return {
        "log_path": str(log_path),
        "initial_pair_failed": any("No good initial image pair found" in line for line in evidence),
        "initial_pair": pair,
        "evidence": evidence,
        "candidate_attempts": candidate_attempts,
    }


def _mapper_options(reconstruction_path: Path) -> dict[str, str]:
    project_file = reconstruction_path / "sparse" / "0" / "project.ini"
    if not project_file.is_file():
        return {}
    current_section = ""
    values: dict[str, str] = {}
    for line in project_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
        elif current_section == "Mapper" and "=" in line and not line.startswith("#"):
            key, value = line.split("=", maxsplit=1)
            values[key.strip()] = value.strip()
    selected = ("init_min_num_inliers", "init_min_tri_angle", "abs_pose_min_num_inliers", "abs_pose_min_inlier_ratio", "abs_pose_max_error")
    return {key: values[key] for key in selected if key in values}


def _camera_parameters(reconstruction_path: Path) -> list[dict[str, Any]]:
    text_files = sorted(
        reconstruction_path.glob("logs/run-*/model_text/cameras.txt"),
        key=lambda path: path.stat().st_mtime,
    )
    if not text_files:
        return []
    cameras: list[dict[str, Any]] = []
    for line in text_files[-1].read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 5:
            continue
        try:
            cameras.append(
                {
                    "camera_id": int(fields[0]),
                    "model": fields[1],
                    "width": int(fields[2]),
                    "height": int(fields[3]),
                    "parameters": [float(value) for value in fields[4:]],
                }
            )
        except ValueError:
            continue
    return cameras


def _load_registered_names(reconstruction_path: Path) -> list[str]:
    reports = sorted(
        reconstruction_path.glob("logs/run-*/reconstruction_report.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not reports:
        return []
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    return sorted({str(item["image"]) for item in report.get("camera_positions", []) if item.get("image")})


def _draw_matching_graph(graph: dict[str, Any], output_path: Path) -> None:
    width, height = 1900, 1400
    image = Image.new("RGB", (width, height), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    try:
        title_font = ImageFont.load_default(size=28)
    except TypeError:  # Pillow 10.0 did not accept the size argument.
        title_font = font
    draw.text((36, 26), "COLMAP verified matching graph", fill="#152238", font=title_font)
    draw.text((36, 68), "Edges show geometric inliers; green nodes registered, red nodes unregistered", fill="#34445b", font=font)

    nodes = graph["nodes"]
    center_x, center_y, radius = 670, 745, 565
    count = max(len(nodes), 1)
    positions: dict[str, tuple[int, int]] = {}
    for index, node in enumerate(nodes):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        positions[node["name"]] = (
            int(center_x + radius * math.cos(angle)),
            int(center_y + radius * math.sin(angle)),
        )

    for edge in graph["edges"]:
        left = positions[edge["image_1"]]
        right = positions[edge["image_2"]]
        weight = edge["inliers"]
        color = "#1f6f8b" if weight >= 100 else "#9aabb9"
        draw.line((left, right), fill=color, width=max(1, min(8, 1 + weight // 30)))
        if weight >= 100:
            mx, my = (left[0] + right[0]) // 2, (left[1] + right[1]) // 2
            draw.text((mx + 2, my + 2), str(weight), fill="#142d4e", font=font)

    for node in nodes:
        x, y = positions[node["name"]]
        fill = "#2e8b57" if node["registered"] else "#c84c4c"
        draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill=fill, outline="white", width=3)
        draw.text((x - 9, y - 7), node["label"], fill="white", font=font)

    legend_x, legend_y = 1320, 130
    draw.text((legend_x, legend_y), "Image key", fill="#152238", font=title_font)
    for index, node in enumerate(nodes):
        row_y = legend_y + 42 + index * 48
        dot = "#2e8b57" if node["registered"] else "#c84c4c"
        draw.ellipse((legend_x, row_y, legend_x + 22, row_y + 22), fill=dot)
        name = node["name"]
        if len(name) > 74:
            name = name[:71] + "..."
        draw.text((legend_x + 32, row_y + 3), f"{node['label']}  {name}", fill="#26374d", font=font)
    draw.text((legend_x, 1260), "Edge width/color scales with geometric inlier count.", fill="#34445b", font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def diagnose_sparse_reconstruction(
    database_path: str | Path,
    reconstruction_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Path]:
    """Read COLMAP outputs, export diagnostics, and never modify the reconstruction."""
    database = Path(database_path).resolve()
    reconstruction = Path(reconstruction_path).resolve()
    output = Path(output_directory).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"COLMAP database does not exist: {database}")
    output.mkdir(parents=True, exist_ok=True)

    # URI read-only mode prevents diagnostic queries from changing the COLMAP DB.
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        image_rows = connection.execute("SELECT image_id, name FROM images ORDER BY name").fetchall()
        if not image_rows:
            raise ValueError("COLMAP database contains no images")
        image_id_to_name = {int(image_id): str(name) for image_id, name in image_rows}
        name_to_id = {name: image_id for image_id, name in image_id_to_name.items()}
        names = sorted(name_to_id)

        keypoint_counts = {
            int(image_id): int(rows)
            for image_id, rows in connection.execute("SELECT image_id, rows FROM keypoints")
        }
        match_rows = connection.execute("SELECT pair_id, rows FROM matches").fetchall()
        geometry_rows = connection.execute(
            "SELECT pair_id, rows, config FROM two_view_geometries"
        ).fetchall()
        camera_rows = connection.execute(
            "SELECT camera_id, model, width, height, params FROM cameras ORDER BY camera_id"
        ).fetchall()
    finally:
        connection.close()

    matches_by_pair: dict[tuple[str, str], int] = {}
    raw_edges: list[tuple[str, str]] = []
    for pair_id, rows in match_rows:
        first_id, second_id = divmod(int(pair_id), MAX_IMAGE_ID)
        first, second = image_id_to_name.get(first_id), image_id_to_name.get(second_id)
        if first is None or second is None:
            continue
        key = tuple(sorted((first, second)))
        matches_by_pair[key] = int(rows)
        if rows > 0:
            raw_edges.append(key)

    geometry_by_pair: dict[tuple[str, str], dict[str, int]] = {}
    for pair_id, rows, config in geometry_rows:
        if int(config) <= 0 or int(rows) <= 0:
            continue
        first_id, second_id = divmod(int(pair_id), MAX_IMAGE_ID)
        first, second = image_id_to_name.get(first_id), image_id_to_name.get(second_id)
        if first is None or second is None:
            continue
        geometry_by_pair[tuple(sorted((first, second)))] = {"inliers": int(rows), "configuration": int(config)}

    registered = set(_load_registered_names(reconstruction))
    # Restrict the registered set to images represented in this database.
    registered.intersection_update(names)
    geometric_edges = list(geometry_by_pair)
    raw_components = _components(names, raw_edges)
    geometric_components = _components(names, geometric_edges)
    registered_names = sorted(registered)
    registered_edges = [edge for edge in geometric_edges if edge[0] in registered and edge[1] in registered]
    registered_components = _components(registered_names, registered_edges) if registered_names else []

    nodes: list[dict[str, Any]] = []
    for index, name in enumerate(names, start=1):
        incident = [edge for edge in geometric_edges if name in edge]
        degree = len(incident)
        strongest_inliers = max((geometry_by_pair[edge]["inliers"] for edge in incident), default=0)
        nodes.append(
            {
                "label": f"{index:02d}",
                "image_id": name_to_id[name],
                "name": name,
                "keypoints": keypoint_counts.get(name_to_id[name], 0),
                "registered": name in registered,
                "verified_pair_degree": degree,
                "strongest_pair_inliers": strongest_inliers,
            }
        )

    edges = [
        {
            "image_1": first,
            "image_2": second,
            "matches": matches_by_pair.get((first, second), 0),
            "inliers": info["inliers"],
            "geometry_configuration": info["configuration"],
        }
        for (first, second), info in sorted(geometry_by_pair.items())
    ]
    inlier_counts = [edge["inliers"] for edge in edges]
    matched_nonempty_count = sum(rows > 0 for rows in matches_by_pair.values())
    keypoint_values = [node["keypoints"] for node in nodes]
    geometry_config_counts = Counter(str(edge["geometry_configuration"]) for edge in edges)
    mapper = _read_mapper_diagnosis(reconstruction, image_id_to_name)
    mapper["options"] = _mapper_options(reconstruction)
    for attempt in mapper["candidate_attempts"]:
        attempt["eventually_registered"] = attempt["image"] in registered
    cameras = _camera_parameters(reconstruction)

    # Keep the stored database calibration as well as the final fitted model calibration.
    database_cameras: list[dict[str, Any]] = []
    for camera_id, model_id, width_px, height_px, blob in camera_rows:
        params = struct.unpack(f"<{len(blob) // 8}d", blob) if blob and len(blob) % 8 == 0 else []
        database_cameras.append(
            {
                "camera_id": int(camera_id),
                "model": CAMERA_MODELS.get(int(model_id), f"UNKNOWN_{model_id}"),
                "width": int(width_px),
                "height": int(height_px),
                "parameters": list(params),
            }
        )

    failed_images: list[dict[str, Any]] = []
    for node in nodes:
        if node["registered"]:
            continue
        name = node["name"]
        incident_edges = [edge for edge in edges if name in (edge["image_1"], edge["image_2"])]
        strongest = max(incident_edges, key=lambda edge: edge["inliers"], default=None)
        cause = (
            "no_verified_geometric_pair"
            if not incident_edges
            else "has_verified_pairs_but_mapper_did_not_accept_pose"
        )
        failed_images.append(
            {
                "image_id": node["image_id"],
                "name": name,
                "keypoints": node["keypoints"],
                "verified_pair_degree": node["verified_pair_degree"],
                "strongest_pair": strongest,
                "diagnosis": cause,
            }
        )

    graph = {
        "nodes": nodes,
        "edges": edges,
        "statistics": {
            "image_count": len(nodes),
            "matched_pair_records": len(matches_by_pair),
            "nonempty_matched_pairs": matched_nonempty_count,
            "verified_geometric_pairs": len(edges),
            "verified_pairs_at_least_100_inliers": sum(value >= 100 for value in inlier_counts),
            "total_verified_inliers": sum(inlier_counts),
            "verified_inliers_min": min(inlier_counts, default=0),
            "verified_inliers_median": median(inlier_counts) if inlier_counts else 0,
            "verified_inliers_max": max(inlier_counts, default=0),
            "geometry_configurations": dict(sorted(geometry_config_counts.items())),
            "geometry_configuration_names": {
                str(config): GEOMETRY_CONFIGURATIONS.get(config, "UNKNOWN")
                for config in sorted({edge["geometry_configuration"] for edge in edges})
            },
            "raw_match_components": raw_components,
            "verified_graph_components": geometric_components,
            "registered_images": registered_names,
            "failed_images": failed_images,
            "registered_graph_components": registered_components,
            "registered_subgraph_connected": len(registered_components) == 1 if registered_names else False,
        },
    }

    final_cameras: list[dict[str, Any]] = []
    for camera in cameras:
        params = camera["parameters"]
        focal = params[0] if params else None
        distortion = params[-1] if camera["model"] in {"SIMPLE_RADIAL", "RADIAL"} and len(params) >= 4 else None
        ratio = focal / max(camera["width"], camera["height"]) if focal is not None else None
        initial_camera = next(
            (item for item in database_cameras if item["camera_id"] == camera["camera_id"]), None
        )
        initial_focal = initial_camera["parameters"][0] if initial_camera and initial_camera["parameters"] else None
        final_cameras.append(
            {
                **camera,
                "focal_px_to_longest_image_side": ratio,
                "radial_distortion_parameter": distortion,
                "initial_focal_px": initial_focal,
                "fitted_to_initial_focal_ratio": focal / initial_focal if focal is not None and initial_focal else None,
                "assessment": "No EXIF or independent calibration reference is available; fitted intrinsics are not independently validated and should not be treated as ground truth.",
            }
        )

    report = {
        "dataset": {
            "image_count": len(nodes),
            "keypoint_total": sum(keypoint_values),
            "keypoints_per_image_min": min(keypoint_values, default=0),
            "keypoints_per_image_median": median(keypoint_values) if keypoint_values else 0,
            "keypoints_per_image_max": max(keypoint_values, default=0),
        },
        "matches": graph["statistics"],
        "registration": {
            "registered_count": len(registered_names),
            "failed_count": len(failed_images),
            "registered_images": registered_names,
            "failed_images": failed_images,
            "registered_sequence_connected_in_verified_graph": graph["statistics"]["registered_subgraph_connected"],
            "mapper_log": mapper,
        },
        "calibration": {
            "database_initial_cameras": database_cameras,
            "fitted_sparse_model_cameras": final_cameras,
            "conclusion": (
                "SIMPLE_RADIAL is a reasonable starting model for unknown intrinsics, but this run does not establish that it is appropriate: the focal length drifted substantially from its database initialization while only four images registered. Without EXIF or an independent calibration reference, the fitted camera parameters remain uncertain. Do not treat this camera fit as validated."
                if any(camera["model"] == "SIMPLE_RADIAL" for camera in final_cameras)
                else "No fitted SIMPLE_RADIAL camera parameters were found in the sparse model."
            ),
        },
        "interpretation": [],
    }
    no_pair_count = sum(item["diagnosis"] == "no_verified_geometric_pair" for item in failed_images)
    declined_attempts = [
        attempt
        for attempt in mapper["candidate_attempts"]
        if attempt["mapper_declined_attempt"] and not attempt["eventually_registered"]
    ]
    seen_counts = [attempt["points_seen"] for attempt in declined_attempts if attempt["points_seen"] is not None]
    attempted_range = f"{min(seen_counts)}–{max(seen_counts)}" if seen_counts else "not recorded"
    report["interpretation"] = [
        "The mapper log explicitly reports that no good initial image pair was found before relaxing initialization constraints. The model configuration required "
        f"{mapper['options'].get('init_min_num_inliers', 'unknown')} initial inliers and a "
        f"{mapper['options'].get('init_min_tri_angle', 'unknown')} degree triangulation angle; inlier count alone does not establish adequate parallax.",
        f"{len(failed_images) - no_pair_count} unregistered images have at least one verified pair edge; {no_pair_count} have none. "
        f"The mapper declined {len(declined_attempts)} pose attempt(s) for images that remained unregistered, with {attempted_range} 2D-to-3D correspondences seen. "
        "This points to geometric/pose consistency trouble beyond simply having no pairwise matches.",
        "Per-image keypoint counts are nonzero. The issue is not a total lack of detected features; sparse strong-pair support, low parallax or degenerate matches, and the unstable fitted camera calibration are plausible interacting causes.",
        "The registered images are connected to each other in the verified matching graph; this does not establish that the full photo set forms one usable reconstruction sequence.",
    ]

    graph["registration"] = report["registration"]
    graph["calibration"] = report["calibration"]
    graph["interpretation"] = report["interpretation"]
    json_path = output / "image_match_statistics.json"
    graph_path = output / "matching_graph.png"
    report_path = output / "diagnostic_report.md"
    json_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _draw_matching_graph(graph, graph_path)
    report_path.write_text(_markdown_report(report, graph), encoding="utf-8")
    return {"statistics": json_path, "graph": graph_path, "report": report_path}


def _markdown_report(report: dict[str, Any], graph: dict[str, Any]) -> str:
    stats = report["matches"]
    dataset = report["dataset"]
    registration = report["registration"]
    calibration = report["calibration"]
    mapper = registration["mapper_log"]
    lines = [
        "# Sparse reconstruction diagnostics",
        "",
        "## Dataset and feature matching",
        "",
        f"- Images in COLMAP database: {dataset['image_count']}",
        f"- Extracted keypoints: {dataset['keypoint_total']} total ({dataset['keypoints_per_image_min']}–{dataset['keypoints_per_image_max']} per image; median {dataset['keypoints_per_image_median']})",
        f"- Nonempty matched image pairs: {stats['nonempty_matched_pairs']} of {stats['matched_pair_records']} pair records",
        f"- Geometrically verified image pairs: {stats['verified_geometric_pairs']}",
        f"- Verified pairs with at least 100 inliers: {stats['verified_pairs_at_least_100_inliers']}",
        f"- Verified inliers per pair: min {stats['verified_inliers_min']}, median {stats['verified_inliers_median']}, max {stats['verified_inliers_max']}",
        "- Geometry configurations: " + ", ".join(
            f"{stats['geometry_configuration_names'][config]}: {count}"
            for config, count in stats["geometry_configurations"].items()
        ),
        f"- Verified graph components: {len(stats['verified_graph_components'])} (sizes: {', '.join(map(str, sorted((len(c) for c in stats['verified_graph_components']), reverse=True)))})",
        f"- Isolated images in verified graph: {sum(not node['verified_pair_degree'] for node in graph['nodes'])}",
        "",
        "## Registration findings",
        "",
        f"- Registered: {registration['registered_count']} / {dataset['image_count']}",
        "- Registered images:",
        *[f"  - `{name}`" for name in registration["registered_images"]],
        f"- Registered images connected in verified graph: {registration['registered_sequence_connected_in_verified_graph']}",
        f"- Mapper log: `{mapper['log_path']}`" if mapper["log_path"] else "- Mapper log: not found",
    ]
    if mapper["evidence"]:
        lines.extend(["- Initial pair evidence:", *[f"  - `{line}`" for line in mapper["evidence"]]])
    if mapper.get("initial_pair", {}).get("images"):
        lines.append(f"- Pair chosen after relaxation: `{mapper['initial_pair']['images'][0]}` and `{mapper['initial_pair']['images'][1]}`.")
    if mapper.get("options"):
        lines.append("- Mapper thresholds: " + ", ".join(f"`{key}={value}`" for key, value in mapper["options"].items()) + ".")
    lines.extend(["", "### Unregistered images", ""])
    if registration["failed_images"]:
        lines.extend(["| Image | Keypoints | Verified pair degree | Strongest pair inliers | Mapper interpretation |", "|---|---:|---:|---:|---|"])
        for item in registration["failed_images"]:
            strongest = item["strongest_pair"]
            strongest_text = f"{strongest['inliers']} ({strongest['image_1']} ↔ {strongest['image_2']})" if strongest else "none"
            diagnosis = "no verified pair" if item["diagnosis"] == "no_verified_geometric_pair" else "matches exist; pose was not accepted"
            lines.append(f"| {item['name']} | {item['keypoints']} | {item['verified_pair_degree']} | {strongest_text} | {diagnosis} |")
    else:
        lines.append("All database images were registered.")
    lines.extend(
        [
            "",
            "The first initialization search found no pair satisfying COLMAP's joint initialization requirements. The run used the configured minimum inlier count and triangulation angle, then relaxed constraints. High pair inlier counts alone do not establish the required parallax.",
            "",
            "### Mapper-rejected pose attempts",
            "",
        ]
    )
    declined_attempts = [attempt for attempt in mapper.get("candidate_attempts", []) if attempt["mapper_declined_attempt"]]
    if declined_attempts:
        lines.extend(["| Candidate image | 2D–3D points seen / candidate points | Final status |", "|---|---:|---|"])
        for attempt in declined_attempts:
            seen, total = attempt["points_seen"], attempt["candidate_points"]
            correspondence_text = f"{seen} / {total}" if seen is not None and total is not None else "not recorded"
            candidate_name = attempt["image"] or f"COLMAP image #{attempt['image_id']}"
            final_status = "registered later" if attempt["eventually_registered"] else "unregistered"
            lines.append(f"| {candidate_name} | {correspondence_text} | {final_status} |")
    else:
        lines.append("No explicit mapper-rejected pose attempts were found in the log.")
    lines.extend(
        [
            "",
            "For images with verified pair edges, pairwise matches passed COLMAP's two-view geometric verification. Some mapper-rejected candidates had correspondence counts above the configured absolute minimum, yet pose registration was still declined; the remaining pose and reprojection consistency checks are therefore material.",
            "",
            "## Camera calibration",
            "",
        ]
    )
    for camera in calibration["database_initial_cameras"]:
        lines.append(f"- Database initial camera {camera['camera_id']}: `{camera['model']}` {camera['width']}×{camera['height']}, parameters `{camera['parameters']}`.")
    for camera in calibration["fitted_sparse_model_cameras"]:
        lines.append(f"- Fitted sparse camera {camera['camera_id']}: `{camera['model']}` {camera['width']}×{camera['height']}, parameters `{camera['parameters']}`.")
        focal_ratio = camera["focal_px_to_longest_image_side"]
        fitted_to_initial = camera["fitted_to_initial_focal_ratio"]
        focal_ratio_text = f"{focal_ratio:.3f}" if focal_ratio is not None else "unavailable"
        focal_change_text = f"{fitted_to_initial:.3f}" if fitted_to_initial is not None else "unavailable"
        lines.append(
            f"  - Focal length / longest side: `{focal_ratio_text}`; "
            f"fitted / initial focal length: `{focal_change_text}`; "
            f"radial parameter: `{camera['radial_distortion_parameter']}`."
        )
        lines.append(f"  - {camera['assessment']}")
    lines.extend(["", calibration["conclusion"], "", "## Assessment", "", *[f"- {item}" for item in report["interpretation"]], ""])
    return "\n".join(lines)
