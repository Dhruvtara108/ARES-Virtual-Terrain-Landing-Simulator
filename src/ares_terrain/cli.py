"""Command line interface for ARES terrain input tools."""

from __future__ import annotations

import argparse
import sys

from .image_validation import validate_images
from .image_inspection import inspect_image_set, write_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ares-terrain")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-images", help="validate image files for reconstruction")
    validate.add_argument("--input", required=True, help="image file or directory of images")
    inspect = commands.add_parser("inspect-image-set", help="inspect images and write a dataset manifest")
    inspect.add_argument("--input", required=True, help="image file or directory of images")
    inspect.add_argument("--output", required=True, help="path for the JSON manifest")
    args = parser.parse_args(argv)

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
