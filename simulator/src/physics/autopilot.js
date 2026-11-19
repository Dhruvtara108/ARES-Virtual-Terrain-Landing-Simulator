import { GRAVITY, ROCKET } from './rocketDynamics.js';

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

/** Explainable position/velocity PD guidance with attitude and throttle loops. */
export function computeAutopilot(state, target = {}) {
  const targetX = target.x ?? 0;
  const targetZ = target.z ?? 0;
  const surfaceY = target.surfaceY ?? ROCKET.padSurfaceY;
  const altitude = Math.max(0, state.y - ROCKET.contactOffset - surfaceY);
  const desiredVy = -Math.min(2.05, Math.sqrt(2 * 1.0 * altitude));
  const desiredAy = clamp((desiredVy - state.vy) * 0.92, -3.0, 4.8);
  const desiredVerticalThrustAccel = Math.max(0.5, GRAVITY + desiredAy);

  const desiredAx = clamp(-0.11 * (state.x - targetX) - 0.92 * state.vx, -3.2, 3.2);
  const desiredAz = clamp(-0.11 * (state.z - targetZ) - 0.92 * state.vz, -3.2, 3.2);
  const targetPitch = clamp(Math.atan2(desiredAx, desiredVerticalThrustAccel), -0.32, 0.32);
  const targetRoll = clamp(-Math.atan2(desiredAz, desiredVerticalThrustAccel), -0.32, 0.32);

  const pitch = clamp((targetPitch - state.pitch) * 4.6 - state.pitchRate * 2.4, -1, 1);
  const roll = clamp((targetRoll - state.roll) * 4.6 - state.rollRate * 2.4, -1, 1);
  const verticalCosine = Math.max(0.72, Math.cos(state.pitch) * Math.cos(state.roll));
  const maxAcceleration = ROCKET.maxThrust / state.mass;
  const throttle = clamp(desiredVerticalThrustAccel / (maxAcceleration * verticalCosine), 0, 1);
  return { throttle, pitch, roll, targetPitch, targetRoll, desiredVy, altitude };
}
