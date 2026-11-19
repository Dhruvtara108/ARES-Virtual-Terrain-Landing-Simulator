"""Command line interface for ARES terrain input tools."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .image_validation import validate_images
from .image_inspection import inspect_image_set, write_manifest
from .sparse_reconstruction import ReconstructionError, run_sparse_reconstruction
from .reconstruction_diagnostics import diagnose_sparse_reconstruction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ares-terrain")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-images", help="validate image files for reconstruction")
    validate.add_argument("--input", required=True, help="image file or directory of images")
    inspect = commands.add_parser("inspect-image-set", help="inspect images and write a dataset manifest")
    inspect.add_argument("--input", required=True, help="image file or directory of images")
    inspect.add_argument("--output", required=True, help="path for the JSON manifest")
    reconstruct = commands.add_parser("reconstruct-sparse", help="run CPU sparse reconstruction with COLMAP")
    reconstruct.add_argument("--input", required=True, help="directory containing terrain photographs")
    reconstruct.add_argument("--output", required=True, help="reconstruction workspace directory")
    reconstruct.add_argument("--camera-mode", choices=("single", "per-image"), default="single")
    diagnose = commands.add_parser("diagnose-sparse", help="analyze COLMAP matches, registration, and calibration")
    diagnose.add_argument("--reconstruction", required=True, help="existing COLMAP reconstruction workspace")
    diagnose.add_argument("--output", required=True, help="directory for diagnostic JSON, PNG, and Markdown")
    args = parser.parse_args(argv)

    if args.command == "reconstruct-sparse":
        try:
            result = run_sparse_reconstruction(args.input, args.output, args.camera_mode)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        except (ReconstructionError, ValueError, OSError) as exc:
            print(f"Sparse reconstruction failed: {exc}", file=sys.stderr)
            return 1

        report = result.report
        print(f"Total input photographs: {report['input_photographs']}")
        print(f"Registered photographs: {report['registered_photographs']}")
        print(f"Unregistered photographs: {report['unregistered_photographs']}")
        print(f"Cameras: {report['cameras']}")
        print(f"Reconstructed 3D points: {report['points_3d']}")
        print(f"Sparse model: {report['sparse_model_path']}")
        print(f"PLY point cloud: {report['ply_path']}")
        print(f"Processing time: {report['processing_seconds']} seconds")
        print(f"Camera positions: {len(report['camera_positions'])}")
        print(f"Statistics report: {result.report_path}")
        for warning in report["warnings"]:
            print(f"Warning: {warning}")
        print(f"Overall reconstruction result: {report['result_status']}")
        return 0

    if args.command == "diagnose-sparse":
        try:
            outputs = diagnose_sparse_reconstruction(
                Path(args.reconstruction) / "database.db", args.reconstruction, args.output
            )
        except (FileNotFoundError, ValueError, OSError, sqlite3.Error) as exc:
            print(f"Sparse diagnostics failed: {exc}", file=sys.stderr)
            return 1
        print(f"Image statistics: {outputs['statistics']}")
        print(f"Matching graph: {outputs['graph']}")
        print(f"Diagnostic report: {outputs['report']}")
        return 0

    if args.command == "inspect-image-set":
        try:
            inspection = inspect_image_set(args.input)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"Inspection failed: {exc}", file=sys.stderr)
            return 1
        try:
            output_path = write_manifest(inspection.manifest, args.output)
        except OSError as exc:
            print(f"Invalid output path: {exc}", file=sys.stderr)
            return 2

        summary = inspection.manifest["summary"]
        images = inspection.manifest["images"]
        camera_available = sum(bool(image["camera_manufacturer"] and image["camera_model"]) for image in images)
        focal_available = sum(image["focal_length_mm"] is not None for image in images)
        print(f"Total files discovered: {inspection.total_files}")
        print(f"Valid images: {summary['valid_images']}")
        print(f"Unique images: {summary['unique_images']}")
        print(f"Duplicate images: {summary['duplicate_images']}")
        print(f"Camera manufacturer/model available: {camera_available}/{len(images)}")
        print(f"Focal length available: {focal_available}/{len(images)}")
        for warning in inspection.manifest["warnings"]:
            print(f"Warning: {warning}")
        print(f"Manifest: {output_path}")
        result = summary["unique_images"] >= 2
        print(f"Overall inspection result: {'PASS' if result else 'FAIL'}")
        return 0 if result else 1

    try:
        report = validate_images(args.input)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Input: {report.input_path}")
    print(f"Total files discovered: {report.total_files}")
    print(f"Valid images: {len(report.accepted)}")
    for image in report.accepted:
        print(f"  ACCEPTED {image.path} — {image.width}x{image.height}")
    print(f"Invalid images: {len(report.rejected)}")
    for image in report.rejected:
        print(f"  REJECTED {image.path} — {image.error}")
    for warning in report.warnings:
        print(f"Warning: {warning}")
    result = "PASS" if report.is_valid else "FAIL"
    print(f"Overall validation result: {result}")
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
