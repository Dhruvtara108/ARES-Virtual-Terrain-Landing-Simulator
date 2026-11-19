"""Command line interface for ARES terrain input tools."""

from __future__ import annotations

import argparse
import sys

from .image_validation import validate_images


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ares-terrain")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-images", help="validate image files for reconstruction")
    validate.add_argument("--input", required=True, help="image file or directory of images")
    args = parser.parse_args(argv)

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
