# ARES 3D Rocket Landing Simulator

Standalone browser prototype using JavaScript ES modules, Three.js, and Vite. The scene is a deterministic procedural lunar-style test environment; it is not reconstructed from the hostel photographs.

## Run locally

```bash
cd simulator
npm install
npm run dev
```

Open the localhost URL printed by Vite. Use OrbitControls to orbit, pan, and zoom. `npm test` runs the deterministic physics and autonomous landing tests; `npm run build` creates the production bundle in `dist/`.

## Flight controls

- **Start autonomous landing** runs the PD guidance controller against the same fixed-step rigid-body model used by the tests.
- **Start manual mode** enables W/S throttle and arrow-key attitude controls.
- **Space** pauses or resumes. **R** resets. The camera-follow toggle tracks the rocket.

Keyboard events are ignored while an editable element has focus.

## Prototype physics assumptions

The vehicle is a point-mass translational model with a visual rigid rocket body. Gravity is 9.81 m/s², thrust is applied along the current pitch/roll orientation, propellant flow is proportional to throttle, and dry mass remains constant. Translation uses semi-implicit Euler integration at 1/120 s. The render loop caps frame delta and substeps to prevent long browser stalls from destabilizing the simulation. Attitude uses damped angular acceleration rather than a full inertia tensor. Terrain collisions use a height function; landing gear and detailed contact dynamics are not modeled.

The autonomous controller uses proportional position/velocity feedback to target the pad, a vertical-velocity descent profile, and damped attitude control. It is a demonstrative controller, not an aerospace flight-control system. Landing thresholds are 2.5 m/s vertical, 1.5 m/s horizontal, 8° tilt, inside the pad boundary, and at least 40% structural integrity.

## Performance

The environment uses a subdivided height mesh, low-poly rocks, 1024 px sun shadows, and a renderer pixel ratio capped at 1.5. It loads no external 3D models, images, or font files.
