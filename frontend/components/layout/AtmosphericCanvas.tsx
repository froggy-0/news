"use client";

import { useEffect, useRef } from "react";

function drawFrame(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  t: number,
) {
  ctx.clearRect(0, 0, w, h);

  const cx = w * 0.5;
  const cy = h * 0.46;
  const baseRadius = Math.min(w, h) * 0.3;
  const pulse = 1 + Math.sin(t * 0.0007) * 0.035;
  const r = baseRadius * pulse;

  // ── outer atmospheric haze ───────────────────────────────────────────────
  const haze = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 3.2);
  haze.addColorStop(0, "rgba(190, 85, 18, 0.20)");
  haze.addColorStop(0.3, "rgba(140, 52, 10, 0.12)");
  haze.addColorStop(0.6, "rgba(90, 28, 5, 0.06)");
  haze.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = haze;
  ctx.fillRect(0, 0, w, h);

  // ── sphere body (highlight offset up-left for 3-D illusion) ─────────────
  const hx = cx - r * 0.2;
  const hy = cy - r * 0.24;
  const sphere = ctx.createRadialGradient(hx, hy, 0, cx, cy, r);
  sphere.addColorStop(0.0, "rgba(255, 168, 48, 0.96)");
  sphere.addColorStop(0.08, "rgba(230, 115, 28, 0.88)");
  sphere.addColorStop(0.22, "rgba(185, 68, 14, 0.76)");
  sphere.addColorStop(0.42, "rgba(130, 38, 8, 0.60)");
  sphere.addColorStop(0.62, "rgba(78, 18, 4, 0.42)");
  sphere.addColorStop(0.82, "rgba(36, 8, 2, 0.22)");
  sphere.addColorStop(1.0, "rgba(0,0,0,0)");

  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.clip();
  ctx.fillStyle = sphere;
  ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
  ctx.restore();

  // ── rim light (bottom-right) ─────────────────────────────────────────────
  const rimX = cx + r * 0.58;
  const rimY = cy + r * 0.48;
  const rim = ctx.createRadialGradient(rimX, rimY, 0, rimX, rimY, r * 0.55);
  rim.addColorStop(0, "rgba(200, 110, 30, 0.18)");
  rim.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = rim;
  ctx.fillRect(0, 0, w, h);

  // ── nebula wisps (3 slow-rotating arcs) ─────────────────────────────────
  for (let i = 0; i < 3; i++) {
    const angle = t * 0.000055 * (i % 2 === 0 ? 1 : -0.7) + (i * Math.PI * 2) / 3;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle) * 0.55;
    const wx = cx + dx * r * 0.72;
    const wy = cy + dy * r * 0.72;
    const wispR = r * (0.5 + i * 0.12);
    const wisp = ctx.createRadialGradient(wx, wy, 0, wx, wy, wispR);
    const alpha = 0.09 + Math.sin(t * 0.0005 + i * 1.8) * 0.04;
    wisp.addColorStop(0, `rgba(170, 62, 12, ${alpha})`);
    wisp.addColorStop(0.5, `rgba(110, 34, 6, ${alpha * 0.5})`);
    wisp.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = wisp;
    ctx.fillRect(0, 0, w, h);
  }

  // ── inner bright core (tiny, shimmers) ───────────────────────────────────
  const shimmer = 0.7 + Math.sin(t * 0.0018) * 0.3;
  const core = ctx.createRadialGradient(hx, hy, 0, hx, hy, r * 0.18);
  core.addColorStop(0, `rgba(255, 210, 120, ${0.55 * shimmer})`);
  core.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = core;
  ctx.fillRect(0, 0, w, h);
}

export function AtmosphericCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    function resize() {
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      if (ctx) ctx.scale(dpr, dpr);
    }

    resize();
    window.addEventListener("resize", resize);

    function loop(t: number) {
      if (!canvas || !ctx) return;
      drawFrame(ctx, window.innerWidth, window.innerHeight, t);
      rafRef.current = requestAnimationFrame(loop);
    }
    rafRef.current = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0 opacity-[0.42] will-change-transform"
      aria-hidden="true"
    />
  );
}
