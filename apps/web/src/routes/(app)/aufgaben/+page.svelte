<script lang="ts">
	import { untrack } from 'svelte';
	import { afterNavigate, goto, invalidateAll } from '$app/navigation';
	import { navigating, page } from '$app/state';
	import { ApiError, post, send } from '#lib/api.ts';
	import { formatter } from '#lib/format.ts';
	import Icon from '#lib/components/Icon.svelte';
	import MarkdownNote from '#lib/components/MarkdownNote.svelte';
	import Attachments from './Attachments.svelte';
	import Checklist from './Checklist.svelte';
	import ListsDialog from './ListsDialog.svelte';
	import type { Person, Task, TaskDetail } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const fmt = $derived(formatter(data.shell.user?.localization));
	const myId = $derived(data.shell.user?.id ?? '');
	const lists = $derived(data.lists.lists);
	const tasks = $derived(data.tasks.tasks);
	const detail = $derived(data.detail);
	const currentList = $derived(lists.find((l) => l.id === data.list) ?? null);

	let message = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);
	let busy = $state(false);
	let manageOpen = $state(false);

	// --- URL state: liste, erledigte, aufgabe ------------------------------------------------
	function setParams(changes: Record<string, string | null>, replace = true) {
		const p = new URLSearchParams(page.url.search);
		for (const [k, v] of Object.entries(changes)) {
			if (v === null) p.delete(k);
			else p.set(k, v);
		}
		p.delete('neu');
		const qs = p.toString();
		return goto(qs ? `?${qs}` : page.url.pathname, { replace, reset: false });
	}

	// --- errors ------------------------------------------------------------------------------
	const ERRORS: Record<string, string> = {
		title_required: 'Gib der Aufgabe einen Titel.',
		assignee_not_member: 'Zuweisen kannst du nur Mitgliedern der Liste.',
		forbidden: 'Dafür fehlt dir die Berechtigung.',
		not_found: 'Diese Aufgabe gibt es nicht mehr.',
		file_type:
			'Dieses Format geht nicht. Erlaubt sind Bilder, PDF, Word, Excel, PowerPoint, OpenDocument, TXT und CSV, ohne Makros.',
		file_too_large: 'Die Datei ist zu gross (höchstens 15 MB).',
		file_infected: 'Die Datei wurde vom Virenschutz abgelehnt.',
		scan_unavailable: 'Der Virenschutz ist gerade nicht erreichbar. Versuche es später.',
		checklist_full: 'Eine Checkliste hat höchstens 50 Punkte.',
		text_required: 'Ein Punkt braucht einen Text.'
	};

	function fail(e: unknown) {
		const d = e instanceof ApiError ? e.detail : '';
		message = {
			tone: 'error',
			text: ERRORS[d] ?? 'Das hat nicht geklappt. Bitte versuche es erneut.'
		};
	}

	// What is running, for the spinner on its button: "toggle:<id>", "delete", "add", …
	let busyKey = $state<string | null>(null);

	async function run(fn: () => Promise<unknown>, ok?: string, key?: string) {
		busy = true;
		busyKey = key ?? null;
		message = null;
		try {
			await fn();
			await invalidateAll();
			if (ok) message = { tone: 'ok', text: ok };
		} catch (e) {
			fail(e);
		} finally {
			busy = false;
			busyKey = null;
		}
	}

	// --- quick add ---------------------------------------------------------------------------
	let newTitle = $state('');
	let newDue = $state('');
	let showDue = $state(false);
	let quickInput = $state<HTMLInputElement>();
	// "Aufgabe erfassen" (quick action) lands here with ?neu=1: focus the field once the
	// navigation has finished (SvelteKit resets focus after navigating).
	afterNavigate(() => {
		if (page.url.searchParams.get('neu') === '1') setTimeout(() => quickInput?.focus(), 0);
	});

	async function add(e: SubmitEvent) {
		e.preventDefault();
		const title = newTitle.trim();
		if (!title) return;
		busy = true;
		busyKey = 'add';
		message = null;
		try {
			await post<TaskDetail>('/aufgaben/tasks', {
				title,
				list_id: data.list ?? undefined,
				due_date: newDue || undefined
			});
			newTitle = '';
			newDue = '';
			showDue = false;
			await invalidateAll();
			quickInput?.focus();
		} catch (err) {
			fail(err);
		} finally {
			busy = false;
			busyKey = null;
		}
	}

	// --- task actions ------------------------------------------------------------------------
	const toggle = (t: Task) =>
		run(
			() => post(`/aufgaben/tasks/${t.id}/${t.status === 'done' ? 'reopen' : 'complete'}`),
			undefined,
			`toggle:${t.id}`
		);

	// While another task or list loads, the part being replaced is dimmed.
	const target = $derived(
		navigating.to?.url.pathname === page.url.pathname ? navigating.to.url.searchParams : null
	);
	const loadingDetail = $derived(
		!!target && (target.get('aufgabe') ?? '') !== (page.url.searchParams.get('aufgabe') ?? '')
	);
	const loadingList = $derived(
		!!target &&
			((target.get('liste') ?? '') !== (page.url.searchParams.get('liste') ?? '') ||
				(target.get('erledigte') ?? '') !== (page.url.searchParams.get('erledigte') ?? ''))
	);

	const patch = (id: string, body: Record<string, unknown>) =>
		run(() => send('PATCH', `/aufgaben/tasks/${id}`, body));

	let confirmDelete = $state(false);
	// Editable copies of the selected task, re-taken whenever the loaded task changes.
	let title = $state('');
	$effect(() => {
		const d = detail;
		untrack(() => {
			title = d?.title ?? '';
			confirmDelete = false;
		});
	});

	function saveTitle() {
		if (!detail) return;
		if (title.trim() && title.trim() !== detail.title) patch(detail.id, { title });
		else title = detail.title;
	}

	const remove = (t: TaskDetail) =>
		run(
			async () => {
				await send('DELETE', `/aufgaben/tasks/${t.id}`);
				await setParams({ aufgabe: null });
			},
			'Aufgabe gelöscht.',
			'delete'
		);

	// --- display helpers ---------------------------------------------------------------------
	const isMe = (p: Person | null) => !!p && p.id === myId;

	const shown = $derived(
		data.showDone
			? `${data.tasks.open} offen, ${data.tasks.done} erledigt`
			: data.tasks.done
				? `${data.tasks.done} erledigte ausgeblendet`
				: `${data.tasks.open} offen`
	);

	function longDue(t: TaskDetail): string {
		if (!t.due_date) return '';
		const d = `${t.due_date}T12:00:00`;
		const w = fmt.weekday(d);
		return `${w.charAt(0).toUpperCase()}${w.slice(1)}, ${fmt.date(d)}`;
	}

	let detailEl = $state<HTMLElement>();
	async function select(t: Task) {
		message = null;
		await setParams({ aufgabe: t.id });
		if (window.matchMedia('(max-width: 900px)').matches) {
			detailEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}
</script>

<svelte:head><title>Aufgaben · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="head">
		<div class="titles">
			<h1>Aufgaben</h1>
			<p>{data.tasks.open} offen{currentList ? ` in ${currentList.name}` : ''}</p>
		</div>
		<div class="tools">
			<label>
				<span class="sr-only">Liste</span>
				<select
					class="input"
					value={data.list ?? ''}
					onchange={(e) =>
						setParams({ liste: e.currentTarget.value || null, aufgabe: null }, false)}
				>
					<option value="">Alle meine Listen</option>
					{#each lists as l (l.id)}
						<option value={l.id}>{l.name}{l.open ? ` (${l.open})` : ''}</option>
					{/each}
				</select>
			</label>
			<button class="btn btn-secondary" type="button" onclick={() => (manageOpen = true)}
				>Listen verwalten</button
			>
		</div>
	</header>

	{#if message}
		<p class="notice {message.tone}" role={message.tone === 'error' ? 'alert' : 'status'}>
			{message.text}
		</p>
	{/if}

	<div class="cols">
		<section class="listcol" aria-label="Aufgabenliste">
			<form class="qadd" onsubmit={add} aria-busy={busyKey === 'add'}>
				{#if busyKey === 'add'}<span
						class="spinner add-spin"
						role="status"
						aria-label="Wird gespeichert"
					></span>{:else}<Icon name="plus" />{/if}
				<label class="sr-only" for="na">Neue Aufgabe</label>
				<input
					id="na"
					bind:this={quickInput}
					bind:value={newTitle}
					maxlength="300"
					autocomplete="off"
					placeholder={currentList
						? `Neue Aufgabe in ${currentList.name} und Enter drücken`
						: 'Neue Aufgabe erfassen und Enter drücken'}
				/>
				{#if showDue}
					<label class="sr-only" for="nd">Fällig am</label>
					<input id="nd" class="due-in" type="date" bind:value={newDue} />
				{:else}
					<button class="btn btn-secondary small" type="button" onclick={() => (showDue = true)}
						>Fällig am</button
					>
				{/if}
				<button class="sr-only" type="submit" disabled={busy}>Hinzufügen</button>
			</form>

			<div class="bar">
				<span class="count">{shown}</span>
				<label class="switch">
					<input
						type="checkbox"
						role="switch"
						checked={data.showDone}
						onchange={(e) => setParams({ erledigte: e.currentTarget.checked ? '1' : null })}
					/>
					<span>Erledigte anzeigen</span>
				</label>
			</div>

			{#if tasks.length}
				<ul class="tasks" class:is-loading={loadingList}>
					{#each tasks as t (t.id)}
						<li class="tk" class:sel={detail?.id === t.id}>
							{#if busyKey === `toggle:${t.id}`}
								<span class="cb-spin" role="status" aria-label="Wird gespeichert"
									><span class="spinner"></span></span
								>
							{:else}
								<input
									class="cb"
									type="checkbox"
									checked={t.status === 'done'}
									disabled={busy}
									onchange={() => toggle(t)}
									aria-label="{t.status === 'done' ? 'Wieder öffnen' : 'Erledigt'}: {t.title}"
								/>
							{/if}
							<button type="button" class="tbtn" onclick={() => select(t)}>
								<span class="tt" class:done={t.status === 'done'}>{t.title}</span>
								<span class="meta">
									{#if t.due_date || t.status === 'done'}<span class="tag {t.due_tone}"
											>{t.due_label}</span
										>{/if}
									{#if !data.list && t.list_kind === 'shared'}<span class="lst">{t.list_name}</span
										>{/if}
									{#if t.created_by && !isMe(t.created_by) && isMe(t.assignee)}<span
											>von {t.created_by.display_name}</span
										>{/if}
									{#if t.checklist_total}<span
											class="chk"
											class:full={t.checklist_done === t.checklist_total}
											title="Checkliste: {t.checklist_done} von {t.checklist_total} erledigt"
											><Icon
												name="list-check"
												size={14}
											/>{t.checklist_done}/{t.checklist_total}</span
										>{/if}
									{#if t.attachments_count}<span class="imgs" title="Anhänge"
											><Icon name="paperclip" size={14} />{t.attachments_count}</span
										>{/if}
								</span>
							</button>
							{#if t.assignee && !isMe(t.assignee)}
								<span class="av" title="Zugewiesen an {t.assignee.display_name}"
									>{t.assignee.initials}</span
								>
							{/if}
						</li>
					{/each}
				</ul>
			{:else}
				<p class="empty">
					{data.tasks.done && !data.showDone
						? 'Alles erledigt.'
						: 'Noch keine Aufgaben. Erfasse oben die erste.'}
				</p>
			{/if}
		</section>

		<section
			class="card detail"
			class:none={!detail}
			class:is-loading={loadingDetail}
			aria-label="Details"
			bind:this={detailEl}
		>
			{#if detail}
				<div class="dhead">
					<span class="eyebrow">{detail.list_name}</span>
					<label class="sr-only" for="td-title">Titel</label>
					<input
						id="td-title"
						class="title-in"
						bind:value={title}
						maxlength="300"
						onblur={saveTitle}
						onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
					/>
				</div>
				<div class="dbody">
					<dl class="dl">
						<dt><label for="td-due">Fällig</label></dt>
						<dd class="due-row">
							<input
								id="td-due"
								class="input slim"
								type="date"
								value={detail.due_date ?? ''}
								onchange={(e) => patch(detail.id, { due_date: e.currentTarget.value || null })}
							/>
							<span class="long">{longDue(detail)}</span>
						</dd>
						<dt><label for="td-as">Zuständig</label></dt>
						<dd>
							<select
								id="td-as"
								class="input slim"
								value={detail.assignee?.id ?? ''}
								onchange={(e) => patch(detail.id, { assignee_id: e.currentTarget.value || null })}
							>
								<option value="">Niemand</option>
								{#each detail.assignable as p (p.id)}
									<option value={p.id}
										>{p.id === myId ? `${p.display_name} (ich)` : p.display_name}</option
									>
								{/each}
								{#if detail.assignee && !detail.assignable.some((p) => p.id === detail.assignee?.id)}
									<option value={detail.assignee.id}>{detail.assignee.display_name}</option>
								{/if}
							</select>
						</dd>
						{#if detail.can_delete && lists.length > 1}
							<dt><label for="td-list">Liste</label></dt>
							<dd>
								<select
									id="td-list"
									class="input slim"
									value={detail.list_id}
									onchange={(e) => patch(detail.id, { list_id: e.currentTarget.value })}
								>
									{#each lists as l (l.id)}<option value={l.id}>{l.name}</option>{/each}
								</select>
							</dd>
						{/if}
						<dt>Erstellt von</dt>
						<dd>
							{detail.created_by?.display_name ?? 'Unbekannt'} · {fmt.relative(detail.created_at)}
						</dd>
						{#if detail.status === 'done' && detail.done_at}
							<dt>Erledigt</dt>
							<dd>
								{fmt.relative(detail.done_at)}{detail.done_by
									? ` von ${detail.done_by.display_name}`
									: ''}
							</dd>
						{/if}
					</dl>

					{#key detail.id}
						<MarkdownNote value={detail.note} onsave={(note) => patch(detail.id, { note })} />
					{/key}

					<Checklist task={detail} {busy} {run} onfinish={() => toggle(detail)} />

					<Attachments task={detail} {busy} {run} localization={data.shell.user?.localization} />
				</div>
				<div class="dfoot">
					{#if detail.can_delete}
						{#if confirmDelete}
							<span class="confirm">
								<button
									class="btn btn-danger"
									type="button"
									disabled={busy}
									aria-busy={busyKey === 'delete'}
									onclick={() => remove(detail)}>Endgültig löschen</button
								>
								<button class="btn btn-link" type="button" onclick={() => (confirmDelete = false)}
									>Abbrechen</button
								>
							</span>
						{:else}
							<button
								class="btn btn-secondary danger-text"
								type="button"
								onclick={() => (confirmDelete = true)}>Löschen</button
							>
						{/if}
					{:else}
						<span></span>
					{/if}
					<button
						class="btn btn-primary"
						type="button"
						disabled={busy}
						aria-busy={busyKey === `toggle:${detail.id}`}
						onclick={() => toggle(detail)}
						>{detail.status === 'done' ? 'Wieder öffnen' : 'Als erledigt markieren'}</button
					>
				</div>
			{:else}
				<p class="pick">
					{data.detailMissing
						? 'Diese Aufgabe gibt es nicht mehr oder du siehst sie nicht.'
						: 'Wähle eine Aufgabe, um Fälligkeit, Zuständigkeit, Notiz, Checkliste und Anhänge zu sehen.'}
				</p>
			{/if}
		</section>
	</div>
</div>

<ListsDialog bind:open={manageOpen} lists={data.lists} {myId} />

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 20px;
		max-width: 1240px;
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
	}
	h1 {
		margin: 0;
		font-size: 30px;
		letter-spacing: -0.02em;
	}
	.titles p {
		margin: 6px 0 0;
		color: var(--muted);
		font-size: 16px;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
	}
	.cols {
		display: flex;
		flex-wrap: wrap;
		gap: 20px;
		align-items: flex-start;
	}
	.listcol {
		flex: 1.3 1 440px;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.qadd {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 52px;
		padding: 0 8px 0 14px;
		background: var(--surface);
		border: 1px solid var(--input);
		border-radius: 12px;
		color: var(--primary);
	}
	.qadd:focus-within {
		border-color: var(--primary);
		outline: 3px solid color-mix(in oklab, var(--primary) 30%, transparent);
	}
	.qadd #na {
		flex: 1;
		min-width: 0;
		min-height: 48px;
		border: 0;
		outline: none;
		background: transparent;
		font: inherit;
		font-size: 16px;
		color: var(--ink);
	}
	.add-spin {
		width: 20px;
		height: 20px;
		margin: 2px;
	}
	.cb-spin {
		display: grid;
		place-content: center;
		flex: none;
		width: 22px;
		height: 22px;
		margin-top: 1px;
		color: var(--primary);
	}
	.due-in {
		min-height: 36px;
		padding: 0 8px;
		border: 1px solid var(--input);
		border-radius: 8px;
		background: var(--surface);
		color: var(--ink);
		font: inherit;
		font-size: 14px;
	}
	.small {
		min-height: 36px;
		padding: 0 12px;
		font-size: 14px;
	}
	.bar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		padding: 12px 4px 4px;
	}
	.count {
		font-size: 13px;
		color: var(--muted);
	}
	.switch {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		min-height: 40px;
		font-size: 14px;
		color: var(--ink-2);
		cursor: pointer;
	}
	.switch input {
		appearance: none;
		position: relative;
		flex: none;
		width: 46px;
		height: 28px;
		margin: 0;
		border-radius: 999px;
		background: var(--input);
		cursor: pointer;
	}
	.switch input::before {
		content: '';
		position: absolute;
		top: 3px;
		left: 3px;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: #fff;
		box-shadow: 0 1px 2px rgb(0 0 0 / 0.2);
		transition: left 0.15s;
	}
	.switch input:checked {
		background: var(--primary);
	}
	.switch input:checked::before {
		left: 21px;
	}
	.switch input:focus-visible,
	.cb:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
	}
	.tasks {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.tk {
		display: flex;
		align-items: flex-start;
		gap: 12px;
		padding: 10px 12px;
		border-radius: 10px;
	}
	.tk:hover {
		background: var(--hover);
	}
	.tk.sel {
		background: var(--primary-tint);
	}
	.cb {
		appearance: none;
		display: grid;
		place-content: center;
		flex: none;
		width: 22px;
		height: 22px;
		margin: 1px 0 0;
		border: 2px solid var(--input);
		border-radius: 7px;
		background: var(--surface);
		cursor: pointer;
	}
	.cb:checked {
		background: var(--primary);
		border-color: var(--primary);
	}
	.cb:checked::after {
		content: '';
		width: 6px;
		height: 11px;
		border: solid #fff;
		border-width: 0 2.5px 2.5px 0;
		transform: rotate(45deg) translate(-1px, -1px);
	}
	.tbtn {
		display: block;
		flex: 1;
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
		background: none;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.tt {
		display: block;
		font-size: 15px;
		font-weight: 500;
	}
	.tt.done {
		color: var(--muted);
		text-decoration: line-through;
	}
	.meta:empty {
		display: none;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-top: 3px;
		font-size: 13px;
		color: var(--muted);
	}
	.tag,
	.lst {
		padding: 1px 8px;
		border-radius: 999px;
		background: var(--line-3);
		color: var(--ink-2);
		font-size: 12px;
		font-weight: 600;
	}
	.tag.over {
		background: var(--danger-bg);
		color: var(--danger-ink);
	}
	.tag.today {
		background: var(--warn-bg);
		color: var(--warn-ink);
	}
	.tag.none {
		padding: 1px 0;
		background: transparent;
		color: var(--muted);
	}
	.chk {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.chk.full {
		color: var(--ok-ink);
		font-weight: 600;
	}
	.imgs {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.av {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--info-bg);
		color: var(--info-ink);
		font-size: 10px;
		font-weight: 700;
	}
	.empty {
		margin: 0;
		padding: 28px 12px;
		color: var(--muted);
	}
	.detail {
		position: sticky;
		top: 20px;
		display: flex;
		flex: 1.1 1 380px;
		flex-direction: column;
		min-width: 0;
	}
	.detail.none {
		background: transparent;
		border-style: dashed;
	}
	.pick {
		margin: 0;
		padding: 28px 24px;
		color: var(--muted);
		font-size: 15px;
	}
	.dhead {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 22px 24px 18px;
		border-bottom: 1px solid var(--line-2);
	}
	.eyebrow {
		font-size: 13px;
		color: var(--muted);
	}
	.title-in {
		margin: 0 -8px;
		padding: 4px 8px;
		border: 1px solid transparent;
		border-radius: 8px;
		background: transparent;
		color: var(--ink);
		font: inherit;
		font-size: 20px;
		font-weight: 700;
	}
	.title-in:hover {
		border-color: var(--line);
	}
	.title-in:focus {
		outline: none;
		border-color: var(--primary);
		background: var(--surface);
	}
	.dbody {
		display: flex;
		flex-direction: column;
		gap: 18px;
		padding: 18px 24px 20px;
	}
	.dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		align-items: center;
		gap: 10px 20px;
		margin: 0;
		font-size: 14px;
	}
	.dl dt {
		color: var(--muted);
	}
	.dl dd {
		min-width: 0;
		margin: 0;
	}
	.slim {
		max-width: 100%;
		min-height: 38px;
		font-size: 14px;
	}
	.due-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 10px;
	}
	.long {
		color: var(--muted);
		font-size: 13px;
	}
	.dfoot {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		margin-top: auto;
		padding: 16px 24px;
		border-top: 1px solid var(--line-2);
		border-radius: 0 0 14px 14px;
		background: var(--surface-2);
	}
	.danger-text {
		color: var(--danger-ink);
	}
	.confirm {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	@media (max-width: 900px) {
		.detail {
			position: static;
		}
		.detail.none {
			display: none;
		}
	}
</style>
