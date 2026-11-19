import * as THREE from 'three';
import { ROCKET } from './physics/rocketDynamics.js';

const PAD_CLEAR_RADIUS = ROCKET.padRadius + 2.0;

function hashNoise(x, z) {
  const value = Math.sin(x * 127.1 + z * 311.7 + 74.7) * 43758.5453123;
  return (value - Math.floor(value)) * 2 - 1;
}

export function terrainHeightAt(x, z) {
  if (Math.hypot(x, z) <= PAD_CLEAR_RADIUS) return 0;
  const broad = Math.sin(x * 0.055) * Math.cos(z * 0.048) * 0.75;
  const small = Math.sin((x + z) * 0.12) * 0.16 + hashNoise(Math.round(x * 0.16), Math.round(z * 0.16)) * 0.16;
  let height = broad + small;
  for (const crater of CRATERS) {
    const distance = Math.hypot(x - crater.x, z - crater.z);
    const bowl = -crater.depth * Math.exp(-((distance / crater.radius) ** 2) * 2.4);
    const rim = crater.depth * 0.23 * Math.exp(-(((distance - crater.radius) / 0.8) ** 2));
    height += bowl + rim;
  }
  return height;
}

const CRATERS = [
  { x: -24, z: -12, radius: 7, depth: 1.4 }, { x: 28, z: 13, radius: 9, depth: 1.8 },
  { x: 16, z: -32, radius: 5, depth: 0.9 }, { x: -38, z: 31, radius: 11, depth: 2 },
  { x: 46, z: -18, radius: 6, depth: 1.1 }, { x: -11, z: 42, radius: 8, depth: 1.4 },
];

function seededRandom(seed = 0x41524553) {
  let state = seed >>> 0;
  return () => {
    state += 0x6D2B79F5;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createTerrain() {
  const group = new THREE.Group();
  const size = 220;
  const segments = 150;
  const geometry = new THREE.PlaneGeometry(size, size, segments, segments);
  geometry.rotateX(-Math.PI / 2);
  const positions = geometry.attributes.position;
  for (let i = 0; i < positions.count; i += 1) {
    const x = positions.getX(i);
    const z = positions.getZ(i);
    positions.setY(i, terrainHeightAt(x, z));
  }
  geometry.computeVertexNormals();
  const ground = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x827c72, roughness: 0.98, metalness: 0.02 }));
  ground.receiveShadow = true;
  group.add(ground);

  const rand = seededRandom();
  const rockGeometry = new THREE.DodecahedronGeometry(1, 0);
  const rockMaterial = new THREE.MeshStandardMaterial({ color: 0x77766f, roughness: 1, flatShading: true });
  const rockPositions = [];
  for (let i = 0; i < 92; i += 1) {
    const x = (rand() - 0.5) * size * 0.88;
    const z = (rand() - 0.5) * size * 0.88;
    if (Math.hypot(x, z) < PAD_CLEAR_RADIUS + 4) continue;
    const scale = 0.25 + rand() * 1.2;
    rockPositions.push({ x, z, scale, rotation: rand() * Math.PI * 2 });
  }
  for (const rock of rockPositions) {
    const mesh = new THREE.Mesh(rockGeometry, rockMaterial);
    mesh.position.set(rock.x, terrainHeightAt(rock.x, rock.z) + rock.scale * 0.56, rock.z);
    mesh.scale.set(rock.scale * (0.8 + rand() * 0.6), rock.scale * (0.65 + rand() * 0.6), rock.scale);
    mesh.rotation.set(rand() * 0.3, rock.rotation, rand() * 0.3);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }

  for (const crater of CRATERS) {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(crater.radius, 0.25, 5, 48),
      new THREE.MeshStandardMaterial({ color: 0x9b9384, roughness: 1 }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(crater.x, terrainHeightAt(crater.x, crater.z) + 0.1, crater.z);
    ring.scale.set(1, 0.82, 1);
    ring.receiveShadow = true;
    group.add(ring);
  }

  const pad = new THREE.Group();
  pad.position.y = ROCKET.padSurfaceY - 0.008;
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(ROCKET.padRadius, ROCKET.padRadius + 0.35, 0.3, 64),
    new THREE.MeshStandardMaterial({ color: 0x262f38, metalness: 0.42, roughness: 0.58 }),
  );
  base.position.y = -0.15;
  base.castShadow = true;
  base.receiveShadow = true;
  pad.add(base);
  const surface = new THREE.Mesh(
    new THREE.CircleGeometry(ROCKET.padRadius - 0.18, 64),
    new THREE.MeshStandardMaterial({ color: 0xaaa89f, roughness: 0.78, metalness: 0.12, side: THREE.DoubleSide }),
  );
  surface.rotation.x = -Math.PI / 2;
  surface.position.y = 0.008;
  surface.receiveShadow = true;
  pad.add(surface);
  const markings = new THREE.Group();
  const lineMaterial = new THREE.MeshBasicMaterial({ color: 0x293542, transparent: true, opacity: 0.78 });
  for (const radius of [2.2, 4.4]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.055, 5, 96), lineMaterial);
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.025;
    markings.add(ring);
  }
  const crossMaterial = new THREE.MeshBasicMaterial({ color: 0xe36c39 });
  for (const [width, length] of [[0.16, 2.3], [2.3, 0.16]]) {
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(width, 0.025, length), crossMaterial);
    stripe.position.y = 0.026;
    markings.add(stripe);
  }
  const target = new THREE.Mesh(new THREE.RingGeometry(0.4, 0.6, 40), new THREE.MeshBasicMaterial({ color: 0xe36c39, side: THREE.DoubleSide }));
  target.rotation.x = -Math.PI / 2;
  target.position.y = 0.03;
  markings.add(target);
  pad.add(markings);

  const lightMaterial = new THREE.MeshStandardMaterial({ color: 0x8be5e1, emissive: 0x27bbb8, emissiveIntensity: 2.1 });
  for (let index = 0; index < 16; index += 1) {
    const angle = index / 16 * Math.PI * 2;
    const light = new THREE.Mesh(new THREE.SphereGeometry(0.14, 8, 6), lightMaterial);
    light.position.set(Math.cos(angle) * (ROCKET.padRadius - 0.35), 0.12, Math.sin(angle) * (ROCKET.padRadius - 0.35));
    pad.add(light);
  }
  group.add(pad);
  return group;
}
