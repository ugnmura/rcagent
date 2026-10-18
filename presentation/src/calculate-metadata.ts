import {ALL_FORMATS, Input, UrlSource} from 'mediabunny';
import {getStaticFiles, staticFile, type CalculateMetadataFunction} from 'remotion';
import {ASSETS, BENCHMARKS_FILE, type AssetKey, type ResolvedAssets} from './assets';
import {EMPTY_BENCHMARKS, type Benchmarks} from './benchmarks';
import {assertWithinLimit, buildTimeline, describeTimeline, totalFrames, type SceneTiming} from './timeline';

export type TalkProps = {
	assets: ResolvedAssets | null;
	scenes: SceneTiming[] | null;
	benchmarks: Benchmarks | null;
	report: string | null;
};

const assetPath = (file: string) => `assets/${file}`;

const exists = (file: string) => {
	const name = assetPath(file);
	return getStaticFiles().some((f) => f.name === name);
};

const durationOf = async (file: string): Promise<number> => {
	const input = new Input({formats: ALL_FORMATS, source: new UrlSource(staticFile(assetPath(file)))});
	try {
		const seconds = await input.computeDuration();
		if (!Number.isFinite(seconds) || seconds <= 0) {
			throw new Error(`duration is ${seconds}`);
		}
		return seconds;
	} catch (e) {
		throw new Error(`public/assets/${file} exists but its duration cannot be read: ${(e as Error).message}`);
	} finally {
		input.dispose();
	}
};

export const resolveAssets = async (): Promise<ResolvedAssets> => {
	const entries = await Promise.all(
		(Object.keys(ASSETS) as AssetKey[]).map(async (key) => {
			const spec = ASSETS[key];
			if (!exists(spec.file)) {
				return [key, {present: false, seconds: spec.placeholderSeconds}] as const;
			}
			return [key, {present: true, seconds: await durationOf(spec.file)}] as const;
		}),
	);
	return Object.fromEntries(entries) as ResolvedAssets;
};

export const loadBenchmarks = async (): Promise<Benchmarks> => {
	if (!exists(BENCHMARKS_FILE)) {
		return EMPTY_BENCHMARKS;
	}
	const res = await fetch(staticFile(assetPath(BENCHMARKS_FILE)));
	if (!res.ok) {
		throw new Error(`Cannot read public/assets/${BENCHMARKS_FILE}: HTTP ${res.status}`);
	}
	return (await res.json()) as Benchmarks;
};

export const calculateTalkMetadata: CalculateMetadataFunction<TalkProps> = async () => {
	const [assets, benchmarks] = await Promise.all([resolveAssets(), loadBenchmarks()]);
	const scenes = buildTimeline(assets);
	assertWithinLimit(scenes, assets);
	const report = describeTimeline(scenes, assets);
	// eslint-disable-next-line no-console
	console.log(`Scene lengths:\n${report}`);
	return {
		durationInFrames: totalFrames(scenes),
		props: {assets, scenes, benchmarks, report},
	};
};

export const calculateSlideMetadata: CalculateMetadataFunction<{mode: 'video' | 'print'; benchmarks: Benchmarks | null}> = async ({
	props,
}) => ({
	props: {...props, benchmarks: await loadBenchmarks()},
});
