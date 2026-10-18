// Synthesises the star-gag sound effects into public/assets/sfx/*.wav (mono, 48 kHz, 16-bit). No dependencies,
// seeded noise, so reruns produce identical files.
// Usage: node scripts/sfx.mjs
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const RATE = 48000;
const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'assets', 'sfx');

let seed = 1;
const rand = () => {
	seed = (seed * 1664525 + 1013904223) >>> 0;
	return seed / 2 ** 32;
};
const noise = () => rand() * 2 - 1;

const buffer = (seconds) => new Float32Array(Math.round(seconds * RATE));

/** One-pole low-pass, cutoff in Hz (may change per sample). */
const lowpass = () => {
	let y = 0;
	return (x, hz) => {
		const a = 1 - Math.exp((-2 * Math.PI * hz) / RATE);
		y += a * (x - y);
		return y;
	};
};

const normalise = (b, peak) => {
	let m = 0;
	for (const v of b) m = Math.max(m, Math.abs(v));
	if (m > 0) for (let i = 0; i < b.length; i++) b[i] *= peak / m;
	return b;
};

const wav = (b) => {
	const data = Buffer.alloc(b.length * 2);
	for (let i = 0; i < b.length; i++) data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, b[i])) * 32767), i * 2);
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
	h.writeUInt32LE(data.length, 40);
	return Buffer.concat([h, data]);
};

/** Air whoosh for the cursor glide: band of noise whose brightness swells and falls. */
const whoosh = () => {
	const b = buffer(1.1);
	const lp1 = lowpass();
	const lp2 = lowpass();
	for (let i = 0; i < b.length; i++) {
		const t = i / b.length;
		const env = Math.sin(Math.PI * Math.pow(t, 0.7)) ** 2;
		const hz = 400 + 2600 * env;
		const n = noise();
		b[i] = (lp1(n, hz) - lp2(n, hz * 0.25)) * env;
	}
	return normalise(b, 0.6);
};

/** Mouse click: a sharp press tick and a softer release tick 70 ms later. */
const click = () => {
	const b = buffer(0.2);
	const tick = (at, gain, hz) => {
		const s = Math.round(at * RATE);
		const lp = lowpass();
		for (let i = 0; i < 0.025 * RATE && s + i < b.length; i++) {
			const env = Math.exp(-i / (0.0025 * RATE));
			b[s + i] += gain * env * (lp(noise(), 6000) * 0.7 + Math.sin((2 * Math.PI * hz * i) / RATE) * 0.5);
		}
	};
	tick(0, 1, 2400);
	tick(0.07, 0.55, 3200);
	return normalise(b, 0.9);
};

/** Impact on the click: sub thump with a falling pitch plus a short filtered noise burst. */
const impact = () => {
	const b = buffer(1.2);
	const lp = lowpass();
	let phase = 0;
	for (let i = 0; i < b.length; i++) {
		const t = i / RATE;
		const hz = 45 + 110 * Math.exp(-t / 0.06);
		phase += (2 * Math.PI * hz) / RATE;
		const body = Math.sin(phase) * Math.exp(-t / 0.35);
		const hit = lp(noise(), 1800) * Math.exp(-t / 0.05) * 2.5;
		b[i] = Math.tanh(1.6 * (body + hit));
	}
	return normalise(b, 0.95);
};

/** Bell-like note with inharmonic partials. */
const bell = (b, at, hz, gain, decay) => {
	const s = Math.round(at * RATE);
	const partials = [
		[1, 1],
		[2.01, 0.45],
		[3.0, 0.25],
		[4.17, 0.15],
		[5.43, 0.08],
	];
	for (let i = 0; s + i < b.length; i++) {
		const t = i / RATE;
		const attack = Math.min(1, t / 0.004);
		let v = 0;
		for (const [m, g] of partials) v += g * Math.sin(2 * Math.PI * hz * m * t) * Math.exp((-t * m) / decay);
		b[s + i] += gain * attack * v;
	}
};

/** The star: a quick rising arpeggio of bells over a shimmering noise tail. */
const chime = () => {
	const b = buffer(2.6);
	const notes = [1046.5, 1318.5, 1568.0, 2093.0, 2637.0];
	notes.forEach((hz, i) => bell(b, i * 0.045, hz, 1 - i * 0.1, 0.9));
	bell(b, 0.25, 2093.0, 0.5, 1.4);
	const lpA = lowpass();
	const lpB = lowpass();
	for (let i = 0; i < b.length; i++) {
		const t = i / RATE;
		const n = noise();
		const shimmer = (lpA(n, 12000) - lpB(n, 5000)) * Math.exp(-t / 0.6) * Math.min(1, t / 0.03) * (0.6 + 0.4 * Math.sin(2 * Math.PI * 9 * t));
		b[i] += 0.9 * shimmer;
	}
	return normalise(b, 0.85);
};

/** One tiny high ping for a sparkle. */
const twinkle = () => {
	const b = buffer(0.7);
	bell(b, 0, 3520, 1, 0.25);
	bell(b, 0.03, 4698.6, 0.5, 0.2);
	return normalise(b, 0.6);
};

await mkdir(outDir, {recursive: true});
for (const [name, make] of Object.entries({whoosh, click, impact, chime, twinkle})) {
	const file = path.join(outDir, `${name}.wav`);
	await writeFile(file, wav(make()));
	console.log(`-> ${path.relative(process.cwd(), file)}`);
}
