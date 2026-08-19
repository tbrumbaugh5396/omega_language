// Nodes you play.
//
// A simulation becomes a game the moment it reads the keyboard, and the
// keyboard arrives the way everything else does: as a texture, `u_keys`,
// 256 columns by 3 rows, bound by the host in every pass that declares it.
// So a game node is a sim node with one more uniform. Its state lives where
// a sim's does — in its own last frame — and it is held to a CPU
// integration of the same equations, driven by the same key presses.
//
// The convention that makes a texel a register: the state is kept in the
// pixel at (0,0), and every other pixel reads it and draws. One texture
// carries the game and the picture of the game, which is how Shadertoy games
// have always done it and why this is one node rather than two.

import { defineNode, addNode } from "./render-graph.js";
import { KEY } from "./keyboard.js";

defineNode(`// A ship. Left and right turn it, up thrusts, and it wraps at the edges.
// The position, velocity and heading live in the texel at the bottom-left
// corner of this node's own last frame; every other texel reads that one and
// draws. Arrow keys, or WASD.
// @node game.ship
// @module 07-shaders
// @alpha
// @pass
// @precision float
uniform sampler2D in0;      // @help last frame — wire this node's own output back here
uniform vec2 in0_size;
uniform sampler2D u_keys;
uniform float thrust;       // @range 0 0.02 @default 0.006 @help acceleration per frame, in screen heights
uniform float turn;         // @range 0 0.3 @default 0.09 @help radians per frame
uniform float drag;         // @range 0.9 1 @default 0.985 @help velocity kept each frame
uniform float size;         // @range 0.02 0.2 @default 0.06 @help ship length, in screen heights
uniform vec3 hull;          // @color @default #f4efe6
uniform vec3 flame;         // @color @default #ff7a3d

// The register: x, y in screen heights (aspect-corrected, like p), vx, vy.
// The heading is kept one texel to the right — as a *count* of turns rather
// than an angle, because a half-float texel holds an integer exactly and an
// angle only to a thousandth, and a thousandth a frame is a drift you can see.
vec4 reg()   { return texture2D(in0, vec2(0.5, 0.5) / in0_size); }
float turns() { return texture2D(in0, vec2(1.5, 0.5) / in0_size).r; }
// Signed distance to the line a→b, positive on the left; three of these make
// a triangle.
float hp(vec2 q, vec2 a, vec2 b) { vec2 e = b - a; return (e.x * (q.y - a.y) - e.y * (q.x - a.x)) / length(e); }

float left  = max(keyDown(u_keys, ${KEY.left}.0),  keyDown(u_keys, ${KEY.a}.0));
float right = max(keyDown(u_keys, ${KEY.right}.0), keyDown(u_keys, ${KEY.d}.0));
float up    = max(keyDown(u_keys, ${KEY.up}.0),    keyDown(u_keys, ${KEY.w}.0));

float aspect = in0_size.x / in0_size.y;
vec4 s = frame == 0 ? vec4(0.0) : reg();
float n = (frame == 0 ? 0.0 : turns()) + (left - right);
float h = 1.5707963 + n * turn;
vec2 dir = vec2(cos(h), sin(h));
vec2 vel = (s.zw + dir * thrust * up) * drag;
vec2 pos = s.xy + vel;
// Wrap: p runs -aspect..aspect across and -1..1 up.
pos.x = mod(pos.x + aspect, 2.0 * aspect) - aspect;
pos.y = mod(pos.y + 1.0, 2.0) - 1.0;

vec2 texel = floor(gl_FragCoord.xy);
vec4 out_;
if (texel == vec2(0.0)) {
  out_ = vec4(pos, vel);                       // the register
} else if (texel == vec2(1.0, 0.0)) {
  out_ = vec4(n, 0.0, 0.0, 1.0);               // the heading, as a count of turns
} else {
  // Draw the ship where the register says it is, facing the way it faces.
  vec2 q = rot(h) * (p - pos);       // rot() turns by minus its argument, so this is R(-h)
  vec2 nose = vec2(size, 0.0), tl = vec2(-size * 0.5, size * 0.45), tr = vec2(-size * 0.5, -size * 0.45);
  float d = -min(min(hp(q, nose, tl), hp(q, tl, tr)), hp(q, tr, nose));
  float body = aa(d);
  // Exhaust, only when thrusting: a flicker behind the tail.
  float ex = up * aa(length(q - vec2(-size * 0.7 - 0.35 * size * hash21(vec2(frame, 1.0)), 0.0)) - size * 0.16);
  vec3 col = mix(flame, hull, body);
  out_ = vec4(col, max(body, ex));
}
out_`);

defineNode(`// The keyboard, as the picture it is: one column per key code, three rows.
// Held keys light the bottom row, a press lights the middle row for one
// frame, and a toggle stays lit. Arrows are columns 37 to 40. Mostly for
// seeing that the host is actually feeding keys to the graph.
// @node input.keys
// @module 07-shaders
uniform sampler2D u_keys;
uniform vec3 lit;    // @color @default #6ee7c8
uniform vec3 unlit;  // @color @default #1b2b4b

vec2 cell = vec2(floor(uv.x * 256.0), floor(uv.y * 3.0));
float v = texture2D(u_keys, (cell + 0.5) / vec2(256.0, 3.0)).r;
vec2 f = fract(uv * vec2(256.0, 3.0));
float gap = step(0.08, f.x) * step(0.08, f.y);
mix(unlit * 0.6, mix(unlit, lit, v), gap)`);

defineNode(`// A ship, drawn where it is told. This node keeps nothing: its position,
// heading and whether it is burning are parameters, and the graph that owns
// it writes them as expressions over prev() and key(). That makes this the
// View of a Model–Update–View, and only the View — the model is numbers in
// the document, the update is the expressions, and the shader is a pure
// function of both.
// @node game.shipView
// @module 07-shaders
// @alpha
uniform vec2  pos;          // @pad @range -2 2 @default 0 0 @help where, in screen heights, centred
uniform float heading;      // @range -10 10 @default 1.5707963 @help radians, anticlockwise from +x
uniform float burning;      // @toggle @default 0 @help draw the exhaust
uniform float size;         // @range 0.02 0.3 @default 0.06 @help ship length, in screen heights
uniform vec3  hull;         // @color @default #f4efe6
uniform vec3  flame;        // @color @default #ff7a3d

float hp(vec2 q, vec2 a, vec2 b) { vec2 e = b - a; return (e.x * (q.y - a.y) - e.y * (q.x - a.x)) / length(e); }

vec2 q = rot(heading) * (p - pos);   // rot() turns by minus its argument
vec2 nose = vec2(size, 0.0), tl = vec2(-size * 0.5, size * 0.45), tr = vec2(-size * 0.5, -size * 0.45);
float d = -min(min(hp(q, nose, tl), hp(q, tl, tr)), hp(q, tr, nose));
float body = aa(d);
float ex = burning * aa(length(q - vec2(-size * 0.7 - 0.35 * size * hash21(vec2(frame, 1.0)), 0.0)) - size * 0.16);
vec4(mix(flame, hull, body), max(body, ex))`);

export const GAME_NODES = ["game.ship", "game.shipView", "input.keys"];

/**
 * The ship as data: a node named `ship` whose parameters are its model and
 * whose expressions are its update. Left/right (or A/D) turn, up (or W)
 * thrusts, and it wraps. `P` is the same constants shipStep takes, so the
 * self-test can hold this graph to that function — and it should be exact,
 * because both are the same arithmetic in the same doubles.
 */
export function shipAsData(graph, P = { thrust: 0.006, turn: 0.09, drag: 0.985 }, extra = {}) {
  const thrustOn = "max(key(38), key(87))";
  return addNode(graph, "game.shipView", {
    // The model. `value` is the state before the first frame.
    turns:   { expr: 'prev("turns") + key(37) - key(39) + key(65) - key(68)', value: [0] },
    heading: { expr: `pi / 2 + ch("turns") * ${P.turn}` },
    vel:     { expr: [`(prev("vel", 0) + cos(ch("heading")) * ${P.thrust} * ${thrustOn}) * ${P.drag}`,
                      `(prev("vel", 1) + sin(ch("heading")) * ${P.thrust} * ${thrustOn}) * ${P.drag}`],
               value: [0, 0] },
    pos:     { expr: ['wrap(prev("pos", 0) + ch("vel", 0), aspect)',
                      'wrap(prev("pos", 1) + ch("vel", 1), 1)'], value: [0, 0] },
    burning: { expr: thrustOn },
    ...(extra.params || {}),
  }, [], { name: extra.name || "ship" });
}

// ------------------------------------------------------------------ reference

/**
 * The ship's equations on the CPU, for the self-test. `keys(frame)` answers
 * { left, right, up } for each frame; the state is the register the shader
 * keeps. Same order of operations, same wrap.
 */
export function shipStep(state, keysAt, frame, { thrust, turn, drag, aspect }) {
  const k = keysAt(frame);
  let { x, y, vx, vy, n } = frame === 0 ? { x: 0, y: 0, vx: 0, vy: 0, n: 0 } : state;
  n += (k.left ? 1 : 0) - (k.right ? 1 : 0);
  const h = Math.PI / 2 + n * turn;
  const up = k.up ? 1 : 0;
  vx = (vx + Math.cos(h) * thrust * up) * drag;
  vy = (vy + Math.sin(h) * thrust * up) * drag;
  x += vx; y += vy;
  const wrap = (v, r) => ((((v + r) % (2 * r)) + 2 * r) % (2 * r)) - r;
  x = wrap(x, aspect); y = wrap(y, 1);
  return { x, y, vx, vy, n, h };
}
