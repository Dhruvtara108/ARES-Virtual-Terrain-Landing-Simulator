import * as THREE from 'three';
import { createScene } from './scene.js';
import { createTerrain, terrainHeightAt } from './terrain.js';
import { createRocket, updateRocketVisual } from './rocket.js';
import { computeAutopilot } from './physics/autopilot.js';
import { FIXED_DT, ROCKET, createInitialState, stepRocket } from './physics/rocketDynamics.js';
import { clearResult, setCameraFollow, setModeHint, showResult, showToast, updateHud } from './ui/hud.js';
import { createControls } from './ui/controls.js';
import './styles/main.css';

const viewport = document.getElementById('viewport');
const view = createScene(viewport);
const terrain = createTerrain();
view.scene.add(terrain);
const rocket = createRocket();
view.scene.add(rocket);

let state = createInitialState();
let mode = 'idle';
let paused = false;
let following = false;
let accumulator = 0;
const MAX_FRAME_DELTA = 0.1;
const MAX_STEPS_PER_FRAME = 12;

const groundHeightAt = (x, z) => Math.hypot(x, z) <= ROCKET.padRadius ? ROCKET.padSurfaceY : terrainHeightAt(x, z);
const altitudeAgl = (s) => Math.max(0, s.y - ROCKET.contactOffset - groundHeightAt(s.x, s.z));

const reset = () => {
  state = createInitialState();
  mode = 'idle';
  paused = false;
  accumulator = 0;
  clearResult();
  setModeHint('AUTOPILOT READY · SELECT A FLIGHT MODE');
  updateRocketVisual(rocket, state);
  updateHud(state, { mode, paused, altitude: altitudeAgl(state) });
  if (following) view.setFollow(true, rocket.position);
};

const start = (nextMode) => {
  reset();
  mode = nextMode;
  state.status = nextMode === 'autonomous' ? 'AUTONOMOUS' : 'MANUAL';
  paused = false;
  setModeHint(nextMode === 'autonomous' ? 'GUIDANCE ACTIVE · PD LANDING SEQUENCE' : 'MANUAL PILOT ACTIVE · W / S THROTTLE');
  showToast(nextMode === 'autonomous' ? 'Autonomous descent initiated' : 'Manual flight controls active');
};

const togglePause = () => {
  if (mode === 'idle' || mode === 'complete') return;
  paused = !paused;
  if (!paused) state.status = mode === 'autonomous' ? 'AUTONOMOUS' : 'MANUAL';
  setModeHint(paused ? 'SIMULATION PAUSED · PRESS SPACE TO RESUME' : (mode === 'autonomous' ? 'GUIDANCE ACTIVE · PD LANDING SEQUENCE' : 'MANUAL PILOT ACTIVE · W / S THROTTLE'));
  updateHud(state, { mode, paused, altitude: altitudeAgl(state) });
};

const toggleFollow = () => {
  following = !following;
  view.setFollow(following, rocket.position);
  setCameraFollow(following);
  showToast(following ? 'Camera follow enabled' : 'Orbit camera enabled');
};

const inputs = createControls({
  startAutonomous: () => start('autonomous'),
  startManual: () => start('manual'),
  togglePause,
  reset,
  toggleFollow,
});

document.getElementById('start-auto').title = 'Start a physics-driven autonomous landing attempt.';
document.getElementById('start-manual').title = 'Start the rocket in manual flight mode.';
document.getElementById('follow-button').title = 'Keep the camera target centered on the rocket.';

updateRocketVisual(rocket, state);
updateHud(state, { mode, paused, altitude: altitudeAgl(state) });

const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const frameDelta = Math.min(clock.getDelta(), MAX_FRAME_DELTA);
  if (mode !== 'idle' && mode !== 'complete' && !paused && !state.result) {
    accumulator += frameDelta;
    let steps = 0;
    while (accumulator >= FIXED_DT && steps < MAX_STEPS_PER_FRAME) {
      const command = mode === 'autonomous'
        ? computeAutopilot(state, { x: 0, z: 0, surfaceY: ROCKET.padSurfaceY })
        : inputs.manualCommand(state, FIXED_DT);
      stepRocket(state, command, FIXED_DT, { groundHeightAt });
      accumulator -= FIXED_DT;
      steps += 1;
      if (state.result) {
        accumulator = 0;
        mode = 'complete';
        showResult(state);
        setModeHint('FLIGHT COMPLETE · RESET TO FLY AGAIN');
        showToast(state.result);
        break;
      }
    }
    if (steps === MAX_STEPS_PER_FRAME && accumulator >= FIXED_DT) accumulator = 0;
  }

  updateRocketVisual(rocket, state);
  if (following) view.updateFollow(rocket.position);
  updateHud(state, { mode, paused, altitude: altitudeAgl(state) });
  view.render();
}
animate();

if (import.meta.hot) import.meta.hot.dispose(() => {
  inputs.dispose();
  view.resizeObserver.disconnect();
  view.controls.dispose();
  view.renderer.dispose();
});
