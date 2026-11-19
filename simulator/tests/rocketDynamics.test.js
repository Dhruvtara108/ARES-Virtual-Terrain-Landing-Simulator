import test from 'node:test';
import assert from 'node:assert/strict';
import { GRAVITY, ROCKET, createInitialState, getThrustDirection, horizontalSpeed, isInsideLandingPad, stepRocket } from '../src/physics/rocketDynamics.js';

const EPS = 1e-6;

test('gravity accelerates an unpowered rocket downward', () => {
  const state = createInitialState();
  state.vy = 0;
  stepRocket(state, { throttle: 0 }, 0.01);
  assert.ok(Math.abs(state.vy + GRAVITY * 0.01) < EPS);
});

test('thrust acts along the current rocket axis', () => {
  const state = createInitialState();
  state.vy = 0;
  stepRocket(state, { throttle: 1 }, 0.01);
  assert.ok(state.vy > 0);
  assert.ok(Math.abs(state.vy - (ROCKET.maxThrust / state.mass - GRAVITY) * 0.01) < 0.003);
  const direction = getThrustDirection(Math.PI / 6, 0);
  assert.ok(direction[0] > 0 && direction[1] > 0);
});

test('fuel use decreases propellant and mass', () => {
  const state = createInitialState();
  const mass = state.mass;
  const fuel = state.fuel;
  stepRocket(state, { throttle: 0.5 }, 0.05);
  assert.ok(state.fuel < fuel);
  assert.ok(state.mass < mass);
  assert.ok(Math.abs(state.fuel - (fuel - ROCKET.fuelFlowRate * 0.5 * 0.05)) < EPS);
});

test('pitch produces horizontal motion and control input rotates the vehicle', () => {
  const state = createInitialState();
  state.pitch = 0.2;
  state.vx = 0;
  state.vy = 0;
  stepRocket(state, { throttle: 1 }, 0.02);
  assert.ok(state.vx > 0);
  const prior = state.pitch;
  stepRocket(state, { throttle: 0, pitch: 1 }, 0.02);
  assert.notEqual(state.pitch, prior);
});

test('landing-pad detection uses the circular pad footprint', () => {
  assert.equal(isInsideLandingPad(1, 2), true);
  assert.equal(isInsideLandingPad(6.1, 0), false);
});

test('low-speed upright touchdown inside the pad is safe', () => {
  const state = createInitialState();
  Object.assign(state, { x: 1, z: 1, y: ROCKET.contactOffset + ROCKET.padSurfaceY + 0.01, vx: 0.4, vy: -1.2, vz: 0.3, fuel: 30, mass: state.dryMass + 30 });
  stepRocket(state, { throttle: 0 }, 0.02, { groundHeightAt: () => ROCKET.padSurfaceY });
  assert.equal(state.result, 'SAFE LANDING');
  assert.equal(state.throttle, 0);
  assert.equal(state.vy, 0);
  assert.ok(state.touchdown.verticalSpeed <= 2.5);
});

test('high-speed touchdown is hard and touchdown outside the pad crashes', () => {
  const hard = createInitialState();
  Object.assign(hard, { x: 0, z: 0, y: ROCKET.contactOffset + ROCKET.padSurfaceY + 0.01, vy: -5, fuel: 30 });
  stepRocket(hard, { throttle: 0 }, 0.01, { groundHeightAt: () => ROCKET.padSurfaceY });
  assert.equal(hard.result, 'HARD LANDING');

  const offPad = createInitialState();
  Object.assign(offPad, { x: 10, y: ROCKET.contactOffset + 0.01, vy: -1, fuel: 30 });
  stepRocket(offPad, { throttle: 0 }, 0.02);
  assert.equal(offPad.result, 'OFF-PAD CRASH');
});

test('touchdown after propellant exhaustion is reported', () => {
  const state = createInitialState();
  Object.assign(state, { x: 0, z: 0, y: ROCKET.contactOffset + 0.01, vy: -1, fuel: 0, mass: state.dryMass });
  stepRocket(state, { throttle: 0 }, 0.02);
  assert.equal(state.result, 'FUEL DEPLETED');
});

test('large integration steps are rejected to protect stability', () => {
  assert.throws(() => stepRocket(createInitialState(), {}, 0.1), /dt must be/);
});
