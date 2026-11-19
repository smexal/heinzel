<script lang="ts">
	// Shared lists: create, rename, members, leave, delete. Opened from the Aufgaben page.
	import { untrack } from 'svelte';
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, get, post, put, send } from '#lib/api.ts';
	import type { Lists, Person } from './+page.server.ts';

	type Member = Person & { role: 'owner' | 'member' };

	let {
		open = $bindable(false),
		lists,
		myId
	}: { open?: boolean; lists: Lists; myId: string } = $props();

	let dialog: HTMLDialogElement;
	let selected = $state<string | null>(null);
	let members = $state<Member[]>([]);
	let newName = $state('');
	let rename = $state('');
	let query = $state('');
	let people = $state<Person[]>([]);
	let confirmDelete = $state(false);
	let busy = $state(false);
	let searching = $state(false);
	let loadingMembers = $state(false);
	let error = $state('');

	const shared = $derived(lists.lists.filter((l) => l.kind === 'shared'));
	const personal = $derived(lists.lists.find((l) => l.kind === 'personal'));
	const current = $derived(shared.find((l) => l.id === selected) ?? null);
	const isOwner = $derived(current?.role === 'owner');

	$effect(() => {
		if (open && !dialog.open) {
			error = '';
			dialog.showModal();
		} else if (!open && dialog.open) {
			dialog.close();
		}
	});

	$effect(() => {
		const id = selected;
		untrack(() => {
			members = [];
			confirmDelete = false;
			query = '';
			people = [];
			rename = current?.name ?? '';
		});
		if (id) loadMembers(id);
	});

	async function loadMembers(id: string) {
		loadingMembers = true;
		try {
			members = await get<Member[]>(`/aufgaben/lists/${id}/members`);
		} catch {
			members = [];
		} finally {
			loadingMembers = false;
		}
	}

	// People search for adding members (debounced)
	$effect(() => {
		const q = query.trim();
		if (!q || !isOwner) {
			people = [];
			return;
		}
		const t = setTimeout(async () => {
			searching = true;
			try {
				const found = await get<Person[]>(`/aufgaben/people?q=${encodeURIComponent(q)}`);
				people = found.filter((p) => !members.some((m) => m.id === p.id));
			} catch {
				people = [];
			} finally {
				searching = false;
			}
		}, 200);
		return () => clearTimeout(t);
	});

	const MESSAGES: Record<string, string> = {
		shared_lists_disabled: 'Geteilte Listen sind ausgeschaltet.',
		forbidden: 'Dafür fehlt dir die Berechtigung.',
		owner_stays: 'Der Besitzer bleibt Mitglied der Liste.',
		name_required: 'Gib der Liste einen Namen.'
	};

	// The running action, for its spinner: "create", "rename", "add:<id>", "remove:<id>", "delete"
	let busyKey = $state<string | null>(null);

	async function act(fn: () => Promise<unknown>, key: string) {
		busy = true;
		busyKey = key;
		error = '';
		try {
			await fn();
			await invalidateAll();
		} catch (e) {
			const d = e instanceof ApiError ? e.detail : '';
			error = MESSAGES[d] ?? 'Das hat nicht geklappt. Bitte versuche es erneut.';
		} finally {
			busy = false;
			busyKey = null;
		}
	}

	function create(e: SubmitEvent) {
		e.preventDefault();
		const name = newName.trim();
		if (!name) return;
		act(async () => {
			const lst = await post<{ id: string }>('/aufgaben/lists', { name });
			newName = '';
			selected = lst.id;
		}, 'create');
	}

	function saveName(e: SubmitEvent) {
		e.preventDefault();
		if (!current || !rename.trim() || rename.trim() === current.name) return;
		act(() => put(`/aufgaben/lists/${current.id}`, { name: rename }), 'rename');
	}

	const addMember = (p: Person) =>
		act(async () => {
			await post(`/aufgaben/lists/${current!.id}/members`, { user_id: p.id });
			query = '';
			await loadMembers(current!.id);
		}, `add:${p.id}`);

	const removeMember = (m: Member) =>
		act(async () => {
			await send('DELETE', `/aufgaben/lists/${current!.id}/members/${m.id}`);
			if (m.id === myId) {
				selected = null;
				if (page.url.searchParams.get('liste')) await goto('/aufgaben', { replace: true });
			} else await loadMembers(current!.id);
		}, `remove:${m.id}`);

	const removeList = () =>
		act(async () => {
			const id = current!.id;
			await send('DELETE', `/aufgaben/lists/${id}`);
			selected = null;
			if (page.url.searchParams.get('liste') === id) await goto('/aufgaben', { replace: true });
		}, 'delete');
</script>

<dialog
	bind:this={dialog}
	class="card lists"
	aria-labelledby="ld-h"
	onclose={() => (open = false)}
	onclick={(e) => {
		if (e.target === dialog) open = false;
	}}
>
	<div class="dh">
		<h2 id="ld-h">Listen verwalten</h2>
		<button class="btn btn-link" type="button" onclick={() => (open = false)}>Schliessen</button>
	</div>

	<div class="db">
		{#if error}<p class="notice error" role="alert">{error}</p>{/if}

		{#if personal}
			<p class="hint">
				<strong>{personal.name}</strong> ist deine persönliche Liste. Nur du siehst sie, ausser du weist
				jemandem eine Aufgabe daraus zu.
			</p>
		{/if}

		{#if lists.can_share}
			<form class="row" onsubmit={create}>
				<label class="sr-only" for="ld-new">Name der neuen Liste</label>
				<input
					id="ld-new"
					class="input grow"
					placeholder="Neue geteilte Liste, z.B. Sekretariat"
					maxlength="80"
					bind:value={newName}
				/>
				<button
					class="btn btn-primary"
					type="submit"
					disabled={busy || !newName.trim()}
					aria-busy={busyKey === 'create'}>Erstellen</button
				>
			</form>
		{/if}

		{#if shared.length}
			<ul class="ll">
				{#each shared as l (l.id)}
					<li>
						<button
							type="button"
							class="li"
							class:on={selected === l.id}
							aria-expanded={selected === l.id}
							onclick={() => (selected = selected === l.id ? null : l.id)}
						>
							<span class="n">{l.name}</span>
							<span class="m"
								>{l.members}
								{l.members === 1 ? 'Mitglied' : 'Mitglieder'} · {l.role === 'owner'
									? 'Besitzer'
									: 'Mitglied'}</span
							>
						</button>
						{#if selected === l.id && current}
							<div class="panel">
								{#if isOwner}
									<form class="row" onsubmit={saveName}>
										<label class="sr-only" for="ld-name">Name</label>
										<input id="ld-name" class="input grow" maxlength="80" bind:value={rename} />
										<button
											class="btn btn-secondary"
											type="submit"
											disabled={busy || !rename.trim() || rename.trim() === current.name}
											aria-busy={busyKey === 'rename'}>Umbenennen</button
										>
									</form>
								{/if}

								<h3>
									Mitglieder{#if loadingMembers && !members.length}
										<span class="spinner small-spin" role="status" aria-label="Wird geladen"
										></span>{/if}
								</h3>
								<ul class="members">
									{#each members as m (m.id)}
										<li>
											<span class="av">{m.initials}</span>
											<span class="who"
												>{m.display_name}{m.id === myId ? ' (ich)' : ''}{m.role === 'owner'
													? ' · Besitzer'
													: ''}</span
											>
											{#if m.role !== 'owner' && (isOwner || m.id === myId)}
												<button
													class="btn btn-link"
													type="button"
													disabled={busy}
													aria-busy={busyKey === `remove:${m.id}`}
													onclick={() => removeMember(m)}
													>{m.id === myId ? 'Liste verlassen' : 'Entfernen'}</button
												>
											{/if}
										</li>
									{/each}
								</ul>

								{#if isOwner}
									<div class="add">
										<label class="field">
											<span>Mitglied hinzufügen</span>
											<input
												class="input"
												placeholder="Name oder E-Mail"
												autocomplete="off"
												bind:value={query}
											/>
										</label>
										{#if people.length}
											<ul class="found">
												{#each people as p (p.id)}
													<li>
														<button
															type="button"
															class="pick"
															disabled={busy}
															onclick={() => addMember(p)}
														>
															<span class="av">{p.initials}</span>{p.display_name}
															{#if busyKey === `add:${p.id}`}<span class="spinner small-spin"
																></span>{/if}
														</button>
													</li>
												{/each}
											</ul>
										{:else if searching}
											<p class="hint"><span class="spinner small-spin"></span> Suche …</p>
										{:else if query.trim()}
											<p class="hint">Niemand gefunden.</p>
										{/if}
									</div>

									<div class="danger">
										{#if confirmDelete}
											<p class="hint">
												«{current.name}» wird mit allen Aufgaben und Bildern gelöscht. Das lässt
												sich nicht rückgängig machen.
											</p>
											<button
												class="btn btn-danger"
												type="button"
												disabled={busy}
												aria-busy={busyKey === 'delete'}
												onclick={removeList}>Liste endgültig löschen</button
											>
											<button
												class="btn btn-link"
												type="button"
												onclick={() => (confirmDelete = false)}>Abbrechen</button
											>
										{:else}
											<button
												class="btn btn-secondary danger-text"
												type="button"
												onclick={() => (confirmDelete = true)}>Liste löschen</button
											>
										{/if}
									</div>
								{/if}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{:else}
			<p class="hint">
				{lists.can_share
					? 'Noch keine geteilten Listen. Erstelle eine für dein Team.'
					: 'Du bist in keiner geteilten Liste.'}
			</p>
		{/if}
	</div>
</dialog>

<style>
	.lists {
		width: min(560px, calc(100vw - 32px));
		max-height: calc(100vh - 80px);
		margin: 56px auto auto;
		padding: 0;
		color: var(--ink);
		overflow: auto;
	}
	.lists::backdrop {
		background: rgb(0 0 0 / 0.35);
	}
	.dh {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 18px 22px;
		border-bottom: 1px solid var(--line-2);
	}
	h2 {
		margin: 0;
		font-size: 20px;
	}
	h3 {
		margin: 6px 0 0;
		color: var(--muted);
		font-size: 13px;
		font-weight: 600;
	}
	.db {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 18px 22px 22px;
	}
	.small-spin {
		width: 14px;
		height: 14px;
		margin-left: 6px;
		color: var(--primary);
	}
	.hint {
		margin: 0;
		color: var(--muted);
		font-size: 14px;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}
	.grow {
		flex: 1 1 220px;
	}
	.ll,
	.members,
	.found {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.li {
		display: flex;
		flex-direction: column;
		gap: 2px;
		width: 100%;
		padding: 12px 14px;
		border: 1px solid var(--line);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.li.on {
		border-color: color-mix(in oklab, var(--primary) 40%, var(--surface));
		background: var(--primary-tint);
	}
	.n {
		font-weight: 600;
	}
	.m {
		color: var(--muted);
		font-size: 13px;
	}
	.panel {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 14px 4px 8px 14px;
	}
	.members li,
	.pick {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 40px;
		font-size: 14px;
	}
	.who {
		flex: 1;
	}
	.pick {
		width: 100%;
		padding: 4px 8px;
		border: 0;
		border-radius: 8px;
		background: none;
		color: var(--ink);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.pick:hover {
		background: var(--hover);
	}
	.av {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--info-bg);
		color: var(--info-ink);
		font-size: 11px;
		font-weight: 700;
	}
	.add {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.danger {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		padding-top: 8px;
		border-top: 1px solid var(--line-2);
	}
	.danger .hint {
		flex-basis: 100%;
	}
	.danger-text {
		color: var(--danger-ink);
	}
</style>
