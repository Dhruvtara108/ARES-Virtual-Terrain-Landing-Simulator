export const GRAVITY = 9.81;
export const FIXED_DT = 1 / 120;
export const ROCKET = Object.freeze({
  dryMass: 1000,
  fuelCapacity: 100,
  maxThrust: 19000,
  fuelFlowRate: 7.2,
  contactOffset: 3.15,
  padRadius: 6,
  padSurfaceY: 0.35,
});

export function createInitialState() {
  return {
    x: 8.2, y: 34, z: -6.5,
    vx: -1.8, vy: -4.2, vz: 1.5,
    pitch: 0, roll: 0,
    pitchRate: 0, rollRate: 0,
    dryMass: ROCKET.dryMass,
    fuel: ROCKET.fuelCapacity,
    initialFuel: ROCKET.fuelCapacity,
    mass: ROCKET.dryMass + ROCKET.fuelCapacity,
    throttle: 0,
    thrust: 0,
    structuralIntegrity: 100,
    elapsed: 0,
    status: 'STANDBY',
    result: null,
    touchdown: null,
  };
}

export function horizontalSpeed(state) {
  return Math.hypot(state.vx, state.vz);
}

export function tiltRadians(state) {
  return Math.acos(Math.max(-1, Math.min(1, Math.cos(state.pitch) * Math.cos(state.roll))));
}

export function isInsideLandingPad(x, z, radius = ROCKET.padRadius) {
  return Math.hypot(x, z) <= radius;
}

export function getThrustDirection(pitch, roll) {
  return [Math.sin(pitch) * Math.cos(roll), Math.cos(pitch) * Math.cos(roll), -Math.sin(roll)];
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function finishTouchdown(state, groundY) {
  const horizontal = horizontalSpeed(state);
  const vertical = Math.abs(state.vy);
  const tilt = tiltRadians(state);
  const onPad = isInsideLandingPad(state.x, state.z, ROCKET.padRadius - 0.25);
  const impact = vertical * 0.8 + horizontal * 0.6 + tilt * (180 / Math.PI) * 0.3;
  state.structuralIntegrity = clamp(state.structuralIntegrity - Math.max(0, impact - 8) * 3.5, 0, 100);

  let result;
  if (!onPad) result = 'OFF-PAD CRASH';
  else if (state.fuel <= 0.001) result = 'FUEL DEPLETED';
  else if (vertical <= 2.5 && horizontal <= 1.5 && tilt <= 8 * Math.PI / 180 && state.structuralIntegrity >= 40) result = 'SAFE LANDING';
  else result = 'HARD LANDING';

  state.y = groundY + ROCKET.contactOffset;
  state.vx = 0;
  state.vy = 0;
  state.vz = 0;
  state.pitchRate = 0;
  state.rollRate = 0;
  state.throttle = 0;
  state.thrust = 0;
  state.result = result;
  state.status = result;
  state.touchdown = { verticalSpeed: vertical, horizontalSpeed: horizontal, tiltRadians: tilt, fuel: state.fuel, structuralIntegrity: state.structuralIntegrity };
}

/** Advance a single deterministic rigid-body step; callers provide fixed dt. */
export function stepRocket(state, controls = {}, dt = FIXED_DT, options = {}) {
  if (!(dt > 0) || dt > 0.05) throw new RangeError('dt must be in (0, 0.05] seconds');
  if (state.result) return state;
  const throttleCommand = clamp(Number(controls.throttle ?? state.throttle), 0, 1);
  const pitchCommand = clamp(Number(controls.pitch ?? 0), -1, 1);
  const rollCommand = clamp(Number(controls.roll ?? 0), -1, 1);

  const fuelUsed = Math.min(state.fuel, ROCKET.fuelFlowRate * throttleCommand * dt);
  state.fuel = Math.max(0, state.fuel - fuelUsed);
  state.mass = state.dryMass + state.fuel;
  state.throttle = state.fuel > 0 ? throttleCommand : 0;
  state.thrust = ROCKET.maxThrust * state.throttle;

  const pitchAngularAccel = pitchCommand * 2.8 - state.pitchRate * 1.9;
  const rollAngularAccel = rollCommand * 2.8 - state.rollRate * 1.9;
  state.pitchRate += pitchAngularAccel * dt;
  state.rollRate += rollAngularAccel * dt;
  state.pitch = clamp(state.pitch + state.pitchRate * dt, -0.62, 0.62);
  state.roll = clamp(state.roll + state.rollRate * dt, -0.62, 0.62);

  const [tx, ty, tz] = getThrustDirection(state.pitch, state.roll);
  const thrustAccel = state.mass > 0 ? state.thrust / state.mass : 0;
  const ax = tx * thrustAccel;
  const ay = ty * thrustAccel - GRAVITY;
  const az = tz * thrustAccel;

  state.vx += ax * dt;
  state.vy += ay * dt;
  state.vz += az * dt;
  state.x += state.vx * dt;
  state.y += state.vy * dt;
  state.z += state.vz * dt;
  state.elapsed += dt;

  const groundY = Number(options.groundHeightAt?.(state.x, state.z) ?? 0);
  if (state.y <= groundY + ROCKET.contactOffset) finishTouchdown(state, groundY);
  return state;
}
