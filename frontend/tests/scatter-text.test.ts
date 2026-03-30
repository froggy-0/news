import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSeededParticles,
  createSeededRandom,
  seedToNumber,
} from "../components/hero/ScatterText";

test("seedToNumber returns stable numeric seed for identical input", () => {
  assert.equal(seedToNumber("2026-03-21"), seedToNumber("2026-03-21"));
  assert.notEqual(seedToNumber("2026-03-21"), seedToNumber("2026-03-22"));
});

test("createSeededRandom produces deterministic sequence for identical seed", () => {
  const randomA = createSeededRandom("2026-03-21");
  const randomB = createSeededRandom("2026-03-21");
  const randomC = createSeededRandom("2026-03-22");

  const sequenceA = Array.from({ length: 5 }, () => randomA()).join(",");
  const sequenceB = Array.from({ length: 5 }, () => randomB()).join(",");
  const sequenceC = Array.from({ length: 5 }, () => randomC()).join(",");

  assert.equal(sequenceA, sequenceB);
  assert.notEqual(sequenceB, sequenceC);
});

test("buildSeededParticles keeps identical output for identical seed and point set", () => {
  const points = [
    { x: 4, y: 10 },
    { x: 8, y: 12 },
    { x: 12, y: 14 },
    { x: 20, y: 18 },
  ];

  const particlesA = buildSeededParticles({
    points,
    seed: "2026-03-21",
    color: "#fff",
    spreadX: 80,
    spreadY: 42,
    density: 1,
  });
  const particlesB = buildSeededParticles({
    points,
    seed: "2026-03-21",
    color: "#fff",
    spreadX: 80,
    spreadY: 42,
    density: 1,
  });
  const particlesC = buildSeededParticles({
    points,
    seed: "2026-03-22",
    color: "#fff",
    spreadX: 80,
    spreadY: 42,
    density: 1,
  });

  assert.deepEqual(particlesA, particlesB);
  assert.notDeepEqual(particlesA, particlesC);
});
