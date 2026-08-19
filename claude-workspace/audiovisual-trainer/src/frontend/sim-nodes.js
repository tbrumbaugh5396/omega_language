// Nodes that remember.
//
// Nothing in here is special to the compiler. Each is an ordinary node with
// an ordinary sampler input; what makes it a simulation is that the graph
// wires that input *back* to the node's own output, so every frame reads the
// one before. The runner keeps that frame in a half-float texture between
// runs. That is the whole mechanism, and it is the same one Shadertoy's
// buffers use — a rule from the last frame to the next, and somewhere to put
// the last frame.
//
// The convention the three sims share: in0 is last frame (wire it back), in1
// is a seed, read only on frame 0. So the same graph that runs the sim also
// starts it, and "reset" is nothing more than forgetting.

import { defineNode } from "./render-graph.js";

defineNode(`// Persistence: what is there now, laid over what was there last frame, faded.
// Motion trails, phosphor, a long exposure — wire in1 back to this node.
// @node feedback.trail
// @module 07-shaders
// @alpha
uniform sampler2D in0;   // @help this frame
uniform sampler2D in1;   // @help last frame — wire this node's own output back here
uniform float decay;     // @range 0 1 @default 0.9 @help how much of last frame survives

vec4 fresh = texture2D(in0, uv);
vec4 prev  = texture2D(in1, uv);
mix(fresh, prev, decay)`);

defineNode(`// Conway's Life. Every cell looks at its eight neighbours in last frame and
// decides; the rule is three lines and the behaviour is not. Dead beyond the
// edge. Frame 0 reads the seed instead.
// @node sim.life
// @module 07-shaders
// @pass
uniform sampler2D in0;     // @help last generation — wire this node's own output back here
uniform vec2 in0_size;
uniform sampler2D in1;     // @help the seed, read on frame 0: anything brighter than half is alive

float cell(vec2 o) {
  vec2 q = uv * in0_size + o;
  if (q.x < 0.0 || q.y < 0.0 || q.x >= in0_size.x || q.y >= in0_size.y) return 0.0;
  return step(0.5, texture2D(in0, q / in0_size).r);
}
float live;
if (frame == 0) {
  live = step(0.5, texture2D(in1, uv).r);
} else {
  float n = cell(vec2(-1.0, -1.0)) + cell(vec2(0.0, -1.0)) + cell(vec2(1.0, -1.0))
          + cell(vec2(-1.0,  0.0))                          + cell(vec2(1.0,  0.0))
          + cell(vec2(-1.0,  1.0)) + cell(vec2(0.0,  1.0)) + cell(vec2(1.0,  1.0));
  float me = cell(vec2(0.0));
  live = (n == 3.0 || (me > 0.5 && n == 2.0)) ? 1.0 : 0.0;
}
vec3(live)`);

defineNode(`// Gray–Scott reaction–diffusion: two chemicals, one eats the other, both
// spread. u in red, v in green. Frame 0 is all u with v wherever the seed is
// bright. The nine-point Laplacian and the clamped edge are the same ones the
// CPU reference uses, so the two can be held against each other.
// @node sim.reactionDiffusion
// @module 07-shaders
// @pass
uniform sampler2D in0;   // @help last state — wire this node's own output back here
uniform vec2 in0_size;
uniform sampler2D in1;   // @help the seed, read on frame 0
uniform float feed;      // @range 0.01 0.1 @default 0.055 @help how fast u is replenished
uniform float kill;      // @range 0.04 0.07 @default 0.062 @help how fast v is removed
uniform float dU;        // @range 0 1 @default 1.0 @help diffusion of u
uniform float dV;        // @range 0 1 @default 0.5 @help diffusion of v
uniform float dt;        // @range 0.1 1 @default 1.0 @help step size

vec2 at(vec2 o) {
  // Clamped, so the edge cell is its own neighbour beyond the edge — which
  // is what CLAMP_TO_EDGE does, and what the reference does on purpose.
  vec2 q = clamp(uv * in0_size + o, vec2(0.5), in0_size - 0.5);
  return texture2D(in0, q / in0_size).rg;
}
vec2 s;
if (frame == 0) {
  s = vec2(1.0, step(0.5, texture2D(in1, uv).r));
} else {
  vec2 c = at(vec2(0.0));
  vec2 lap = -c
    + 0.2  * (at(vec2(-1.0, 0.0)) + at(vec2(1.0, 0.0)) + at(vec2(0.0, -1.0)) + at(vec2(0.0, 1.0)))
    + 0.05 * (at(vec2(-1.0, -1.0)) + at(vec2(1.0, -1.0)) + at(vec2(-1.0, 1.0)) + at(vec2(1.0, 1.0)));
  float uvv = c.x * c.y * c.y;
  s = c + vec2(dU * lap.x - uvv + feed * (1.0 - c.x),
               dV * lap.y + uvv - (feed + kill) * c.y) * dt;
  s = clamp(s, 0.0, 1.0);
}
vec3(s, 0.0)`);

defineNode(`// Look at a two-chemical state as a picture: dark where v has taken over,
// light where u is undisturbed.
// @node sim.view
// @module 07-shaders
uniform sampler2D in0;   // @help a state with u in red and v in green
uniform vec3 light;      // @color @default #f4efe6
uniform vec3 dark;       // @color @default #1b2b4b

vec2 s = texture2D(in0, uv).rg;
mix(dark, light, clamp(s.x - s.y, 0.0, 1.0))`);

export const SIM_NODES = ["feedback.trail", "sim.life", "sim.reactionDiffusion", "sim.view"];

// ------------------------------------------------------------------ references
//
// The CPU implementations the self-test holds the GPU ones to. They are here,
// beside the sketches, so the two stencils are one screen apart and a change
// to one is seen next to the other.

/** One generation of Life on a 0/1 grid, dead beyond the edge. */
export function lifeStep(grid, w, h) {
  const out = new Uint8Array(w * h);
  const at = (x, y) => (x < 0 || y < 0 || x >= w || y >= h ? 0 : grid[y * w + x]);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const n = at(x - 1, y - 1) + at(x, y - 1) + at(x + 1, y - 1)
              + at(x - 1, y)                    + at(x + 1, y)
              + at(x - 1, y + 1) + at(x, y + 1) + at(x + 1, y + 1);
      const me = grid[y * w + x];
      out[y * w + x] = n === 3 || (me && n === 2) ? 1 : 0;
    }
  }
  return out;
}

/** One Gray–Scott step on interleaved [u, v] Float32 state, clamped edges. */
export function grayScottStep(state, w, h, { feed, kill, dU, dV, dt }) {
  const out = new Float32Array(state.length);
  const cl = (v, hi) => (v < 0 ? 0 : v >= hi ? hi - 1 : v);
  const U = (x, y) => state[(cl(y, h) * w + cl(x, w)) * 2];
  const V = (x, y) => state[(cl(y, h) * w + cl(x, w)) * 2 + 1];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const u = U(x, y), v = V(x, y);
      const lu = -u + 0.2 * (U(x - 1, y) + U(x + 1, y) + U(x, y - 1) + U(x, y + 1))
                    + 0.05 * (U(x - 1, y - 1) + U(x + 1, y - 1) + U(x - 1, y + 1) + U(x + 1, y + 1));
      const lv = -v + 0.2 * (V(x - 1, y) + V(x + 1, y) + V(x, y - 1) + V(x, y + 1))
                    + 0.05 * (V(x - 1, y - 1) + V(x + 1, y - 1) + V(x - 1, y + 1) + V(x + 1, y + 1));
      const uvv = u * v * v;
      const i = (y * w + x) * 2;
      out[i]     = Math.min(1, Math.max(0, u + (dU * lu - uvv + feed * (1 - u)) * dt));
      out[i + 1] = Math.min(1, Math.max(0, v + (dV * lv + uvv - (feed + kill) * v) * dt));
    }
  }
  return out;
}
