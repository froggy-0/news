"use client";

import { useEffect, useRef } from "react";

type FieldProps = {
  seedInput: string;
  significantCount: number;
  topLoading: number;
  qualityStatus: string;
};

function hashSeed(input: string): number {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function mulberry32(seed: number) {
  return () => {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function AnalysisSignalField({
  seedInput,
  significantCount,
  topLoading,
  qualityStatus,
}: FieldProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const context = canvas.getContext("2d");
    if (!context) return;

    const random = mulberry32(hashSeed(`${seedInput}:${significantCount}:${topLoading}`));
    let frameId = 0;
    let tick = 0;

    const draw = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, rect.width, rect.height);

      const polarity = topLoading >= 0 ? 1 : -1;
      const qualityDrag =
        qualityStatus === "critical" ? 0.38 : qualityStatus === "degraded" ? 0.58 : 0.82;
      const particleCount = Math.min(96, 32 + significantCount * 10);
      const amplitude = 16 + Math.min(Math.abs(topLoading), 1) * 48;

      context.globalCompositeOperation = "lighter";
      for (let i = 0; i < particleCount; i += 1) {
        const baseX = random() * rect.width;
        const baseY = random() * rect.height;
        const drift = reduceMotion ? 0 : tick * (0.002 + random() * 0.002);
        const angle = (baseX * 0.006 + baseY * 0.004 + drift) * polarity;
        const x = baseX + Math.cos(angle) * amplitude * qualityDrag;
        const y = baseY + Math.sin(angle * 1.7) * amplitude * 0.45;
        const radius = 0.55 + random() * 1.6;
        const alpha = 0.025 + random() * 0.055;

        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        context.fillStyle =
          polarity > 0
            ? `rgba(0, 255, 255, ${alpha})`
            : `rgba(255, 107, 107, ${alpha})`;
        context.fill();

        if (i % 3 === 0) {
          context.beginPath();
          context.moveTo(x, y);
          context.lineTo(
            x + Math.cos(angle + Math.PI / 2) * (18 + significantCount * 2),
            y + Math.sin(angle + Math.PI / 2) * (18 + significantCount * 2),
          );
          context.strokeStyle = `rgba(255, 255, 255, ${alpha * 0.35})`;
          context.lineWidth = 0.5;
          context.stroke();
        }
      }

      tick += 1;
      if (!reduceMotion) frameId = window.requestAnimationFrame(draw);
    };

    draw();
    return () => window.cancelAnimationFrame(frameId);
  }, [qualityStatus, seedInput, significantCount, topLoading]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full opacity-70"
    />
  );
}
