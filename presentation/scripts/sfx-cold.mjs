// Synthesises the cold-open sound effects into public/assets/sfx/cold-*.wav (mono, 48 kHz, 16-bit):
// a low rising drone, keyboard taps, the hang-up click and typewriter ticks for the caption. No dependencies, seeded noise, reproducible.
// Usage: node scripts/sfx-cold.mjs
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const RATE = 48000;
const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'assets', 'sfx');

let seed = 7;
const rand = () => {
	seed = (seed * 1664525 + 1013904223) >>> 0;
	return seed / 2 ** 32;
};
const noise = () => rand() * 2 - 1;
const buffer = (seconds) => new Float32Array(Math.round(seconds * RATE));

const lowpass = () => {
	let y = 0;
	return (x, hz) => {
		y += (1 - Math.exp((-2 * Math.PI * hz) / RATE)) * (x - y);
		return y;
	};
};

const normalise = (b, peak) => {
	let m = 0;
	for (const v of b) m = Math.max(m, Math.abs(v));
	for (let i = 0; i < b.length; i++) b[i] = (b[i] / (m || 1)) * peak;
	return b;
};

const wav = (b) => {
	const data = Buffer.alloc(b.length * 2);
	b.forEach((v, i) => data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, v)) * 32767), i * 2));
	const h = Buffer.alloc(44);
	h.write('RIFF', 0);
	h.writeUInt32LE(36 + data.length, 4);
	h.write('WAVEfmt ', 8);
	h.writeUInt32LE(16, 16);
	h.writeUInt16LE(1, 20);
	h.writeUInt16LE(1, 22);
	h.writeUInt32LE(RATE, 24);
	h.writeUInt32LE(RATE * 2, 28);
	h.writeUInt16LE(2, 32);
	h.writeUInt16LE(16, 34);
	h.write('data', 36);
	h.writeUInt32LE(data.length, 40);
	return Buffer.concat([h, data]);
};

/** Low drone that swells over 20 s: detuned saws at A1 / E2 through a low-pass that slowly opens, plus rumble. */
const drone = () => {
	const T = 20;
	const b = buffer(T);
	const lp = lowpass();
	const rumble = lowpass();
	const saw = (f, t) => 2 * ((f * t) % 1) - 1;
	for (let i = 0; i < b.length; i++) {
		const t = i / RATE;
		const k = t / T;
		const tone = saw(55, t) + saw(55.4, t) + 0.7 * saw(82.4, t) + 0.5 * saw(110.3, t);
		const swell = Math.min(1, t / 2) * (0.35 + 0.65 * k * k);
		b[i] = swell * (lp(tone, 120 + 900 * k * k) + 2.5 * rumble(noise(), 60));
	}
	return normalise(b, 0.6);
};

/** Keyboard typing: irregular short filtered clicks for 3.5 s, a little faster near the end. */
const keys = () => {
	const b = buffer(3.5);
	let t = 0.05;
	while (t < 3.4) {
		const start = Math.round(t * RATE);
		const len = Math.round(0.018 * RATE);
		const tone = 1800 + rand() * 1500;
		const amp = 0.5 + rand() * 0.5;
		for (let j = 0; j < len && start + j < b.length; j++) {
			const e = Math.exp(-j / (0.003 * RATE));
			b[start + j] += amp * e * (0.7 * noise() + 0.3 * Math.sin((2 * Math.PI * tone * j) / RATE));
		}
		t += 0.06 + rand() * (0.16 - 0.04 * t);
	}
	return normalise(b, 0.5);
};

/** Hang-up click: a hard plastic snap and a short low thunk. 0.3 s. */
const hangup = () => {
	const b = buffer(0.3);
	const lp = lowpass();
	for (let i = 0; i < b.length; i++) {
		const t = i / RATE;
		b[i] = Math.exp(-t / 0.004) * noise() + 0.8 * Math.exp(-t / 0.05) * lp(noise(), 300) * 6 + 0.5 * Math.exp(-t / 0.06) * Math.sin(2 * Math.PI * 90 * t);
	}
	return normalise(b, 0.9);
};

/** Typewriter ticks for one caption line: one key per character at `cps` (matches Typewriter in src/film.tsx),
 * spaces softer, a carriage-return thunk at the end. */
const typeLine = (chars, cps) => () => {
	const b = buffer(chars / cps + 0.25);
	const lp = lowpass();
	for (let i = 0; i < chars; i++) {
		const start = Math.round((i / cps) * RATE);
		const amp = (i % 7 === 3 ? 0.55 : 1) * (0.75 + rand() * 0.25);
		const tone = 2400 + rand() * 1600;
		for (let j = 0; j < 0.025 * RATE && start + j < b.length; j++) {
			const t = j / RATE;
			b[start + j] += amp * (Math.exp(-t / 0.0025) * noise() + 0.4 * Math.exp(-t / 0.008) * Math.sin(2 * Math.PI * tone * t));
		}
	}
	const end = Math.round((chars / cps) * RATE);
	for (let j = 0; end + j < b.length; j++) {
		const t = j / RATE;
		b[end + j] += 0.6 * Math.exp(-t / 0.04) * lp(noise(), 400) * 5;
	}
	return normalise(b, 0.6);
};

await mkdir(outDir, {recursive: true});
for (const [name, make] of [['cold-drone', drone], ['cold-keys', keys], ['cold-click', hangup],
	// coldOpen.captionLines in src/content.ts at the cps used by TitleCaption in src/shots.tsx
	['cold-type-1', typeLine('LAWRENCE LIVERMORE NATIONAL LABORATORY'.length, 30)],
	['cold-type-2', typeLine('Blue Gene/L'.length, 12)],
	['cold-type-3', typeLine('Saturday, 11 June 2005 · 17:17'.length, 22)]]) {
	await writeFile(path.join(outDir, `${name}.wav`), wav(make()));
	console.log(`wrote public/assets/sfx/${name}.wav`);
}
