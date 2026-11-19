<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, put } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import SchemaForm from '#lib/components/SchemaForm.svelte';
	import type { ModuleInfo } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const mods = $derived(data.modules);

	const STATUS = {
		active: { label: 'Aktiv', tone: 'ok' },
		inactive: { label: 'Deaktiviert', tone: 'muted' },
		available: { label: 'Verfügbar', tone: 'info' }
	} as const;

	const MCP_KIND = {
		read: { label: 'Lesen', tone: 'info' },
		write: { label: 'Schreiben', tone: 'warn' },
		prompt: { label: 'Prompt', tone: '' }
	} as const;

	let selectedKey = $state(page.url.searchParams.get('modul') ?? '');
	const selected = $derived(mods.modules.find((m) => m.key === selectedKey) ?? mods.modules[0]);

	// Editable copy of the selected module
	type Draft = {
		area: string | null;
		visible: Record<string, boolean>;
		settings: Record<string, unknown>;
		mcp: Record<string, boolean>;
	};
	let draft = $state<Draft>({ area: null, visible: {}, settings: {}, mcp: {} });
	let loadedFor = $state('');

	function take(m: ModuleInfo) {
		draft = {
			area: m.area,
			visible: Object.fromEntries(m.children.map((c) => [c.path, c.visible])),
			settings: structuredClone(m.settings),
			mcp: Object.fromEntries(m.mcp.map((i) => [i.name, i.enabled]))
		};
		loadedFor = `${m.key}@${mods.version}`;
	}

	$effect(() => {
		if (selected && loadedFor !== `${selected.key}@${mods.version}`) take(selected);
	});

	function select(key: string) {
		selectedKey = key;
		message = null;
		const url = new URL(page.url.href);
		url.searchParams.set('modul', key);
		history.replaceState(history.state, '', url);
	}

	let busy = $state(false);
	// The button whose action runs (for its spinner): true = save/activate, false = deactivate
	let busyEnable = $state<boolean | null>(null);
	let message = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);

	const ERRORS: Record<string, string> = {
		version_conflict:
			'Jemand hat die Module inzwischen geändert. Lade die Seite neu und versuche es nochmals.',
		unknown_area: 'Diesen Bereich gibt es nicht mehr. Lade die Seite neu.'
	};

	async function save(enabled: boolean) {
		const m = selected;
		busy = true;
		busyEnable = enabled;
		message = null;
		try {
			await put(`/admin/modules/${m.key}`, {
				version: mods.version,
				enabled,
				area: draft.area,
				hidden_children: Object.entries(draft.visible)
					.filter(([, v]) => !v)
					.map(([k]) => k),
				settings: draft.settings,
				mcp_disabled: Object.entries(draft.mcp)
					.filter(([, v]) => !v)
					.map(([k]) => k)
			});
			await invalidateAll();
			message = {
				tone: 'ok',
				text:
					enabled === (m.status === 'active')
						? `${m.name} gespeichert.`
						: enabled
							? `${m.name} ist jetzt aktiv.`
							: `${m.name} ist deaktiviert. Die Daten bleiben erhalten.`
			};
		} catch (e) {
			const d = e instanceof ApiError ? e.detail : '';
			message = {
				tone: 'error',
				text:
					ERRORS[d] ??
					(e instanceof ApiError && e.status === 422
						? 'Bitte prüfe die Einstellungen des Moduls.'
						: 'Speichern hat nicht geklappt. Bitte versuche es erneut.')
			};
		} finally {
			busy = false;
			busyEnable = null;
		}
	}

	const areaLabel = (key: string | null) =>
		key === null
			? 'Hauptbereich, unter Mein Eingang'
			: (mods.areas.find((a) => a.key === key)?.label ?? key);
</script>

<svelte:head><title>Module · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="titles">
		<span class="eyebrow">Administration</span>
		<h1>Module</h1>
		<p>
			Jedes Modul ist eine einzelne Funktion. Hier schaltest du Module ein, legst ihren Platz in der
			Seitenleiste fest und passt ihre Einstellungen an.
		</p>
	</header>

	{#if message}
		<p class="notice {message.tone}" role={message.tone === 'error' ? 'alert' : 'status'}>
			{message.text}
		</p>
	{/if}

	<div class="layout">
		<nav class="list card" aria-label="Module">
			{#each mods.modules as m (m.key)}
				<button
					type="button"
					class="mod"
					class:on={selected?.key === m.key}
					aria-current={selected?.key === m.key ? 'true' : undefined}
					onclick={() => select(m.key)}
				>
					<span class="ico"><Icon name={m.icon ?? 'grid'} size={22} /></span>
					<span class="txt">
						<strong>{m.name}</strong>
						<small>{areaLabel(m.area)}</small>
					</span>
					<span class="chip {STATUS[m.status].tone}">{STATUS[m.status].label}</span>
				</button>
			{/each}
			<p class="more">Weitere Module folgen. Jedes Modul wird einzeln beschrieben und gebaut.</p>
		</nav>

		{#if selected}
			{@const m = selected}
			<section class="card detail" aria-labelledby="md-h">
				<div class="top">
					<span class="ico big"><Icon name={m.icon ?? 'grid'} size={28} /></span>
					<div class="head">
						<div class="name">
							<h2 id="md-h">{m.name}</h2>
							<span class="chip {STATUS[m.status].tone}">{STATUS[m.status].label}</span>
						</div>
						{#if m.description}<p>{m.description}</p>{/if}
						<p class="meta">Version {m.version} · läuft im Kern · <code>{m.key}</code></p>
					</div>
				</div>

				<div class="sec">
					<h3>Rollenzuordnung</h3>
					{#each m.permissions as p (p.id)}
						<div class="row">
							<span class="perm"><strong>{p.label}</strong><code>{p.id}</code></span>
							<span class="chips">
								{#each p.roles as r (r)}<span class="chip">{r}</span>{:else}<span class="none"
										>keine Rolle</span
									>{/each}
								<a href="/admin/benutzer?tab=rollen">Ändern</a>
							</span>
						</div>
					{/each}
				</div>

				<div class="sec">
					<h3>Navigation</h3>
					<div class="grid">
						<div class="f">
							<label for="m-area">Position in der Seitenleiste</label>
							<select
								id="m-area"
								class="input"
								value={draft.area ?? ''}
								onchange={(e) => (draft.area = e.currentTarget.value || null)}
							>
								<option value="">{areaLabel(null)}</option>
								{#each mods.areas as a (a.key)}<option value={a.key}>{a.label}</option>{/each}
							</select>
							<small
								>Bereiche verwaltest du unter <a href="/admin/einstellungen?tab=navigation"
									>Einstellungen › Navigation</a
								>.</small
							>
						</div>
						<div class="f">
							<span class="lab">Unterpunkte</span>
							{#if m.children.length}
								<div class="box">
									{#each m.children as c (c.path)}
										<label class="row tight">
											{c.label}
											<input type="checkbox" role="switch" bind:checked={draft.visible[c.path]} />
										</label>
									{/each}
								</div>
							{:else}
								<span class="none pad">Dieses Modul hat keine Unterpunkte.</span>
							{/if}
						</div>
					</div>
				</div>

				{#if m.settings_schema}
					<div class="sec">
						<h3>Einstellungen</h3>
						<SchemaForm schema={m.settings_schema} bind:values={draft.settings} idPrefix={m.key} />
					</div>
				{/if}

				{#if m.mcp.length}
					<div class="sec">
						<div class="sec-head">
							<h3>KI-Zugriff (MCP)</h3>
							<span>KI-Clients handeln immer mit den Rechten der Person.</span>
						</div>
						{#each m.mcp as i (i.name)}
							<label class="row">
								<span class="perm"
									><code class="strong">{i.name}</code><small>{i.title}</small></span
								>
								<span class="chips">
									<span class="chip {MCP_KIND[i.kind].tone}">{MCP_KIND[i.kind].label}</span>
									<input
										type="checkbox"
										role="switch"
										bind:checked={draft.mcp[i.name]}
										aria-label="{i.name} erlauben"
									/>
								</span>
							</label>
						{/each}
					</div>
				{/if}

				<div class="foot">
					<span
						>{m.status === 'active'
							? 'Beim Deaktivieren bleiben alle Daten erhalten.'
							: 'Das Modul ist für niemanden sichtbar, bis du es aktivierst.'}</span
					>
					<div class="buttons">
						{#if m.status === 'active'}
							<button
								class="btn btn-secondary danger"
								type="button"
								disabled={busy}
								aria-busy={busyEnable === false}
								onclick={() => save(false)}>Modul deaktivieren</button
							>
							<button
								class="btn btn-primary"
								type="button"
								disabled={busy}
								aria-busy={busyEnable === true}
								onclick={() => save(true)}>Speichern</button
							>
						{:else}
							<button
								class="btn btn-primary"
								type="button"
								disabled={busy}
								aria-busy={busyEnable === true}
								onclick={() => save(true)}>Modul aktivieren</button
							>
						{/if}
					</div>
				</div>
			</section>
		{/if}
	</div>
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 22px;
		max-width: 1240px;
	}
	.titles {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.eyebrow {
		font-size: 13px;
		font-weight: 600;
		color: var(--muted-2);
	}
	h1 {
		margin: 0;
		font-size: 30px;
		letter-spacing: -0.02em;
	}
	.titles p {
		margin: 0;
		max-width: 720px;
		color: var(--muted);
		font-size: 16px;
	}
	.layout {
		display: flex;
		flex-wrap: wrap;
		gap: 20px;
		align-items: flex-start;
	}
	.list {
		flex: 1 1 280px;
		min-width: 0;
		padding: 8px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.mod {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px;
		border: 0;
		border-radius: 10px;
		background: none;
		color: var(--ink);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.mod:hover {
		background: var(--hover);
	}
	.mod.on {
		background: var(--primary-tint);
	}
	.ico {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 44px;
		height: 44px;
		border-radius: 12px;
		background: var(--info-bg);
		color: var(--info-ink);
	}
	.ico.big {
		width: 56px;
		height: 56px;
		border-radius: 14px;
	}
	.txt {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.txt strong {
		font-size: 16px;
	}
	.txt small,
	.more,
	.meta,
	small,
	.none {
		font-size: 13px;
		color: var(--muted);
	}
	.more {
		margin: 8px 10px 6px;
	}
	.detail {
		flex: 2 1 560px;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	.top {
		display: flex;
		flex-wrap: wrap;
		gap: 16px;
		padding: 24px;
	}
	.head {
		flex: 1 1 240px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.head p {
		margin: 0;
		color: var(--muted);
	}
	.name {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	h2 {
		margin: 0;
		font-size: 22px;
	}
	.sec {
		padding: 20px 24px;
		border-top: 1px solid var(--line-2);
	}
	h3 {
		margin: 0 0 8px;
		font-size: 16px;
	}
	.sec-head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: baseline;
		gap: 8px;
	}
	.sec-head span {
		font-size: 14px;
		color: var(--muted);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 12px 0;
		border-bottom: 1px solid var(--line-3);
	}
	.row:last-child {
		border-bottom: 0;
	}
	.row.tight {
		padding: 8px 12px;
		font-size: 15px;
	}
	.perm {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.perm code {
		font-size: 12px;
		color: var(--muted);
	}
	.perm code.strong {
		font-size: 14px;
		font-weight: 600;
		color: var(--ink);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
	}
	.chips a {
		font-size: 14px;
		font-weight: 600;
		padding: 0 6px;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 16px;
		align-items: start;
	}
	.f {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.f label,
	.lab {
		font-size: 14px;
		font-weight: 600;
	}
	.box {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	.pad {
		padding-top: 10px;
	}
	input[type='checkbox'] {
		width: 18px;
		height: 18px;
		accent-color: var(--primary);
	}
	.foot {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		align-items: center;
		justify-content: space-between;
		padding: 18px 24px;
		border-top: 1px solid var(--line-2);
		background: var(--surface-2);
		border-radius: 0 0 14px 14px;
		font-size: 14px;
		color: var(--muted);
	}
	.buttons {
		display: flex;
		gap: 10px;
	}
	.danger {
		color: var(--danger-ink);
	}
</style>
