// The scopes, as render-graph nodes.
//
// This is where the two roadmaps meet. A spectrum is a picture; the app has a
// render graph for pictures, a schema in a comment, fusion, ejection and a
// self-test that holds every node to a number. So a scope is not a bespoke
// canvas routine — it is a node like any other, taking the analysis as a
// texture and drawing it.
//
// audio-scopes.js packs the measurement into one row of pixels. These read it.

import { defineNode } from "./render-graph.js";

defineNode(`// A spectrum: one packed row in, a plot out. Log in frequency because
// hearing is, and a decibel floor because the interesting part is the top 90 dB.
// @node scope.spectrum
// @module 05-display
// @alpha
uniform sampler2D in0;      // the packed analysis, one row
uniform vec3  ink;          // @color @default 0.42 0.92 0.75 @help the trace
uniform vec3  paper;        // @color @default 0.04 0.05 0.09 @help behind it
uniform float grid;         // @range 0 1 @default 0.35 @help how visible the decade lines are
uniform float thickness;    // @range 0.5 6 @default 1.5 @help the trace, in pixels

float v = texture2D(in0, vec2(uv.x, 0.5)).r;
float px = 1.0 / u_resolution.y;
// The trace is a distance to the curve, so it is one pixel wide at any size —
// the same reason every shape in this app is a distance rather than a mask.
float d = abs(uv.y - v);
float line = 1.0 - smoothstep(0.0, thickness * px, d);
float fill = smoothstep(0.0, thickness * px, v - uv.y) * 0.16;
// Decade lines, at each power of ten across the log axis.
float decades = fract(uv.x * 3.0);
float g = (1.0 - smoothstep(0.0, 1.5 / u_resolution.x, min(decades, 1.0 - decades))) * grid;
vec3 col = mix(paper, vec3(0.5), g);
col = mix(col, ink, max(line, fill));
vec4(col, 1.0)`);

defineNode(`// A waveform, from a row holding each column's highest and lowest sample.
// @node scope.wave
// @module 05-display
// @alpha
uniform sampler2D in0;      // r is the top of the column, g the bottom
uniform vec3  ink;          // @color @default 0.42 0.92 0.75 @help the waveform
uniform vec3  paper;        // @color @default 0.04 0.05 0.09 @help behind it
uniform float centre;       // @range 0 1 @default 0.35 @help how visible the zero line is

vec2 c = texture2D(in0, vec2(uv.x, 0.5)).rg;
float hi = c.r, lo = c.g;
float inside = step(lo, uv.y) * step(uv.y, hi);
float zero = (1.0 - smoothstep(0.0, 1.5 / u_resolution.y, abs(uv.y - 0.5))) * centre;
vec3 col = mix(paper, vec3(0.5), zero);
col = mix(col, ink, inside);
vec4(col, 1.0)`);

defineNode(`// Correlation, as the one number a mix engineer actually acts on: how much
// of this will survive being folded to mono. −1 cancels, +1 is mono already.
// @node scope.correlation
// @module 03-additive-subtractive
// @alpha
uniform float value;        // @range -1 1 @default 1 @help the correlation coefficient
uniform vec3  good;         // @color @default 0.42 0.92 0.75 @help at or above zero
uniform vec3  bad;          // @color @default 0.95 0.44 0.36 @help below zero
uniform vec3  paper;        // @color @default 0.04 0.05 0.09 @help behind it

// A bar from the centre: right for positive, left for negative.
float x = uv.x * 2.0 - 1.0;
float within = step(min(0.0, value), x) * step(x, max(0.0, value));
float band = step(0.3, uv.y) * step(uv.y, 0.7);
float ticks = 1.0 - smoothstep(0.0, 2.0 / u_resolution.x, abs(fract(uv.x * 4.0 + 0.5) - 0.5) * 2.0);
vec3 col = mix(paper, vec3(0.28), ticks * 0.5);
col = mix(col, value < 0.0 ? bad : good, within * band);
vec4(col, 1.0)`);

defineNode(`// A spectrogram: time across, frequency up, loudness as colour. The history
// is a ring, so nothing scrolls — the newest column is wherever the head is,
// and this unwraps it.
// @node scope.spectrogram
// @module 05-display
// @alpha
uniform sampler2D in0;      // the ring: one column per frame
uniform float head;         // @range 0 1 @default 0 @hidden where the newest column sits
uniform float gain;         // @range 0.5 4 @default 1.6 @help how hard the colour is driven
uniform vec3  cool;         // @color @default 0.04 0.05 0.09 @help the quiet end
uniform vec3  warm;         // @color @default 0.98 0.86 0.45 @help the loud end

// Unwrap: the column just left of the head is the newest, so it belongs at
// the right-hand edge.
float x = fract(uv.x + head);
float v = clamp(texture2D(in0, vec2(x, 1.0 - uv.y)).r * gain, 0.0, 1.0);
// Through a warm ramp rather than a raw grey: two colours make a level
// readable at a glance where one only makes it visible.
vec3 mid = vec3(0.29, 0.55, 0.62);
vec3 col = v < 0.5 ? mix(cool, mid, v * 2.0) : mix(mid, warm, (v - 0.5) * 2.0);
vec4(col, 1.0)`);
