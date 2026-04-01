"use client";

import React, { useEffect, useRef, useState } from "react";
import { useInView } from "motion/react";

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  originX: number;
  originY: number;
  color: string;
  size: number;
  active: boolean;
  jitterPhase: number;
  jitterFreq: number;
  sparklePhase: number;
  isSparkle: boolean;
};

type ScatterSeedPoint = {
  x: number;
  y: number;
};

export function seedToNumber(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function createSeededRandom(seed: string): () => number {
  let state = seedToNumber(seed) || 1;
  return () => {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function buildSeededParticles({
  points,
  seed,
  color,
  spreadX,
  spreadY,
  density,
}: {
  points: ScatterSeedPoint[];
  seed: string;
  color: string;
  spreadX: number;
  spreadY: number;
  density: number;
}): Particle[] {
  const random = createSeededRandom(`${seed}:${points.length}:${spreadX}:${spreadY}:${density}`);
  const particles: Particle[] = [];

  for (const point of points) {
    if (random() > density) {
      continue;
    }

    particles.push({
      x: point.x + (random() * spreadX - spreadX / 2),
      y: point.y + (random() * spreadY - spreadY / 2),
      vx: 0,
      vy: 0,
      originX: point.x,
      originY: point.y,
      color,
      size: 0.18 + random() * 0.37,
      active: true,
      jitterPhase: random() * Math.PI * 2,
      jitterFreq: 0.5 + random() * 1.5,
      sparklePhase: random() * Math.PI * 2,
      isSparkle: random() < 0.035,
    });
  }

  return particles;
}

export function ScatterText({
  text,
  seed,
  className,
  color = "#FFFFFF",
  fontSize = 56,
  density = 0.72,
  spread = 0.28,
  durationMs = 920,
}: {
  text: string;
  seed: string;
  className?: string;
  color?: string;
  fontSize?: number;
  density?: number;
  spread?: number;
  durationMs?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isInView = useInView(containerRef, { once: true, margin: "0px" });
  const [reducedMotion, setReducedMotion] = useState(false);
  const [animationReady, setAnimationReady] = useState(false);
  const [fallbackVisible, setFallbackVisible] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => setReducedMotion(mediaQuery.matches);
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (reducedMotion) {
      setAnimationReady(false);
      return;
    }
    if (!isInView) {
      return;
    }
    setAnimationReady(true);
  }, [durationMs, isInView, reducedMotion]);

  useEffect(() => {
    if (reducedMotion || !animationReady || !canvasRef.current || !containerRef.current) {
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) {
      setFallbackVisible(true);
      return;
    }

    let animationFrameId = 0;
    let resizeObserver: ResizeObserver | null = null;
    let viewportCanvas: HTMLCanvasElement | null = null;

    const render = async () => {
      const containerEl = containerRef.current;
      if (!containerEl) {
        return;
      }

      await document.fonts.ready;

      const dpr = window.devicePixelRatio || 1;
      const rect = containerEl.getBoundingClientRect();

      // Measure and resolve font size
      const tempCanvas = document.createElement("canvas");
      const tempCtx = tempCanvas.getContext("2d", { willReadFrequently: true });
      if (!tempCtx) {
        setFallbackVisible(true);
        return;
      }

      const targetWidth = Math.max(240, Math.round(rect.width) - 6);
      let resolvedFontSize = fontSize;
      tempCtx.font = `900 ${resolvedFontSize}px Pretendard, Inter, sans-serif`;
      const initialWidth = tempCtx.measureText(text).width;
      if (initialWidth > targetWidth) {
        const scale = targetWidth / initialWidth;
        resolvedFontSize = Math.max(30, Math.floor(fontSize * scale));
        tempCtx.font = `900 ${resolvedFontSize}px Pretendard, Inter, sans-serif`;
      }

      const metrics = tempCtx.measureText(text);
      const canvasWidth = Math.max(targetWidth + 32, Math.ceil(metrics.width) + 32);
      const canvasHeight = Math.max(96, Math.round(resolvedFontSize * 1.7));
      const textX = 4;
      const textY = canvasHeight / 2;

      // Sample text pixels at higher density (gap 0.85 vs 1.25)
      const offscreenCanvas = document.createElement("canvas");
      const offscreenCtx = offscreenCanvas.getContext("2d", { willReadFrequently: true });
      if (!offscreenCtx) {
        setFallbackVisible(true);
        return;
      }

      offscreenCanvas.width = canvasWidth;
      offscreenCanvas.height = canvasHeight;
      offscreenCtx.clearRect(0, 0, canvasWidth, canvasHeight);
      offscreenCtx.font = `900 ${resolvedFontSize}px Pretendard, Inter, sans-serif`;
      offscreenCtx.fillStyle = color;
      offscreenCtx.textAlign = "left";
      offscreenCtx.textBaseline = "middle";
      offscreenCtx.fillText(text, textX, textY);

      const pixels = offscreenCtx.getImageData(0, 0, canvasWidth, canvasHeight).data;
      const points: ScatterSeedPoint[] = [];
      const gap = 0.85;

      for (let y = 0; y < canvasHeight; y += gap) {
        for (let x = 0; x < canvasWidth; x += gap) {
          const index = (Math.floor(y) * canvasWidth + Math.floor(x)) * 4;
          if (pixels[index + 3] > 132) {
            points.push({ x, y });
          }
        }
      }

      // Build particles — initial positions scattered across full viewport
      const random = createSeededRandom(`${seed}:${points.length}:${density}:grav`);
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const particles: Particle[] = [];

      for (const point of points) {
        if (random() > density) continue;
        particles.push({
          x: random() * vw,
          y: random() * vh,
          vx: 0,
          vy: 0,
          originX: point.x,
          originY: point.y,
          color,
          size: 0.18 + random() * 0.37,
          active: true,
          jitterPhase: random() * Math.PI * 2,
          jitterFreq: 0.5 + random() * 1.5,
          sparklePhase: random() * Math.PI * 2,
          isSparkle: random() < 0.035,
        });
      }

      // Viewport canvas for scatter phase
      viewportCanvas?.remove();
      viewportCanvas = document.createElement("canvas");
      viewportCanvas.style.cssText =
        "position:fixed;inset:0;pointer-events:none;z-index:9999";
      viewportCanvas.width = vw * dpr;
      viewportCanvas.height = vh * dpr;
      viewportCanvas.style.width = `${vw}px`;
      viewportCanvas.style.height = `${vh}px`;
      document.body.appendChild(viewportCanvas);
      const vpCtx = viewportCanvas.getContext("2d");
      if (!vpCtx) {
        setFallbackVisible(true);
        return;
      }
      vpCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Container canvas (used during settled micro-life)
      canvas.width = canvasWidth * dpr;
      canvas.height = canvasHeight * dpr;
      canvas.style.width = `${canvasWidth}px`;
      canvas.style.height = `${canvasHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      setFallbackVisible(false);
      cancelAnimationFrame(animationFrameId);

      let phase: "scatter" | "settled" = "scatter";
      let frame = 0;

      const animate = () => {
        frame++;

        if (phase === "scatter") {
          // Re-read rect every frame so scroll doesn't desync particle targets
          const currentRect = containerEl.getBoundingClientRect();
          const cLeft = currentRect.left;
          const cTop = currentRect.top;
          // Canvas is vertically centered in the shell via CSS (top:50% translateY(-50%)),
          // so its actual top = shellTop + shellH/2 - canvasH/2. Use this offset so
          // viewport-canvas coords match container-canvas coords after transition.
          const cActualTop = cTop + currentRect.height / 2 - canvasHeight / 2;

          vpCtx.clearRect(0, 0, vw, vh);

          let allSettled = true;

          for (const particle of particles) {
            if (particle.active) {
              const originVX = cLeft + particle.originX;
              const originVY = cActualTop + particle.originY;

              const dx = originVX - particle.x;
              const dy = originVY - particle.y;
              const dist = Math.sqrt(dx * dx + dy * dy);

              // Gravitational physics: velocity + damping
              particle.vx += dx * 0.002;
              particle.vy += dy * 0.002;
              particle.vx *= 0.87;
              particle.vy *= 0.87;
              particle.x += particle.vx;
              particle.y += particle.vy;

              if (dist < 1.5 && Math.abs(particle.vx) < 0.2 && Math.abs(particle.vy) < 0.2) {
                particle.x = originVX;
                particle.y = originVY;
                particle.active = false;
              } else {
                allSettled = false;
              }
            }

            const originVX = cLeft + particle.originX;
            const originVY = cActualTop + particle.originY;
            const distFromOrigin = Math.sqrt(
              (originVX - particle.x) ** 2 + (originVY - particle.y) ** 2,
            );
            const opacity = Math.max(0.14, Math.min(1, 1.5 - distFromOrigin / 160));

            vpCtx.globalAlpha = opacity;
            vpCtx.fillStyle = particle.color;
            vpCtx.beginPath();
            vpCtx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            vpCtx.fill();
          }

          if (allSettled) {
            // Pre-draw settled state on container canvas BEFORE removing viewport canvas.
            // Both draws happen in the same rAF callback so the browser paints them
            // atomically — no blank frame between the two canvases.
            ctx.clearRect(0, 0, canvasWidth, canvasHeight);
            for (const p of particles) {
              ctx.globalAlpha = 0.78;
              ctx.fillStyle = p.color;
              ctx.beginPath();
              ctx.arc(p.originX, p.originY, p.size, 0, Math.PI * 2);
              ctx.fill();
            }
            ctx.globalAlpha = 1;

            viewportCanvas?.remove();
            viewportCanvas = null;
            phase = "settled";

            for (const particle of particles) {
              particle.x = particle.originX;
              particle.y = particle.originY;
              particle.vx = 0;
              particle.vy = 0;
            }
          }
        } else {
          // Settled micro-life on container canvas
          ctx.clearRect(0, 0, canvasWidth, canvasHeight);
          const t = frame * 0.016; // ~seconds at 60fps

          for (const particle of particles) {
            const jx =
              Math.sin(t * particle.jitterFreq * Math.PI * 2 + particle.jitterPhase) * 0.3;
            const jy =
              Math.cos(t * particle.jitterFreq * 0.72 * Math.PI * 2 + particle.jitterPhase) * 0.3;

            const px = particle.originX + jx;
            const py = particle.originY + jy;

            let opacity = 0.78 + Math.sin(t * 0.9 + particle.jitterPhase) * 0.08;

            if (particle.isSparkle) {
              const pulse = Math.sin(t * 0.35 + particle.sparklePhase);
              if (pulse > 0.88) {
                opacity = Math.min(1, opacity + (pulse - 0.88) * 8);
              }
            }

            ctx.globalAlpha = Math.max(0, Math.min(1, opacity));
            ctx.fillStyle = particle.color;
            ctx.beginPath();
            ctx.arc(px, py, particle.size, 0, Math.PI * 2);
            ctx.fill();
          }
        }

        animationFrameId = requestAnimationFrame(animate);
      };

      animate();
    };

    void render();
    resizeObserver = new ResizeObserver(() => {
      void render();
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(animationFrameId);
      resizeObserver?.disconnect();
      viewportCanvas?.remove();
    };
  }, [animationReady, color, density, fontSize, reducedMotion, seed, spread, text]);

  return (
    <div ref={containerRef} className={`scatter-text-shell ${className ?? ""}`}>
      <span
        className={`scatter-text-anchor ${
          reducedMotion || fallbackVisible ? "scatter-text-visible" : ""
        }`}
      >
        {text}
      </span>
      {reducedMotion ? null : (
        <canvas ref={canvasRef} className="scatter-text-canvas" aria-hidden="true" />
      )}
    </div>
  );
}
