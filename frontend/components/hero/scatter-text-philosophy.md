# Gravitational Crystallization
### Algorithmic Philosophy for ScatterText v2

---

## The Core Idea

Data does not originate where it is read. It begins dispersed — raw signals scattered across a chaotic field, invisible and unordered. The act of intelligence is *convergence*: the invisible force that pulls entropy into meaning, noise into signal, scatter into form. **Gravitational Crystallization** is the philosophy that every piece of information visible on screen arrived from somewhere else in the universe — and the animation makes that journey visible.

The particle system does not merely scatter text and reassemble it. Each particle begins as a point of raw data existing anywhere in the observable field (the full viewport), pulled by the gravitational well of the text's origin coordinates. The convergence is not random — it is computed, weighted, and timed so that the assembly of letters emerges as an act of precision, as if an intelligence is writing in real time.

---

## The Particle as Unit of Meaning

Each particle represents one unit of information: small, precise, near-invisible in isolation. The existing implementation uses particles of size 0.45–1.15px, which reads as textured noise. The refined philosophy demands particles of 0.18–0.55px — sub-pixel to 0.5px — sampled at a gap of 0.85 rather than 1.25. This density increase (roughly 2× more particles) creates a fundamentally different visual register: not a collection of visible dots, but a *field of light* that resolves into letterforms. The individual particle should be so small it is nearly imperceptible; the letter emerges from their collective presence. This is the hallmark of a meticulously crafted algorithm — individual components that are humble, but whose sum is monumental.

---

## Viewport Gravity: The Full-Screen Origin Field

The critical failure of the current implementation is that particles scatter within the container bounds (`spreadX = canvasWidth * 0.28`). This is a local tremor when we need a cosmological event. The refined system mounts a **single full-viewport canvas** (`position: fixed, inset: 0, pointer-events: none`) that persists for the duration of the convergence animation. Particle initial positions are seeded across the entire viewport using `window.innerWidth × window.innerHeight` space. The text origin coordinates are offset by the container's `getBoundingClientRect()` to be expressed in viewport space.

The result: particles rain in from corners, edges, and far distances — from outside the text container entirely — as if the entire screen is the source field and the text is the attractor. This is the product of painstaking coordinate system design: one canvas, two phases (scatter-phase in viewport-space, settled-phase in container-space), seamless transition.

---

## Easing as Computation

Current easing: linear exponential decay (`x += dx * ease`), ease constant per particle. This is adequate but produces a rush-and-settle motion where all particles feel identical in character. The refined philosophy applies **per-particle gravitational ease**: ease starts slow (weak gravity at distance), accelerates as the particle approaches origin (strong gravity), then gently overshoots by 1–3px before settling. This requires tracking velocity separately from position:

```
velocity += (origin - position) * attractionStrength * (1 + distanceFactor)
velocity *= damping  // 0.82–0.88
position += velocity
```

The overshoot-and-settle is the most computationally expensive detail — and the most visually credible. It transforms mechanical assembly into organic crystallization. This behavioral refinement is the mark of a system refined through hundreds of iterations by someone who understands both physics and aesthetics.

---

## The Settled State: Micro-life After Convergence

The current system marks `particle.active = false` and stops all movement. The particle is frozen. This is computationally efficient but aesthetically inert. The refined system introduces a **micro-oscillation layer** for settled particles: a seeded sine-wave jitter of ±0.3px amplitude at low frequency (0.5–2Hz, per-particle variation). Combined with an opacity pulse (±0.08 amplitude), settled particles appear to breathe — as if the data is alive and processing. The animation never truly ends; it simply calms. This is not a gimmick but a consequence of the philosophy: information does not stop when you read it.

A sparse secondary layer of "sparkle events" triggers randomly post-convergence — 2–5% of particles briefly brighten to full opacity before fading, simulating live data updates arriving in the field. Each sparkle event is seeded and reproducible. This level of post-convergence detail is the painstaking final refinement that separates gallery-quality generative work from merely functional animation.
