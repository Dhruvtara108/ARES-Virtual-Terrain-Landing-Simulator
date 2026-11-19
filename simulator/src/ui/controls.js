export function createControls(actions) {
  const held = new Set();
  const editable = (target) => target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));

  const onKeyDown = (event) => {
    if (editable(event.target)) return;
    const key = event.key.toLowerCase();
    if (['arrowleft', 'arrowright', 'arrowup', 'arrowdown', ' '].includes(key)) event.preventDefault();
    held.add(key);
    if (event.repeat) return;
    if (key === 'r') actions.reset();
    if (key === ' ') actions.togglePause();
  };
  const onKeyUp = (event) => held.delete(event.key.toLowerCase());
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);

  document.getElementById('start-auto').addEventListener('click', actions.startAutonomous);
  document.getElementById('start-manual').addEventListener('click', actions.startManual);
  document.getElementById('pause-button').addEventListener('click', actions.togglePause);
  document.getElementById('reset-button').addEventListener('click', actions.reset);
  document.getElementById('follow-button').addEventListener('click', actions.toggleFollow);

  return {
    manualCommand(state, dt) {
      let throttle = state.throttle;
      if (held.has('w')) throttle += 0.42 * dt;
      if (held.has('s')) throttle -= 0.42 * dt;
      return {
        throttle: Math.max(0, Math.min(1, throttle)),
        pitch: (held.has('arrowright') ? 1 : 0) - (held.has('arrowleft') ? 1 : 0),
        roll: (held.has('arrowup') ? 1 : 0) - (held.has('arrowdown') ? 1 : 0),
      };
    },
    dispose() {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    },
  };
}
