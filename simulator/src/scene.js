import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export function createScene(container) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111820);
  scene.fog = new THREE.Fog(0xadb2b3, 85, 250);

  const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 500);
  camera.position.set(42, 31, 48);
  camera.lookAt(0, 8, 0);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setSize(container.clientWidth, container.clientHeight, false);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  container.appendChild(renderer.domElement);

  scene.add(new THREE.HemisphereLight(0xd6e2e8, 0x62584b, 1.55));
  const sun = new THREE.DirectionalLight(0xffe4bd, 2.5);
  sun.position.set(-55, 75, 38);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.left = -65;
  sun.shadow.camera.right = 65;
  sun.shadow.camera.top = 65;
  sun.shadow.camera.bottom = -65;
  sun.shadow.bias = -0.00022;
  sun.shadow.normalBias = 0.035;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x9ebaca, 0.7);
  fill.position.set(45, 20, -25);
  scene.add(fill);

  const random = (() => {
    let seed = 0x51E1E;
    return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  })();
  const starVertices = [];
  for (let i = 0; i < 700; i += 1) {
    const theta = random() * Math.PI * 2;
    const y = 28 + random() * 90;
    const radius = 150 + random() * 75;
    starVertices.push(Math.cos(theta) * radius, y, Math.sin(theta) * radius);
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starVertices, 3));
  const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({ color: 0xe4e7df, size: 0.46, sizeAttenuation: true, transparent: true, opacity: 0.8 }));
  scene.add(stars);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 8, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.minDistance = 12;
  controls.maxDistance = 145;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.update();

  const resize = () => {
    const width = Math.max(1, container.clientWidth);
    const height = Math.max(1, container.clientHeight);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(width, height, false);
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);

  let followOffset = new THREE.Vector3();
  let lastFollowPoint = null;
  function setFollow(enabled, point = new THREE.Vector3()) {
    if (enabled) {
      followOffset.copy(camera.position).sub(controls.target);
      lastFollowPoint = point.clone();
    } else {
      lastFollowPoint = null;
    }
  }
  function updateFollow(point) {
    if (!lastFollowPoint) return;
    const delta = point.clone().sub(lastFollowPoint);
    camera.position.add(delta);
    controls.target.add(delta);
    lastFollowPoint.copy(point);
  }
  function render() {
    controls.update();
    renderer.render(scene, camera);
  }
  return { scene, camera, renderer, controls, render, setFollow, updateFollow, resizeObserver };
}
