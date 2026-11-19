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

## Reconstruction recovery experiments

`src/ares_terrain/reconstruction_experiments.py` defines isolated, CPU-only
COLMAP experiments for the existing photo sequence. Each run has its own
database, logs, sparse model, text export, PLY, and JSON metrics under
`data/terrain_dataset/experiments/`. Run the matrix with:

```bash
python -c 'from pathlib import Path; from ares_terrain.reconstruction_experiments import EXPERIMENTS, run_experiment; root=Path("data/terrain_dataset/experiments"); root.mkdir(exist_ok=True); [run_experiment("data/terrain_dataset/raw", root/c.name, c) for c in EXPERIMENTS]'
```

The experiments compare exhaustive and sequential matching (three-image
overlap), a modest mapper threshold change, and `SIMPLE_RADIAL` versus
`SIMPLE_PINHOLE`. The experiment outputs are local artifacts and remain
excluded from Git. See `data/terrain_dataset/experiments/summary.md` for the
recorded comparison. The experiments currently do not yield a stable model
usable for dense reconstruction; the preserved baseline remains the strongest
sparse result.

### Path to a virtual environment

The sparse COLMAP model supplies camera poses and sparse landmarks only; it is
not a walkable surface or terrain mesh. Proceed only after obtaining a
geometrically stable, sufficiently overlapping reconstruction. Dense MVS would
then require image undistortion and PatchMatch stereo, followed by stereo
fusion to a dense cloud. This installed COLMAP 3.9.1 build reports that it was
compiled without CUDA and `patch_match_stereo` exits with a CUDA requirement,
so dense MVS cannot run in this environment. Mesh generation would need an
independent CPU capable mesher (or a CUDA enabled COLMAP build installed
elsewhere), then validation and hole handling. Texture generation would
project the original photographs onto that validated mesh. Only then should
the mesh and textures be exported to a Three.js scene, with a separately
specified rocket model, collision surface, coordinate scale, gravity, and
landing controls. No mesh or placeholder environment is generated here.

## HLoc learned-feature experiment in Google Colab

Open [`notebooks/ares_hloc_reconstruction.ipynb`](notebooks/ares_hloc_reconstruction.ipynb)
in Google Colab ([open this branch's notebook](https://colab.research.google.com/github/Dhruvtara108/ARES-Virtual-Terrain-Landing-Simulator/blob/feature/part-1-terrain-reconstruction/notebooks/ares_hloc_reconstruction.ipynb)). In Colab, select a GPU runtime, run cells from top to bottom, and upload the ready-made `data/terrain_dataset/ares_hloc_photos.zip` containing the existing 22 unique images. The ZIP is ignored by Git. The notebook follows the [official HLoc SfM notebook](https://github.com/cvg/Hierarchical-Localization/blob/master/pipeline_SfM.ipynb) and uses its upstream `extract_features.main`, `pairs_from_exhaustive.main`, `match_features.main`, and `reconstruction.main` interfaces with SuperPoint, LightGlue, and PyCOLMAP.

The notebook shares a SIMPLE_RADIAL camera and fixes its initial `[1920, 800, 450, 0]` parameters during bundle adjustment. The focal length is COLMAP's default heuristic, not an independently measured phone calibration. Results and the report are written to `/content/ares_hloc_outputs/`; the notebook displays sparse points and camera centers and offers `points3D.ply` for download. The PLY contains sparse landmarks, not a dense cloud or terrain mesh. Local pytest tests validate the notebook JSON, ZIP handling, output paths, deterministic image ordering, and report calculations without installing HLoc or PyTorch locally.
