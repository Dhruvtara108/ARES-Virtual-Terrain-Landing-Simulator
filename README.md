# ARES Virtual Terrain Landing Simulator

An AI-based virtual environment for terrain reconstruction and autonomous rocket landing.

## Project Components

1. **Terrain Reconstruction:** Convert images of real-world terrain into a 3D virtual environment.
2. **Rocket Simulator:** Build a physics-based simulation with terrain, obstacles, and landing zones.
3. **Rocket Intelligence:** Train a PPO reinforcement learning agent to autonomously land on suitable terrain.

## Project Status

Prototype development.

The current prototype validates overlapping terrain photographs before a
reconstruction workflow.

## Validate images

Requires Python 3.12 or newer. Install the project and development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Validate one image or a directory (including nested directories):

```bash
python -m ares_terrain.cli validate-images --input PATH_TO_IMAGES
```

JPG, JPEG, PNG, and WEBP images are decoded and checked for dimensions. The
command reports accepted and rejected files, and returns 0 when at least two
valid images are present, 1 when validation fails, or 2 for an invalid input
path. Approximately 20–30 overlapping photographs are recommended for the
intended reconstruction workflow. Original files are never modified.

## Inspect an image set

Create a JSON manifest with file hashes, image dimensions and format, selected
camera EXIF fields (when present), and duplicate groups:

```bash
python -m ares_terrain.cli inspect-image-set \
  --input PATH_TO_IMAGES \
  --output output/terrain-manifest.json
```

The command creates missing output directories and reports the discovered,
valid, unique, and duplicate image counts. Identical files are counted once
toward reconstruction readiness, but no files are deleted or changed. The
manifest omits GPS and capture timestamps. It recommends overlapping photos
and explicitly states that overlap has not been verified. Exit code 0 means
at least two unique valid images, 1 means inspection failed or there are fewer
than two unique images, and 2 means the input or output path is invalid.

Run tests with:

```bash
pytest
```

## Sparse COLMAP reconstruction

With COLMAP installed, run a CPU-only sparse reconstruction on a directory of
validated photographs:

```bash
python -m ares_terrain.cli reconstruct-sparse \
  --input data/terrain_dataset/raw \
  --output data/terrain_dataset/reconstruction \
  --camera-mode single
```

COLMAP runs SIFT extraction, exhaustive matching with geometric verification,
incremental mapping, model analysis, and sparse PLY export. The pipeline uses
`SIMPLE_RADIAL`, limits extraction and matching to four CPU threads, disables
GPU processing, and caps the longest image side at 1600 pixels. Camera mode
`single` shares calibration across images; `per-image` creates separate camera
calibrations. Databases, model files, point clouds, logs, and the statistics
report remain in the selected output directory. No dense reconstruction or
mesh is produced.

## Diagnose sparse matching and registration

Analyze an existing COLMAP workspace without changing its database or model:

```bash
python -m ares_terrain.cli diagnose-sparse \
  --reconstruction data/terrain_dataset/reconstruction \
  --output data/terrain_dataset/reconstruction/diagnostics
```

The command exports pair and keypoint statistics as JSON, a verified matching
graph as PNG, and a Markdown report covering registration and fitted camera
parameters. Outputs are generated locally under the ignored `data/` directory.
