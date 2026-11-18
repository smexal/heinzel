<script lang="ts">
	// Global search (Ctrl K / Cmd K). Mounted once in the app layout; results come from
	// GET /api/v1/search, which already filters by permissions.
	import { goto } from '$app/navigation';
	import { ApiError, get } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';

	type Hit = {
		id: string;
		title: string;
		title_hl: [number, number][];
		meta: string;
		snippet: string | null;
		snippet_hl: [number, number][];
		link: string;
		chip: { label: string; tone: string } | null;
	};
	type Group = { key: string; label: string; icon: string; count: number; items: Hit[] };
	type Result = { query: string; total: number; groups: Group[] };

	let { open = $bindable(false) }: { open?: boolean } = $props();

	let dialog: HTMLDialogElement;
	let input = $state<HTMLInputElement>();
	let q = $state('');
	let group = $state<string | null>(null);
	let result = $state<Result | null>(null);
	let counts = $state<{ key: string; label: string; count: number }[]>([]);
	let total = $state(0);
	let active = $state(0);
	let loading = $state(false);
	let failed = $state(false);

	const flat = $derived(result ? result.groups.flatMap((g) => g.items) : []);
	const ICON_TONE: Record<string, string> = {
		compass: 'tone-primary',
		users: 'tone-purple',
		'check-square': 'tone-info',
		wrench: 'tone-warn'
	};
	const CHIP_TONE: Record<string, string> = { red: 'danger', amber: 'warn', blue: 'info' };

	$effect(() => {
		if (open && !dialog.open) {
			dialog.showModal();
			input?.select();
		} else if (!open && dialog.open) {
			dialog.close();
		}
	});

	// Debounced query; a newer query cancels the one in flight.
	let controller: AbortController | null = null;
	$effect(() => {
		const query = q.trim();
		const g = group;
		if (query.length < 2) {
			result = null;
			counts = [];
			total = 0;
			failed = false;
			return;
		}
		const timer = setTimeout(() => run(query, g), 150);
		return () => clearTimeout(timer);
	});

	async function run(query: string, g: string | null) {
		controller?.abort();
		controller = new AbortController();
		const signal = controller.signal;
		loading = true;
		try {
			const params = new URLSearchParams({ q: query });
			if (g) params.set('group', g);
			const res = await get<Result>(`/search?${params}`);
			if (signal.aborted) return;
			result = res;
			total = res.total;
			if (!g) counts = res.groups.map(({ key, label, count }) => ({ key, label, count }));
			active = 0;
			failed = false;
		} catch (e) {
			if (!signal.aborted) failed = !(e instanceof ApiError && e.status === 401);
		} finally {
			if (!signal.aborted) loading = false;
		}
	}

	function pick(g: string | null) {
		group = g;
		input?.focus();
	}

	function close() {
		open = false;
	}

	async function openHit(hit: Hit) {
		close();
		await goto(hit.link);
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			if (!flat.length) return;
			active = (active + (e.key === 'ArrowDown' ? 1 : flat.length - 1)) % flat.length;
			document.getElementById(`sr-${active}`)?.scrollIntoView({ block: 'nearest' });
		} else if (e.key === 'Enter' && flat[active]) {
			e.preventDefault();
			openHit(flat[active]);
		}
	}

	function parts(text: string, hl: [number, number][]) {
		const out: { t: string; m: boolean }[] = [];
		let at = 0;
		for (const [a, b] of hl) {
			if (a > at) out.push({ t: text.slice(at, a), m: false });
			out.push({ t: text.slice(a, b), m: true });
			at = b;
		}
		if (at < text.length) out.push({ t: text.slice(at), m: false });
		return out;
	}

	function indexOf(hit: Hit) {
		return flat.indexOf(hit);
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			open = true;
		}
	}}
/>

<dialog
	bind:this={dialog}
	class="search card"
	aria-labelledby="sq-l"
	onclose={() => (open = false)}
	onclick={(e) => {
		if (e.target === dialog) close();
	}}
>
	<div class="bar">
		<Icon name="search" size={22} />
		<label class="sr-only" id="sq-l" for="sq">Suchen in Heinzel</label>
		<input
			bind:this={input}
			id="sq"
			type="search"
			placeholder="Suchen in Heinzel …"
			autocomplete="off"
			spellcheck="false"
			role="combobox"
			aria-expanded={flat.length > 0}
			aria-controls="sq-results"
			aria-activedescendant={flat.length ? `sr-${active}` : undefined}
			bind:value={q}
			{onkeydown}
		/>
		<button class="esc" type="button" onclick={close} aria-label="Suche schliessen">Esc</button>
	</div>

	{#if counts.length > 1}
		<div class="filters" role="group" aria-label="Filter">
			<button
				type="button"
				class="fchip"
				class:on={group === null}
				aria-pressed={group === null}
				onclick={() => pick(null)}>Alle <span>{total}</span></button
			>
			{#each counts as c (c.key)}
				<button
					type="button"
					class="fchip"
					class:on={group === c.key}
					aria-pressed={group === c.key}
					onclick={() => pick(c.key)}>{c.label} <span>{c.count}</span></button
				>
			{/each}
		</div>
	{/if}

	<div class="results" id="sq-results" role="listbox" aria-label="Suchergebnisse">
		{#if q.trim().length < 2}
			<p class="hint">Personen, Seiten und Einträge aus allen Modulen, die du sehen darfst.</p>
		{:else if failed}
			<p class="hint">Die Suche ist gerade nicht erreichbar. Versuche es gleich nochmals.</p>
		{:else if result && result.total === 0 && !loading}
			<p class="hint">Keine Treffer für «{q.trim()}».</p>
		{:else if result}
			{#each result.groups as g (g.key)}
				<div class="rg" role="presentation">
					<span>{g.label}</span><span class="n">{g.count}</span>
				</div>
				{#each g.items as hit (hit.link + hit.id)}
					{@const i = indexOf(hit)}
					<a
						id="sr-{i}"
						class="rs"
						class:act={i === active}
						href={hit.link}
						role="option"
						aria-selected={i === active}
						onmouseenter={() => (active = i)}
						onclick={(e) => {
							e.preventDefault();
							openHit(hit);
						}}
					>
						<span class="ricon {ICON_TONE[g.icon] ?? ''}"><Icon name={g.icon} size={18} /></span>
						<span class="txt">
							<span class="title"
								>{#each parts(hit.title, hit.title_hl) as p, k (k)}{#if p.m}<mark>{p.t}</mark
										>{:else}{p.t}{/if}{/each}</span
							>
							{#if hit.snippet}
								<span class="snip"
									>{#each parts(hit.snippet, hit.snippet_hl) as p, k (k)}{#if p.m}<mark>{p.t}</mark
											>{:else}{p.t}{/if}{/each}</span
								>
							{/if}
							{#if hit.meta}<span class="meta">{hit.meta}</span>{/if}
						</span>
						{#if hit.chip}<span class="chip {CHIP_TONE[hit.chip.tone] ?? ''}">{hit.chip.label}</span
							>{/if}
					</a>
				{/each}
				{#if !group && g.count > g.items.length}
					<button type="button" class="more" onclick={() => pick(g.key)}
						>Alle {g.count} in {g.label} anzeigen</button
					>
				{/if}
			{/each}
		{/if}
	</div>

	<div class="foot">
		<span class="keys">
			<span><kbd>↑</kbd> <kbd>↓</kbd> auswählen</span>
			<span><kbd>Enter</kbd> öffnen</span>
			<span><kbd>Esc</kbd> schliessen</span>
		</span>
		<span class="only"><Icon name="shield" size={16} />Nur Ergebnisse, die du sehen darfst</span>
	</div>
</dialog>

<style>
	.search {
		margin: 72px auto auto;
		width: min(720px, calc(100vw - 32px));
		max-height: calc(100vh - 120px);
		padding: 0;
		border-radius: 16px;
		box-shadow: 0 24px 64px rgb(0 0 0 / 0.25);
		color: var(--ink);
		overflow: hidden;
	}
	.search[open] {
		display: flex;
		flex-direction: column;
	}
	.search::backdrop {
		background: rgb(22 26 25 / 0.45);
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 14px 16px 14px 20px;
		border-bottom: 1px solid var(--line-2);
		color: var(--primary);
	}
	.bar input {
		flex: 1;
		min-width: 0;
		min-height: 44px;
		border: 0;
		outline: none;
		background: transparent;
		font: inherit;
		font-size: 19px;
		font-weight: 500;
		color: var(--ink);
	}
	.bar input::-webkit-search-cancel-button {
		display: none;
	}
	.esc,
	kbd {
		font: inherit;
		font-size: 11px;
		font-weight: 600;
		color: var(--muted-2);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 2px 6px;
		background: var(--surface-2);
	}
	.esc {
		padding: 4px 8px;
		font-size: 12px;
		cursor: pointer;
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		padding: 12px 20px;
		border-bottom: 1px solid var(--line-2);
	}
	.fchip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 34px;
		padding: 0 12px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--surface);
		color: var(--ink-2);
		font: inherit;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}
	.fchip span {
		font-weight: 500;
		color: var(--muted);
	}
	.fchip.on {
		background: var(--primary-tint);
		border-color: color-mix(in oklab, var(--primary) 35%, var(--surface));
		color: var(--primary-strong);
	}
	.results {
		flex: 1;
		min-height: 0;
		max-height: 460px;
		overflow-y: auto;
		padding: 4px 0 10px;
	}
	.hint {
		margin: 0;
		padding: 22px 20px;
		color: var(--muted);
		font-size: 15px;
	}
	.rg {
		display: flex;
		gap: 8px;
		padding: 12px 20px 4px;
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--muted-2);
	}
	.rg .n {
		letter-spacing: 0;
		font-weight: 600;
		color: var(--muted);
	}
	.rs {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 20px;
		text-decoration: none;
		color: var(--ink);
	}
	.rs.act {
		background: var(--primary-tint);
	}
	.ricon {
		width: 36px;
		height: 36px;
		border-radius: 10px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		background: var(--line-3);
		color: var(--ink-2);
	}
	.tone-primary {
		background: var(--primary-tint);
		color: var(--primary-strong);
	}
	.tone-info {
		background: var(--info-bg);
		color: var(--info-ink);
	}
	.tone-warn {
		background: var(--warn-bg);
		color: var(--warn-ink);
	}
	.tone-purple {
		background: #efe9fb;
		color: #4b3a8c;
	}
	:global(:root[data-theme='dark']) .tone-purple {
		background: #2a2440;
		color: #c5b6f2;
	}
	.txt {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.title {
		font-size: 15px;
		font-weight: 600;
	}
	.snip,
	.meta {
		font-size: 13px;
		color: var(--muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.snip {
		color: var(--ink-2);
	}
	mark {
		background: var(--ok-bg);
		color: var(--ok-ink);
		border-radius: 2px;
		padding: 0;
	}
	.chip.danger {
		background: var(--danger-bg);
		color: var(--danger-ink);
	}
	.more {
		display: block;
		margin: 2px 20px 4px 68px;
		padding: 4px 0;
		border: 0;
		background: none;
		color: var(--link);
		font: inherit;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}
	.foot {
		display: flex;
		flex-wrap: wrap;
		gap: 10px 18px;
		align-items: center;
		justify-content: space-between;
		padding: 12px 20px;
		border-top: 1px solid var(--line-2);
		background: var(--surface-2);
		font-size: 13px;
		color: var(--muted);
	}
	.keys {
		display: flex;
		gap: 14px;
		flex-wrap: wrap;
	}
	.only {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
</style>
