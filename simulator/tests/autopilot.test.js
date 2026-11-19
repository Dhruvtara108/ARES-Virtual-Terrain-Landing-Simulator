import test from 'node:test';
import assert from 'node:assert/strict';
import { computeAutopilot } from '../src/physics/autopilot.js';
import { FIXED_DT, ROCKET, createInitialState, horizontalSpeed, stepRocket, tiltRadians } from '../src/physics/rocketDynamics.js';
import { terrainHeightAt } from '../src/terrain.js';

test('autopilot commands bounded controls toward the pad', () => {
  const state = createInitialState();
  const command = computeAutopilot(state);
  assert.ok(command.throttle >= 0 && command.throttle <= 1);
  assert.ok(command.pitch >= -1 && command.pitch <= 1);
  assert.ok(command.roll >= -1 && command.roll <= 1);
  assert.ok(command.desiredVy < 0);
});

test('autopilot achieves safe touchdown by controlling actual fixed-step physics', () => {
  const state = createInitialState();
  state.status = 'AUTONOMOUS';
  const maxSteps = 120 * 45;
  for (let i = 0; i < maxSteps && !state.result; i += 1) {
    const controls = computeAutopilot(state, { x: 0, z: 0, surfaceY: ROCKET.padSurfaceY });
    stepRocket(state, controls, FIXED_DT, {
      groundHeightAt: (x, z) => Math.hypot(x, z) <= ROCKET.padRadius ? ROCKET.padSurfaceY : terrainHeightAt(x, z),
    });
  }
  assert.equal(state.result, 'SAFE LANDING', `result=${state.result}; x=${state.x.toFixed(2)} z=${state.z.toFixed(2)} y=${state.y.toFixed(2)} vy=${state.vy.toFixed(2)} fuel=${state.fuel.toFixed(2)}`);
  assert.ok(Math.hypot(state.touchdown.horizontalSpeed, state.touchdown.verticalSpeed) > 0);
  assert.ok(state.touchdown.verticalSpeed <= 2.5);
  assert.ok(state.touchdown.horizontalSpeed <= 1.5);
  assert.ok(state.touchdown.tiltRadians <= 8 * Math.PI / 180);
  assert.ok(state.touchdown.fuel > 0);
  assert.ok(state.touchdown.structuralIntegrity >= 40);
  assert.equal(state.y, ROCKET.padSurfaceY + ROCKET.contactOffset);
  assert.equal(horizontalSpeed(state), 0);
  assert.ok(tiltRadians(state) <= 8 * Math.PI / 180);
});
