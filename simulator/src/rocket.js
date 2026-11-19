import * as THREE from 'three';
import { getThrustDirection } from './physics/rocketDynamics.js';

function addStrut(parent, start, end, radius, material) {
  const a = new THREE.Vector3(...start);
  const b = new THREE.Vector3(...end);
  const delta = new THREE.Vector3().subVectors(b, a);
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.72, radius, delta.length(), 8), material);
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize());
  mesh.castShadow = true;
  parent.add(mesh);
  return mesh;
}

export function createRocket() {
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);
  const white = new THREE.MeshStandardMaterial({ color: 0xdfe5e7, metalness: 0.35, roughness: 0.35 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x29343e, metalness: 0.64, roughness: 0.32 });
  const orange = new THREE.MeshStandardMaterial({ color: 0xe87443, metalness: 0.2, roughness: 0.5 });
  const glass = new THREE.MeshStandardMaterial({ color: 0x3bbfc4, metalness: 0.72, roughness: 0.2, emissive: 0x0b4147, emissiveIntensity: 0.4 });

  const fuselage = new THREE.Mesh(new THREE.CylinderGeometry(0.72, 0.82, 4.25, 20), white);
  fuselage.castShadow = true;
  fuselage.receiveShadow = true;
  body.add(fuselage);
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.72, 1.55, 20), white);
  nose.position.y = 2.9;
  nose.castShadow = true;
  body.add(nose);
  const noseTip = new THREE.Mesh(new THREE.SphereGeometry(0.1, 8, 6), orange);
  noseTip.position.y = 3.68;
  body.add(noseTip);

  const band = new THREE.Mesh(new THREE.CylinderGeometry(0.84, 0.84, 0.22, 24), orange);
  band.position.y = 0.85;
  body.add(band);
  const window = new THREE.Mesh(new THREE.SphereGeometry(0.31, 16, 12), glass);
  window.scale.set(1, 1.14, 0.42);
  window.position.set(0, 1.4, 0.67);
  body.add(window);

  for (let i = 0; i < 4; i += 1) {
    const fin = new THREE.Mesh(new THREE.BoxGeometry(0.13, 1.55, 0.9), orange);
    fin.position.set(0, -1.45, 0.83);
    fin.rotation.z = -0.25;
    fin.rotation.x = 0.12;
    fin.rotation.y = i * Math.PI / 2;
    fin.castShadow = true;
    body.add(fin);
  }

  const engineTop = new THREE.Mesh(new THREE.CylinderGeometry(0.58, 0.92, 0.55, 20), dark);
  engineTop.position.y = -2.24;
  body.add(engineTop);
  const bell = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.72, 0.85, 20, 1, true), dark);
  bell.position.y = -2.88;
  bell.castShadow = true;
  body.add(bell);
  const nozzleRim = new THREE.Mesh(new THREE.TorusGeometry(0.66, 0.09, 8, 20), dark);
  nozzleRim.rotation.x = Math.PI / 2;
  nozzleRim.position.y = -3.31;
  body.add(nozzleRim);

  const legMaterial = new THREE.MeshStandardMaterial({ color: 0x828d92, metalness: 0.72, roughness: 0.32 });
  const footMaterial = new THREE.MeshStandardMaterial({ color: 0x242d33, metalness: 0.52, roughness: 0.54 });
  for (let i = 0; i < 4; i += 1) {
    const angle = i * Math.PI / 2 + Math.PI / 4;
    const radial = new THREE.Vector3(Math.cos(angle), 0, Math.sin(angle));
    const upper = radial.clone().multiplyScalar(0.61).add(new THREE.Vector3(0, -1.25, 0));
    const knee = radial.clone().multiplyScalar(1.03).add(new THREE.Vector3(0, -2.35, 0));
    const foot = radial.clone().multiplyScalar(1.48).add(new THREE.Vector3(0, -3.12, 0));
    addStrut(body, upper.toArray(), knee.toArray(), 0.09, legMaterial);
    addStrut(body, knee.toArray(), foot.toArray(), 0.065, legMaterial);
    const shoe = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 0.12, 10), footMaterial);
    shoe.position.copy(foot);
    shoe.castShadow = true;
    body.add(shoe);
  }

  const exhaust = new THREE.Group();
  exhaust.position.y = -3.27;
  body.add(exhaust);
  const flameOuter = new THREE.Mesh(new THREE.ConeGeometry(0.62, 3.2, 16), new THREE.MeshBasicMaterial({ color: 0xff7a32, transparent: true, opacity: 0.76, depthWrite: false }));
  flameOuter.rotation.x = Math.PI;
  flameOuter.position.y = -1.5;
  exhaust.add(flameOuter);
  const flameInner = new THREE.Mesh(new THREE.ConeGeometry(0.31, 2.15, 12), new THREE.MeshBasicMaterial({ color: 0xffe29a, transparent: true, opacity: 0.9, depthWrite: false }));
  flameInner.rotation.x = Math.PI;
  flameInner.position.y = -1.0;
  exhaust.add(flameInner);
  const engineGlow = new THREE.PointLight(0xff8a4a, 0, 9, 2);
  engineGlow.position.y = -0.65;
  exhaust.add(engineGlow);

  root.userData = { body, exhaust, flameOuter, flameInner, engineGlow };
  root.traverse((object) => { if (object.isMesh) object.frustumCulled = true; });
  return root;
}

export function updateRocketVisual(rocket, state) {
  rocket.position.set(state.x, state.y, state.z);
  const direction = new THREE.Vector3(...getThrustDirection(state.pitch, state.roll)).normalize();
  rocket.userData.body.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  rocket.userData.body.rotateY(state.roll);
  const power = state.throttle;
  rocket.userData.exhaust.visible = power > 0.015;
  rocket.userData.exhaust.scale.setScalar(0.55 + power * 0.65);
  rocket.userData.flameOuter.material.opacity = 0.28 + power * 0.55;
  rocket.userData.flameInner.material.opacity = 0.35 + power * 0.6;
  rocket.userData.engineGlow.intensity = power * 2.4;
}
