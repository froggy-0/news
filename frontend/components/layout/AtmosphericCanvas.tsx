"use client";

import { useEffect, useRef } from "react";

const vertexShaderSource = `
  attribute vec2 position;
  varying vec2 vUv;

  void main() {
    vUv = position * 0.5 + 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
  }
`;

const fragmentShaderSource = `
  precision highp float;

  uniform float uTime;
  uniform vec2 uResolution;
  varying vec2 vUv;

  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

  float noise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
    vec2 i = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod289(i);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
    m = m * m;
    m = m * m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
  }

  float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 5; i++) {
      value += amplitude * noise(p);
      p *= 2.0;
      amplitude *= 0.5;
    }
    return value;
  }

  float fbmLite(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 3; i++) {
      value += amplitude * noise(p);
      p *= 2.0;
      amplitude *= 0.5;
    }
    return value;
  }

  float roundedBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
  }

  void main() {
    float aspect = uResolution.x / uResolution.y;
    vec2 uv = vUv - 0.5;
    uv.x *= aspect;
    float t = uTime;

    float angle = 0.785;
    mat2 rot = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    vec2 p = rot * uv;

    float size = 0.16;
    float radius = 0.04;
    float d = roundedBox(p, vec2(size), radius);
    float mask = 1.0 - smoothstep(-0.001, 0.002, d);

    vec2 drift = vec2(
      fbmLite(p * 2.5 + vec2(t * 0.12, t * 0.08)),
      fbmLite(p * 2.5 + vec2(t * 0.09 + 5.2, t * 0.10 + 1.3))
    );
    vec2 grain = p * 2.0 + drift * 1.5;
    float flow = fbm(grain);

    float eps = 0.005;
    float hx = fbm(grain + vec2(eps, 0.0)) - fbm(grain - vec2(eps, 0.0));
    float hy = fbm(grain + vec2(0.0, eps)) - fbm(grain - vec2(0.0, eps));
    vec3 normal = normalize(vec3(-hx * 0.5, -hy * 0.5, 0.5));
    vec3 view = vec3(0.0, 0.0, 1.0);

    vec2 lightPos = vec2(sin(t * 0.25) * 0.10, cos(t * 0.20) * 0.08);
    float lightDist = length(p - lightPos);
    float lightRadius = 0.09 + sin(t * 0.4) * 0.02;
    float lightAtten = exp(-lightDist * lightDist / (lightRadius * lightRadius * 0.5));
    vec3 lightDir = normalize(vec3(lightPos - p, 0.8));
    vec3 halfDir = normalize(lightDir + view);
    float spec = pow(max(dot(normal, halfDir), 0.0), 40.0);
    float sharpSpec = pow(max(dot(normal, halfDir), 0.0), 200.0);

    vec2 warmPos = vec2(cos(t * 0.18 + 3.0) * 0.12, sin(t * 0.15 + 1.5) * 0.10);
    float warmDist = length(p - warmPos);
    float warmAtten = exp(-warmDist * warmDist / (0.06 * 0.06));
    vec3 warmDir = normalize(vec3(warmPos - p, 0.7));
    vec3 warmHalf = normalize(warmDir + view);
    float warmSpec = pow(max(dot(normal, warmHalf), 0.0), 60.0);

    float shift = flow * 2.0 + t * 0.15;
    vec3 tint = vec3(
      sin(shift) * 0.5 + 0.5,
      sin(shift + 2.094) * 0.5 + 0.5,
      sin(shift + 4.189) * 0.5 + 0.5
    );
    tint = mix(tint, vec3(0.02, 0.16, 0.20), 0.65);

    vec3 surface = vec3(0.002, 0.006, 0.008);
    surface += tint * 0.28 * lightAtten;
    surface += vec3(0.00, 0.75, 0.90) * spec * lightAtten * 0.55;
    surface += vec3(0.80, 0.96, 1.00) * sharpSpec * lightAtten * 1.20;
    surface += vec3(0.58, 0.30, 0.02) * warmSpec * warmAtten * 0.55;
    surface += vec3(0.65, 0.40, 0.04) * warmAtten * 0.09;
    surface += vec3(0.02, 0.08, 0.12) * pow(1.0 - max(dot(normal, view), 0.0), 4.0) * 0.14;

    float rim = exp(-abs(d) * 80.0) * 0.18;
    float edgeAngle = atan(p.y, p.x);
    vec3 rimColor = mix(
      vec3(0.00, 0.22, 0.28),
      vec3(0.30, 0.16, 0.02),
      sin(edgeAngle * 2.0 + t * 0.3) * 0.5 + 0.5
    );

    vec2 mirrorP = rot * (uv + vec2(0.0, 0.36));
    float mirrorD = roundedBox(mirrorP, vec2(size * 0.85), radius);
    float mirrorMask = 1.0 - smoothstep(-0.001, 0.002, mirrorD);
    float mirrorFade = smoothstep(0.0, 0.18, -(uv.y + 0.08));

    vec3 color = vec3(0.0);
    color += surface * mask;
    color += rimColor * rim;
    color += surface * 0.15 * mirrorFade * mirrorMask * (1.0 - mask);

    gl_FragColor = vec4(color, 1.0);
  }
`;

function createShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error(gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createProgram(canvas: HTMLCanvasElement) {
  const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
  if (!gl) return null;

  const vertexShader = createShader(gl, gl.VERTEX_SHADER, vertexShaderSource);
  const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, fragmentShaderSource);
  if (!vertexShader || !fragmentShader) return null;

  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(gl.getProgramInfoLog(program));
    return null;
  }

  gl.useProgram(program);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
    gl.STATIC_DRAW,
  );

  const position = gl.getAttribLocation(program, "position");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

  return {
    gl,
    uResolution: gl.getUniformLocation(program, "uResolution"),
    uTime: gl.getUniformLocation(program, "uTime"),
  };
}

export function AtmosphericCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const renderer = createProgram(canvas);
    if (!renderer) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const startedAt = performance.now();

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = window.innerWidth;
      const height = window.innerHeight;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      renderer.gl.viewport(0, 0, canvas.width, canvas.height);
    };

    const render = () => {
      const time = reduceMotion ? 0.0 : (performance.now() - startedAt) / 1000;
      renderer.gl.uniform1f(renderer.uTime, time);
      renderer.gl.uniform2f(renderer.uResolution, canvas.width, canvas.height);
      renderer.gl.drawArrays(renderer.gl.TRIANGLE_STRIP, 0, 4);
      if (!reduceMotion) frameRef.current = requestAnimationFrame(render);
    };

    resize();
    render();
    window.addEventListener("resize", resize);

    return () => {
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0 opacity-[0.28] will-change-transform"
      aria-hidden="true"
    />
  );
}
