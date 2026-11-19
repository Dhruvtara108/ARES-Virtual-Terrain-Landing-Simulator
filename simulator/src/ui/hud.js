import { horizontalSpeed, ROCKET } from '../physics/rocketDynamics.js';

const byId = (id) => document.getElementById(id);
const formatNumber = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : '—';
const degrees = (radians) => radians * 180 / Math.PI;

export function updateHud(state, { paused = false, mode = 'idle', altitude = null } = {}) {
  const agl = altitude ?? Math.max(0, state.y - ROCKET.contactOffset - ROCKET.padSurfaceY);
  byId('altitude-large').textContent = formatNumber(agl, 1);
  byId('altitude-value').textContent = formatNumber(agl, 1);
  byId('altitude-bar').style.width = `${Math.max(2, Math.min(100, agl / 35 * 100))}%`;
  byId('vertical-speed').textContent = formatNumber(state.vy, 2);
  byId('horizontal-speed').textContent = formatNumber(horizontalSpeed(state), 2);
  byId('fuel-value').textContent = `${Math.round(state.fuel / state.initialFuel * 100)}%`;
  byId('fuel-bar').style.width = `${Math.max(0, state.fuel / state.initialFuel * 100)}%`;
  byId('fuel-bar').classList.toggle('low', state.fuel / state.initialFuel < 0.2);
  byId('throttle-value').textContent = `${Math.round(state.throttle * 100)}%`;
  byId('throttle-bar').style.width = `${state.throttle * 100}%`;
  byId('pitch-value').textContent = `${formatNumber(degrees(state.pitch))}°`;
  byId('roll-value').textContent = `${formatNumber(degrees(state.roll))}°`;
  byId('attitude-dot').style.transform = `translate(${Math.max(-24, Math.min(24, state.pitch * 78))}px, ${Math.max(-17, Math.min(17, state.roll * 52))}px)`;
  const minutes = Math.floor(state.elapsed / 60).toString().padStart(2, '0');
  const seconds = Math.floor(state.elapsed % 60).toString().padStart(2, '0');
  byId('mission-time').textContent = `${minutes}:${seconds}`;
  let status = state.status;
  if (paused) status = 'PAUSED';
  else if (mode === 'idle') status = 'STANDBY';
  byId('flight-status').textContent = status;
  byId('telemetry-dot').classList.toggle('active', mode !== 'idle' && !paused && !state.result);
  byId('pause-button').textContent = paused ? '▶ RESUME' : 'Ⅱ PAUSE';
  byId('pause-button').disabled = mode === 'idle' || Boolean(state.result);
}

export function showResult(state) {
  const banner = byId('result-banner');
  const safe = state.result === 'SAFE LANDING';
  banner.classList.remove('hidden', 'safe', 'failure');
  banner.classList.add(safe ? 'safe' : 'failure');
  byId('result-title').textContent = state.result;
  const touchdown = state.touchdown;
  byId('result-detail').textContent = `V ${touchdown.verticalSpeed.toFixed(2)} m/s  ·  H ${touchdown.horizontalSpeed.toFixed(2)} m/s  ·  FUEL ${Math.round(touchdown.fuel / state.initialFuel * 100)}%`;
  document.querySelector('.result-icon').textContent = safe ? '✓' : '!';
}

export function clearResult() {
  byId('result-banner').classList.add('hidden');
}

export function setModeHint(text) {
  byId('mode-hint').textContent = text;
}

export function setCameraFollow(active) {
  byId('follow-state').textContent = active ? 'ON' : 'OFF';
  byId('view-mode').textContent = active ? 'FOLLOW CAM' : 'ORBIT VIEW';
  byId('follow-button').classList.toggle('selected', active);
}

export function showToast(message) {
  const toast = byId('toast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => toast.classList.remove('visible'), 2100);
}
