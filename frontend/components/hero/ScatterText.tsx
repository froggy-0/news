"use client";

import React, { useEffect, useRef, useState } from "react";
import { useInView } from "motion/react";

type Particle = {
  x: number;
  y: number;
  originX: number;
  originY: number;
  color: string;
  size: number;
  ease: number;
  active: boolean;
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
      originX: point.x,
      originY: point.y,
      color,
      size: 0.45 + random() * 0.7,
      ease: 0.024 + random() * 0.028,
      active: true,
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
  const isInView = useInView(containerRef, { once: true, margin: "-80px" });
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

    const timer = window.setTimeout(() => {
      setAnimationReady(true);
    }, Math.max(120, Math.round(durationMs * 0.4)));

    return () => window.clearTimeout(timer);
  }, [durationMs, isInView, reducedMotion]);

  useEffect(() => {
    if (reducedMotion || !canvasRef.current || !containerRef.current) {
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

    const render = async () => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) {
        return;
      }

      await document.fonts.ready;

      const dpr = window.devicePixelRatio || 1;
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

      canvas.width = canvasWidth * dpr;
      canvas.height = canvasHeight * dpr;
      canvas.style.width = `${canvasWidth}px`;
      canvas.style.height = `${canvasHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

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
      const gap = 1.25;

      for (let y = 0; y < canvasHeight; y += gap) {
        for (let x = 0; x < canvasWidth; x += gap) {
          const index = (Math.floor(y) * canvasWidth + Math.floor(x)) * 4;
          if (pixels[index + 3] > 132) {
            points.push({ x, y });
          }
        }
      }

      const particles = buildSeededParticles({
        points,
        seed,
        color,
        spreadX: canvasWidth * spread,
        spreadY: canvasHeight * (spread * 0.82),
        density,
      });

      setFallbackVisible(false);
      cancelAnimationFrame(animationFrameId);

      const animate = () => {
        ctx.clearRect(0, 0, canvasWidth, canvasHeight);

        for (const particle of particles) {
          if (animationReady && particle.active) {
            const dx = particle.originX - particle.x;
            const dy = particle.originY - particle.y;
            const distance = Math.sqrt(dx * dx + dy * dy);

            particle.x += dx * particle.ease;
            particle.y += dy * particle.ease;

            if (distance < 0.18) {
              particle.x = particle.originX;
              particle.y = particle.originY;
              particle.active = false;
            }
          }

          const distanceFromOrigin = Math.sqrt(
            (particle.originX - particle.x) ** 2 + (particle.originY - particle.y) ** 2,
          );
          const opacity = animationReady
            ? Math.max(0.22, Math.min(1, 1.4 - distanceFromOrigin / 90))
            : 0;

          ctx.globalAlpha = opacity;
          ctx.fillStyle = particle.color;
          ctx.beginPath();
          ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
          ctx.fill();
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
      {reducedMotion ? null : <canvas ref={canvasRef} className="scatter-text-canvas" aria-hidden="true" />}
    </div>
  );
}
