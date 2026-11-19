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

Run tests with:

```bash
pytest
```
