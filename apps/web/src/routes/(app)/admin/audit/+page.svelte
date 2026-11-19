<script lang="ts">
	import { goto } from '$app/navigation';
	import { navigating, page } from '$app/state';
	import { get } from '#lib/api.ts';
	import { actionLabel, CHANNELS, FAILURE_REASONS, PERIODS, apiQuery } from '#lib/audit.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { formatter } from '#lib/format.ts';
	import type { AuditEvent, AuditPage } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const fmt = $derived(formatter(data.shell.user?.localization));

	// Loaded pages: the server page plus everything fetched with "Ältere laden".
	let more = $state<AuditEvent[]>([]);
	let nextBefore = $state<number | null>(null);
	let loading = $state(false);
	let open = $state<number | null>(null);

	$effect(() => {
		// reset when the filters (server data) change
		void data.page;
		more = [];
		nextBefore = data.page.next_before_id;
		open = null;
	});

	const events = $derived([...data.page.events, ...more]);
	const chain = $derived(data.page.chain);

	// Module areas from the navigation (core entries and admin excluded).
	const areas = $derived(
		data.shell.navigation
			.flatMap((s) => s.items)
			.filter((i) => !['home', 'inbox'].includes(i.key) && !i.path.startsWith('/admin'))
			.map((i) => ({ key: i.key, label: i.label }))
	);

	const params = $derived(page.url.searchParams);
	let search = $state('');
	$effect(() => {
		search = params.get('q') ?? '';
	});

	function setFilter(key: string, value: string) {
		const p = new URLSearchParams(page.url.search);
		if (value) p.set(key, value);
		else p.delete(key);
		goto(`?${p}`, { reset: false, replace: true });
	}

	let timer: ReturnType<typeof setTimeout>;
	function onSearch(value: string) {
		search = value;
		clearTimeout(timer);
		timer = setTimeout(() => setFilter('q', value.trim()), 300);
	}

	async function loadOlder() {
		if (nextBefore === null) return;
		loading = true;
		try {
			const q = apiQuery(new URLSearchParams(page.url.search));
			q.set('before_id', String(nextBefore));
			const r = await get<AuditPage>(`/admin/audit?${q}`);
			more = [...more, ...r.events];
			nextBefore = r.next_before_id;
		} finally {
			loading = false;
		}
	}

	const exportHref = $derived(`/api/v1/admin/audit/export.csv?${data.query}`);

	function target(e: AuditEvent): string {
		if (e.target_type === 'user') {
			if (e.target_id && e.target_id === e.actor_user_id) return 'Eigenes Konto';
			return e.target_name ?? 'Unbekannte Person';
		}
		if (e.action === 'auth.login_failed') return String(e.data.email ?? '');
		if (e.action === 'audit.exported') return `${e.data.rows ?? 0} Einträge · CSV`;
		if (e.target_type === 'settings') {
			const names: Record<string, string> = {
				general: 'Allgemein',
				branding: 'Branding',
				localization: 'Sprache & Region',
				navigation: 'Navigation',
				identity: 'Anmeldung',
				email: 'E-Mail'
			};
			return names[e.target_id ?? ''] ?? e.target_id ?? '';
		}
		if (e.target_type === 'module') return `Modul ${String(e.data.name ?? e.target_id ?? '')}`;
		if (e.target_type === 'role') {
			const n = e.data.name;
			return `Rolle ${Array.isArray(n) ? n[n.length - 1] : (n ?? e.target_id ?? '')}`;
		}
		return e.target_id ?? '';
	}

	function person(e: AuditEvent): string {
		if (e.actor_name) return e.actor_name;
		if (e.channel === 'cli') return 'Konsole';
		if (e.channel === 'system') return 'System';
		return 'Unbekannt';
	}

	const short = (h: string) => `${h.slice(0, 4)}…${h.slice(-4)}`;
	const list = (v: unknown) => (Array.isArray(v) ? (v as string[]) : []);
	const dayLabel = (iso: string) => {
		const r = fmt.relative(iso);
		return r.startsWith('heute') ? 'Heute' : r.startsWith('gestern') ? 'Gestern' : fmt.date(iso);
	};
</script>

<svelte:head><title>Audit-Log · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="head">
		<div class="titles">
			<span class="eyebrow">Administration</span>
			<h1>Audit-Log</h1>
			<p>Jede Änderung und jede Anmeldung, egal ob über Web, API oder KI-Client. Auch Exporte.</p>
		</div>
		<a class="btn btn-secondary" href={exportHref} download>
			<Icon name="download" size={18} />CSV exportieren
		</a>
	</header>

	<div class="chain" class:broken={!chain.ok} role="status">
		<Icon name="shield" size={24} />
		<span>
			{#if chain.ok}
				<strong>Protokoll lückenlos.</strong> Die Hash-Kette mit {fmt.number(chain.events, 0)} Einträgen
				wurde {fmt.relative(chain.checked_at)} geprüft. Keine veränderten oder fehlenden Einträge.
			{:else}
				<strong>Protokoll beschädigt.</strong> Ab Eintrag {chain.broken_at} stimmt die Hash-Kette nicht.
				Einträge wurden verändert oder gelöscht. Informiere die IT-Sicherheit.
			{/if}
		</span>
	</div>

	<div class="filters">
		<label class="search">
			<Icon name="search" size={18} />
			<span class="sr-only">Ereignisse durchsuchen</span>
			<input
				type="search"
				placeholder="Aktion, Ziel oder ID"
				value={search}
				oninput={(e) => onSearch(e.currentTarget.value)}
			/>
		</label>
		<label>
			<span class="sr-only">Person</span>
			<select
				class="input"
				value={params.get('actor') ?? ''}
				onchange={(e) => setFilter('actor', e.currentTarget.value)}
			>
				<option value="">Alle Personen</option>
				{#each data.page.actors as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
			</select>
		</label>
		<label>
			<span class="sr-only">Bereich</span>
			<select
				class="input"
				value={params.get('area') ?? ''}
				onchange={(e) => setFilter('area', e.currentTarget.value)}
			>
				<option value="">Alle Bereiche</option>
				<option value="core">Plattform</option>
				{#each areas as a (a.key)}<option value={a.key}>{a.label}</option>{/each}
			</select>
		</label>
		<label>
			<span class="sr-only">Kanal</span>
			<select
				class="input"
				value={params.get('channel') ?? ''}
				onchange={(e) => setFilter('channel', e.currentTarget.value)}
			>
				<option value="">Alle Kanäle</option>
				{#each Object.entries(CHANNELS) as [key, label] (key)}<option value={key}>{label}</option
					>{/each}
			</select>
		</label>
		<label>
			<span class="sr-only">Zeitraum</span>
			<select
				class="input"
				value={params.get('zeitraum') ?? '7d'}
				onchange={(e) =>
					setFilter('zeitraum', e.currentTarget.value === '7d' ? '' : e.currentTarget.value)}
			>
				{#each Object.entries(PERIODS) as [key, p] (key)}<option value={key}>{p.label}</option
					>{/each}
			</select>
		</label>
	</div>

	<div class="card table-wrap">
		<table class:is-loading={navigating.to?.url.pathname === page.url.pathname}>
			<thead>
				<tr>
					<th scope="col">Zeit</th>
					<th scope="col">Person</th>
					<th scope="col">Kanal</th>
					<th scope="col">Aktion</th>
					<th scope="col">Ziel</th>
				</tr>
			</thead>
			<tbody>
				{#each events as e, i (e.id)}
					{#if i === 0 || fmt.dayKey(events[i - 1].at) !== fmt.dayKey(e.at)}
						<tr class="day"><td colspan="5">{dayLabel(e.at)}</td></tr>
					{/if}
					<tr class="row" class:open={open === e.id}>
						<td class="t">
							<button
								type="button"
								class="expand"
								aria-expanded={open === e.id}
								aria-label="Details zu {actionLabel(e.action)} um {fmt.time(e.at)}"
								onclick={() => (open = open === e.id ? null : e.id)}
							>
								{fmt.time(e.at)}
							</button>
						</td>
						<td class="who">{person(e)}</td>
						<td><span class="chip ch-{e.channel}">{CHANNELS[e.channel] ?? e.channel}</span></td>
						<td class:fail={e.action.endsWith('_failed')}>{actionLabel(e.action)}</td>
						<td class="target">{target(e)}</td>
					</tr>
					{#if open === e.id}
						<tr class="detail">
							<td></td>
							<td colspan="4">
								<div class="box">
									<div class="change">
										{#if e.action === 'user.roles_changed' || (e.action === 'role.updated' && (e.data.added || e.data.removed))}
											<span class="lbl">Änderung</span>
											<div class="diff">
												{#each list(e.data.removed) as r (r)}<span class="del">{r}</span>{/each}
												{#each list(e.data.added) as r (r)}<span class="add">{r}</span>{/each}
											</div>
										{:else if e.action === 'auth.login_failed'}
											<span class="lbl">Grund</span>
											<span
												>{FAILURE_REASONS[String(e.data.reason)] ??
													String(e.data.reason ?? '')}</span
											>
										{:else if Object.keys(e.data).length}
											<span class="lbl">Daten</span>
											<pre>{JSON.stringify(e.data, null, 2)}</pre>
										{:else}
											<span class="lbl">Aktion</span><code>{e.action}</code>
										{/if}
									</div>
									<dl>
										<dt>Zeitpunkt</dt>
										<dd>{fmt.date(e.at)} {fmt.time(e.at)}</dd>
										<dt>Ereignis</dt>
										<dd><code>#{e.id}</code> · <code>{e.action}</code></dd>
										<dt>Hash</dt>
										<dd>
											<code title={e.hash}>{short(e.hash)}</code> · verkettet mit
											<code title={e.prev_hash}>{short(e.prev_hash)}</code>
										</dd>
										{#if e.ip}<dt>IP-Adresse</dt>
											<dd>{e.ip}</dd>{/if}
									</dl>
								</div>
							</td>
						</tr>
					{/if}
				{:else}
					<tr><td colspan="5" class="empty">Keine Ereignisse für diese Filter.</td></tr>
				{/each}
			</tbody>
		</table>
	</div>

	<div class="foot">
		<span>{events.length} Ereignisse angezeigt</span>
		{#if nextBefore !== null}
			<button
				class="btn btn-secondary"
				type="button"
				onclick={loadOlder}
				disabled={loading}
				aria-busy={loading}>Ältere laden</button
			>
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
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
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
		color: var(--muted);
	}
	.chain {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px 18px;
		border-radius: 12px;
		background: var(--primary-tint);
		color: var(--primary-strong);
		font-size: 15px;
	}
	.chain span {
		color: var(--ink);
	}
	.chain strong {
		color: var(--primary-strong);
	}
	.chain.broken {
		background: var(--danger-bg);
		color: var(--danger-ink);
	}
	.chain.broken strong {
		color: var(--danger-ink);
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}
	.search {
		flex: 1 1 240px;
		max-width: 360px;
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 44px;
		padding: 0 14px;
		border: 1px solid var(--input);
		border-radius: 10px;
		background: var(--surface);
		color: var(--muted-2);
		box-sizing: border-box;
	}
	.search:focus-within {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
	}
	.search input {
		flex: 1;
		min-width: 0;
		border: 0;
		outline: none;
		background: transparent;
		color: var(--ink);
		font: inherit;
		font-size: 15px;
	}
	.table-wrap {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		padding: 12px 16px;
		font-size: 13px;
		font-weight: 600;
		color: var(--muted);
		text-align: left;
		background: var(--surface-2);
		border-bottom: 1px solid var(--line);
	}
	td {
		padding: 10px 16px;
		font-size: 15px;
		border-bottom: 1px solid var(--line-3);
	}
	.day td {
		padding: 14px 16px 6px;
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--muted-2);
		border-bottom: 0;
	}
	.row.open,
	.detail {
		background: var(--primary-tint);
	}
	.expand {
		min-height: 36px;
		padding: 0 8px;
		margin-left: -8px;
		border: 0;
		border-radius: 8px;
		background: none;
		color: var(--link);
		font: inherit;
		font-variant-numeric: tabular-nums;
		font-weight: 600;
		cursor: pointer;
		text-decoration: underline;
		text-decoration-color: color-mix(in oklab, currentColor 30%, transparent);
		text-underline-offset: 3px;
	}
	.who {
		font-weight: 600;
	}
	.fail {
		color: var(--danger-ink);
	}
	.target {
		color: var(--ink-2);
	}
	.chip.ch-web {
		background: var(--info-bg);
		color: var(--info-ink);
	}
	.chip.ch-mcp {
		background: var(--ok-bg);
		color: var(--ok-ink);
	}
	.chip.ch-api {
		background: var(--warn-bg);
		color: var(--warn-ink);
	}
	.detail td {
		padding-top: 0;
	}
	.box {
		display: flex;
		flex-wrap: wrap;
		gap: 24px;
		padding: 14px 16px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	.change {
		flex: 1 1 280px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		min-width: 0;
	}
	.lbl,
	dt {
		font-size: 13px;
		font-weight: 600;
		color: var(--muted);
	}
	.diff {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		font-size: 14px;
	}
	.del,
	.add {
		padding: 4px 8px;
		border-radius: 6px;
	}
	.del {
		background: var(--danger-bg);
		color: var(--danger-ink);
		text-decoration: line-through;
	}
	.add {
		background: var(--ok-bg);
		color: var(--ok-ink);
	}
	pre {
		margin: 0;
		font-size: 13px;
		white-space: pre-wrap;
		word-break: break-word;
		color: var(--ink-2);
	}
	dl {
		flex: 1 1 280px;
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 6px 16px;
		margin: 0;
		font-size: 14px;
	}
	dd {
		margin: 0;
	}
	code {
		font-size: 13px;
	}
	.empty {
		text-align: center;
		color: var(--muted);
		padding: 32px;
	}
	.foot {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		font-size: 14px;
		color: var(--muted);
	}
</style>
