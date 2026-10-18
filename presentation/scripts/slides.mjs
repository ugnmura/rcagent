// Renders Slide1..Slide5 as PNG stills and combines them into out/slides.pdf (one 1920×1080 page each).
import {renderStill, selectComposition} from '@remotion/renderer';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {PDFDocument} from 'pdf-lib';
import {bundleProject, root} from './bundle.mjs';

const SLIDE_COUNT = 5;
const outDir = path.join(root, 'out');
const stillDir = path.join(outDir, 'slides');
await mkdir(stillDir, {recursive: true});

const serveUrl = await bundleProject();
const pdf = await PDFDocument.create();
pdf.setTitle('Making Sense of Logs');

for (let i = 1; i <= SLIDE_COUNT; i++) {
	const id = `Slide${i}`;
	const composition = await selectComposition({serveUrl, id, logLevel: 'error'});
	const output = path.join(stillDir, `${id}.png`);
	await renderStill({composition, serveUrl, output, imageFormat: 'png', logLevel: 'error'});
	const png = await pdf.embedPng(await readFile(output));
	const page = pdf.addPage([composition.width, composition.height]);
	page.drawImage(png, {x: 0, y: 0, width: composition.width, height: composition.height});
	console.log(`${id} -> ${path.relative(root, output)}`);
}

const pdfPath = path.join(outDir, 'slides.pdf');
await writeFile(pdfPath, await pdf.save());
console.log(`${path.relative(root, pdfPath)}: ${pdf.getPageCount()} pages`);
