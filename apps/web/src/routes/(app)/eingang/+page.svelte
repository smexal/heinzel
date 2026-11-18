<script lang="ts">
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post } from '#lib/api.ts';
	import { formatter } from '#lib/format.ts';
	import { renderMarkdown } from '#lib/markdown.ts';
	import type { InboxItem } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const fmt = $derived(formatter(data.shell.user?.localization));
	const items = $derived(data.inbox.items);
	const counts = $derived(data.inbox.counts);

	const selectedId = $derived(page.url.searchParams.get('eintrag'));
	const selected = $derived(items.find((i) => i.id === selectedId) ?? null);

	let message = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);
	let busy = $state(false);

	function setParam(key: string, value: string | null, drop: string[] = []) {
		const p = new URLSearchParams(page.url.search);
		if (value) p.set(key, value);
		else p.delete(key);
		for (const d of drop) p.delete(d);
		const qs = p.toString();
		return goto(qs ? `?${qs}` : page.url.pathname, { reset: false, replace: key === 'eintrag' });
	}

	async function open(item: InboxItem) {
		message = null;
		await setParam('eintrag', item.id);
		if (!item.read && !item.done) {
			await post(`/inbox/${item.id}/read`);
			await invalidateAll();
		}
	}

	async function change(item: InboxItem, what: 'done' | 'reopen' | 'unread') {
		busy = true;
		message = null;
		try {
			await post(`/inbox/${item.id}/${what}`);
			if (what === 'unread') await setParam('eintrag', null);
			await invalidateAll();
			message = {
				tone: 'ok',
				text:
					what === 'done'
						? 'Erledigt. Du findest den Eintrag unter «Erledigt».'
						: what === 'reopen'
							? 'Wieder offen.'
							: 'Als ungelesen markiert.'
			};
		} catch {
			message = { tone: 'error', text: 'Das hat nicht geklappt. Bitte versuche es erneut.' };
		} finally {
			busy = false;
		}
	}

	async function action(item: InboxItem, key: string) {
		busy = true;
		message = null;
		try {
			const r = await post<{ message: string }>(`/inbox/${item.id}/actions/${key}`);
			await invalidateAll();
			message = { tone: 'ok', text: r.message };
		} catch (e) {
			const d = e instanceof ApiError ? e.detail : '';
			message = {
				tone: 'error',
				text:
					d === 'forbidden'
						? 'Dafür fehlt dir die Berechtigung.'
						: d === 'action_unavailable'
							? 'Diese Aktion ist nicht mehr möglich.'
							: 'Das hat nicht geklappt. Bitte versuche es erneut.'
			};
		} finally {
			busy = false;
		}
	}

	async function readAll() {
		const source = page.url.searchParams.get('quelle');
		await post(`/inbox/read-all${source ? `?source=${encodeURIComponent(source)}` : ''}`);
		await invalidateAll();
	}

	const VIEWS = [
		{ key: 'open', label: 'Offen' },
		{ key: 'notices', label: 'Mitteilungen' },
		{ key: 'done', label: 'Erledigt' }
	];

	function meta(i: InboxItem): string {
		const parts = [];
		if (i.context) parts.push(i.context);
		if (i.actor_name) parts.push(`von ${i.actor_name}`);
		parts.push(fmt.relative(i.updated_at));
		return parts.join(' · ');
	}

	const buttonClass = (style: string) =>
		style === 'primary' ? 'btn-primary' : style === 'danger' ? 'btn-danger' : 'btn-secondary';
</script>

<svelte:head><title>Mein Eingang · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="head">
		<div class="titles">
			<h1>Mein Eingang</h1>
			<p>Aufgaben und Mitteilungen aus allen Modulen, an einem Ort.</p>
		</div>
		<div class="tools">
			{#if data.inbox.sources.length > 1}
				<label>
					<span class="sr-only">Quelle</span>
					<select
						class="input"
						value={page.url.searchParams.get('quelle') ?? ''}
						onchange={(e) => setParam('quelle', e.currentTarget.value || null, ['eintrag'])}
					>
						<option value="">Alle Quellen</option>
						{#each data.inbox.sources as s (s.key)}<option value={s.key}>{s.label}</option>{/each}
					</select>
				</label>
			{/if}
			<button class="btn btn-secondary" type="button" onclick={readAll} disabled={!counts.unread}
				>Alle als gelesen markieren</button
			>
		</div>
	</header>

	<nav class="tabs" aria-label="Filter">
		{#each VIEWS as v (v.key)}
			<button
				type="button"
				class="tab"
				class:on={data.view === v.key}
				aria-current={data.view === v.key ? 'page' : undefined}
				onclick={() => setParam('ansicht', v.key === 'open' ? null : v.key, ['eintrag'])}
			>
				{v.label}
				{#if v.key === 'open' && counts.open}<span class="count">{counts.open}</span>{/if}
				{#if v.key === 'notices' && counts.notices}<span class="count muted">{counts.notices}</span
					>{/if}
			</button>
		{/each}
	</nav>

	{#if message}
		<p class="notice {message.tone}" role={message.tone === 'error' ? 'alert' : 'status'}>
			{message.text}
		</p>
	{/if}

	<div class="layout">
		<section class="list card" aria-label="Einträge">
			{#each items as i (i.id)}
				<button
					type="button"
					class="it"
					class:on={selected?.id === i.id}
					class:unread={!i.read && !i.done}
					aria-current={selected?.id === i.id ? 'true' : undefined}
					onclick={() => open(i)}
				>
					{#if !i.read && !i.done}
						<span class="dot" role="img" aria-label="ungelesen"></span>
					{:else}
						<span class="nodot"></span>
					{/if}
					<span class="txt">
						<span class="tags">
							<span
								class="chip"
								class:danger={i.severity === 'urgent'}
								class:info={i.source !== 'core' && i.severity !== 'urgent'}
								>{i.source_label}{#if i.severity === 'urgent'}&nbsp;· Dringend{/if}</span
							>
							<span class="kind">{i.kind === 'task' ? 'Aufgabe' : 'Mitteilung'}</span>
						</span>
						<span class="title">{i.title}</span>
						<span class="meta">{meta(i)}</span>
					</span>
				</button>
			{:else}
				<div class="empty">
					{#if data.view === 'done'}
						Noch nichts erledigt.
					{:else}
						<strong>Alles erledigt.</strong>
						<span>Neue Aufgaben und Mitteilungen aus den Modulen erscheinen hier.</span>
					{/if}
				</div>
			{/each}
		</section>

		{#if selected}
			{@const i = selected}
			<section class="detail card" aria-labelledby="dt-h">
				<div class="dhead">
					<div class="tags">
						{#if i.severity === 'urgent'}<span class="chip danger">Dringend</span>{/if}
						<span class="ctx"
							>{i.source_label}{#if i.context}&nbsp;· {i.context}{/if}</span
						>
					</div>
					<h2 id="dt-h">{i.title}</h2>
					<p class="sub">
						{#if i.actor_name}von {i.actor_name} ·
						{/if}{fmt.date(i.created_at)}
						{fmt.time(i.created_at)}{#if i.due_at}&nbsp;· fällig {fmt.relative(i.due_at)}{/if}
					</p>
				</div>
				<div class="dbody">
					{#if i.facts.length || i.reason}
						<dl>
							{#each i.facts as f (f.label)}<dt>{f.label}</dt>
								<dd>{f.value}</dd>{/each}
							{#if i.reason}<dt>Warum bei dir?</dt>
								<dd>{i.reason}</dd>{/if}
						</dl>
					{/if}
					{#if i.body}<div class="body">{@html renderMarkdown(i.body)}</div>{/if}
					{#if i.attachments.length}
						<div class="atts">
							{#each i.attachments as a (a.id)}
								{#if a.is_image}
									<a href={a.url} target="_blank" rel="noopener" class="thumb">
										<img src={a.url} alt={a.filename} loading="lazy" />
									</a>
								{:else}
									<a href="{a.url}?download=true" class="file">{a.filename}</a>
								{/if}
							{/each}
						</div>
					{/if}
				</div>
				<div class="dfoot">
					<div class="links">
						{#if i.link}<a href={i.link}>{i.source === 'core' ? 'Öffnen' : 'Im Modul öffnen'}</a
							>{/if}
						{#if !i.done && i.read}
							<button class="btn btn-link" type="button" onclick={() => change(i, 'unread')}
								>Als ungelesen markieren</button
							>
						{/if}
					</div>
					<div class="buttons">
						{#if i.done}
							<button
								class="btn btn-secondary"
								type="button"
								disabled={busy}
								onclick={() => change(i, 'reopen')}>Wieder öffnen</button
							>
						{:else}
							{#each i.actions as a (a.key)}
								<button
									class="btn {buttonClass(a.style)}"
									type="button"
									disabled={busy}
									onclick={() => action(i, a.key)}>{a.label}</button
								>
							{/each}
							<button
								class="btn {i.actions.length ? 'btn-secondary' : 'btn-primary'}"
								type="button"
								disabled={busy}
								onclick={() => change(i, 'done')}
								>{i.kind === 'task' ? 'Erledigt' : 'Archivieren'}</button
							>
						{/if}
					</div>
				</div>
			</section>
		{:else if items.length}
			<section class="detail card placeholder" aria-hidden="true">
				<p>Wähle links einen Eintrag.</p>
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
	h1 {
		margin: 0;
		font-size: 30px;
		letter-spacing: -0.02em;
	}
	.titles p {
		margin: 0;
		color: var(--muted);
		font-size: 16px;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
	}
	.tabs {
		display: flex;
		gap: 28px;
		border-bottom: 1px solid var(--line);
	}
	.tab {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 44px;
		padding: 0 4px;
		border: 0;
		border-bottom: 2px solid transparent;
		background: none;
		font: inherit;
		font-size: 15px;
		font-weight: 600;
		color: var(--muted);
		cursor: pointer;
	}
	.tab.on {
		color: var(--primary-strong);
		border-bottom-color: var(--primary);
	}
	.count {
		padding: 1px 8px;
		border-radius: 999px;
		background: var(--primary);
		color: #fff;
		font-size: 12px;
	}
	.count.muted {
		background: var(--line-3);
		color: var(--ink-2);
	}
	.layout {
		display: flex;
		flex-wrap: wrap;
		gap: 20px;
		align-items: flex-start;
	}
	.list {
		flex: 1 1 340px;
		min-width: 0;
		padding: 8px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.it {
		display: flex;
		gap: 12px;
		padding: 12px;
		border: 0;
		border-radius: 10px;
		background: none;
		color: var(--ink);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.it:hover {
		background: var(--hover);
	}
	.it.on {
		background: var(--primary-tint);
	}
	.dot,
	.nodot {
		flex: none;
		width: 10px;
		height: 10px;
		margin-top: 6px;
		border-radius: 50%;
	}
	.dot {
		background: var(--primary);
	}
	.txt {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
	}
	.chip.danger {
		background: var(--danger-bg);
		color: var(--danger-ink);
	}
	.kind {
		font-size: 12px;
		font-weight: 600;
		color: var(--muted-2);
	}
	.title {
		font-size: 15px;
		font-weight: 500;
	}
	.unread .title {
		font-weight: 700;
	}
	.meta,
	.ctx {
		font-size: 13px;
		color: var(--muted);
	}
	.empty {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 32px 16px;
		text-align: center;
		color: var(--muted);
	}
	.empty strong {
		color: var(--ink);
	}
	.detail {
		flex: 1.4 1 420px;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	.placeholder {
		display: grid;
		place-items: center;
		min-height: 240px;
		color: var(--muted);
	}
	.dhead {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 22px 24px;
		border-bottom: 1px solid var(--line-2);
	}
	h2 {
		margin: 0;
		font-size: 22px;
	}
	.sub {
		margin: 0;
		font-size: 15px;
		color: var(--muted);
	}
	.dbody {
		display: flex;
		flex-direction: column;
		gap: 18px;
		padding: 22px 24px;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 8px 18px;
		margin: 0;
		font-size: 15px;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	.body :global(p),
	.body :global(ul),
	.body :global(ol) {
		margin: 0 0 8px;
	}
	.body :global(:last-child) {
		margin-bottom: 0;
	}
	.body :global(ul),
	.body :global(ol) {
		padding-left: 22px;
	}
	.body :global(ul) {
		list-style: disc;
	}
	.body :global(ol) {
		list-style: decimal;
	}
	.body {
		margin: 0;
		font-size: 15px;
		line-height: 1.55;
	}
	.atts {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
		gap: 10px;
		max-width: 480px;
	}
	.thumb img {
		display: block;
		width: 100%;
		aspect-ratio: 4 / 3;
		object-fit: cover;
		border-radius: 10px;
		border: 1px solid var(--line);
	}
	.file {
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: 10px;
		font-size: 14px;
		word-break: break-all;
	}
	.dfoot {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		justify-content: space-between;
		padding: 18px 24px;
		border-top: 1px solid var(--line-2);
		background: var(--surface-2);
		border-radius: 0 0 14px 14px;
	}
	.links {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 14px;
		font-weight: 600;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}
</style>
