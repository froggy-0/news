"use client";

import { useEffect, useRef, useState } from "react";
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

export function ScatterText({
  text,
  className,
  color = "#FFFFFF",
  fontSize = 56,
}: {
  text: string;
  className?: string;
  color?: string;
  fontSize?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isInView = useInView(containerRef, { once: true, margin: "-100px" });
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => setReducedMotion(mediaQuery.matches);
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (reducedMotion || !canvasRef.current || !containerRef.current) {
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) {
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    let animationFrameId = 0;
    let resizeObserver: ResizeObserver | null = null;

    const render = async () => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect || !ctx || !canvasRef.current) {
        return;
      }

      const targetWidth = Math.max(260, Math.round(rect.width) - 20);
      const tempCanvas = document.createElement("canvas");
      const tempCtx = tempCanvas.getContext("2d", { willReadFrequently: true });
      if (!tempCtx) {
        return;
      }

      let resolvedFontSize = fontSize;
      tempCtx.font = `900 ${resolvedFontSize}px Pretendard, Inter, sans-serif`;
      const initialWidth = tempCtx.measureText(text).width;
      if (initialWidth > targetWidth) {
        const scale = targetWidth / initialWidth;
        resolvedFontSize = Math.max(30, Math.floor(fontSize * scale));
        tempCtx.font = `900 ${resolvedFontSize}px Pretendard, Inter, sans-serif`;
      }

      const measuredWidth = tempCtx.measureText(text).width;
      const canvasWidth = Math.max(targetWidth + 120, Math.ceil(measuredWidth) + 120);
      const canvasHeight = Math.max(180, Math.round(resolvedFontSize * 2.8));
      const gap = 1.15;
      const spreadX = Math.max(240, canvasWidth * 0.75);
      const spreadY = Math.max(180, canvasHeight * 1.05);

      canvas.width = canvasWidth * dpr;
      canvas.height = canvasHeight * dpr;
      canvas.style.width = `${canvasWidth}px`;
      canvas.style.height = `${canvasHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const particles: Particle[] = [];
      const offscreenCanvas = document.createElement("canvas");
      const offscreenCtx = offscreenCanvas.getContext("2d", { willReadFrequently: true });
      if (!offscreenCtx) {
        return;
      }

      offscreenCanvas.width = canvasWidth;
      offscreenCanvas.height = canvasHeight;
      offscreenCtx.clearRect(0, 0, canvasWidth, canvasHeight);
      offscreenCtx.font = `900 ${resolvedFontSize}px Pretendard, Inter, sans-serif`;
      offscreenCtx.fillStyle = color;
      offscreenCtx.textAlign = "center";
      offscreenCtx.textBaseline = "middle";
      offscreenCtx.fillText(text, canvasWidth / 2, canvasHeight / 2);

      const pixels = offscreenCtx.getImageData(0, 0, canvasWidth, canvasHeight).data;

      for (let y = 0; y < canvasHeight; y += gap) {
        for (let x = 0; x < canvasWidth; x += gap) {
          const index = (Math.floor(y) * canvasWidth + Math.floor(x)) * 4;
          if (pixels[index + 3] > 128) {
            particles.push({
              x: x + (Math.random() * spreadX - spreadX / 2),
              y: y + (Math.random() * spreadY - spreadY / 2),
              originX: x,
              originY: y,
              color,
              size: Math.random() * 0.8 + 0.4,
              ease: Math.random() * 0.05 + 0.018,
              active: true,
            });
          }
        }
      }

      const animate = () => {
        ctx.clearRect(0, 0, canvasWidth, canvasHeight);

        particles.forEach((particle) => {
          if (isInView && particle.active) {
            const dx = particle.originX - particle.x;
            const dy = particle.originY - particle.y;
            const distance = Math.sqrt(dx * dx + dy * dy);

            particle.x += dx * particle.ease;
            particle.y += dy * particle.ease;

            if (distance < 0.12) {
              particle.x = particle.originX;
              particle.y = particle.originY;
              particle.active = false;
            }
          }

          const distFromOrigin = Math.sqrt(
            (particle.originX - particle.x) ** 2 + (particle.originY - particle.y) ** 2,
          );
          const opacity = isInView ? Math.min(1, 2.4 - distFromOrigin / 150) : 0;

          ctx.globalAlpha = opacity;
          ctx.fillStyle = particle.color;
          ctx.shadowBlur = particle.active && Math.random() > 0.992 ? 4 : 0;
          ctx.shadowColor = "white";
          ctx.beginPath();
          ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
          ctx.fill();
        });

        animationFrameId = requestAnimationFrame(animate);
      };

      await document.fonts.ready;
      cancelAnimationFrame(animationFrameId);
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
  }, [color, fontSize, isInView, reducedMotion, text]);

  return (
    <div ref={containerRef} className={`scatter-text-shell ${className ?? ""}`}>
      <span className={`scatter-text-anchor ${reducedMotion ? "scatter-text-visible" : ""}`}>
        {text}
      </span>
      {reducedMotion ? null : <canvas ref={canvasRef} className="scatter-text-canvas" aria-hidden="true" />}
    </div>
  );
}
