import test from 'node:test';
import assert from 'node:assert/strict';
import { createTerrain, terrainHeightAt } from '../src/terrain.js';
import { ROCKET } from '../src/physics/rocketDynamics.js';

test('terrain height is repeatable and the landing platform remains flat', () => {
  for (const [x, z] of [[18, 12], [-42, 31], [63, -58], [0, 0], [5, -3]]) {
    assert.equal(terrainHeightAt(x, z), terrainHeightAt(x, z));
  }
  assert.equal(terrainHeightAt(0, 0), 0);
  assert.equal(terrainHeightAt(ROCKET.padRadius + 0.5, 0), 0);
});

test('procedural terrain mesh and rock placement are deterministic', () => {
  const first = createTerrain();
  const second = createTerrain();
  assert.equal(first.children.length, second.children.length);
  const firstVertices = first.children[0].geometry.attributes.position.array;
  const secondVertices = second.children[0].geometry.attributes.position.array;
  assert.equal(firstVertices.length, secondVertices.length);
  for (let i = 0; i < firstVertices.length; i += 137) assert.equal(firstVertices[i], secondVertices[i]);
});
