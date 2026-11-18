<script lang="ts">
	import { untrack } from 'svelte';
	import { invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post, put, send } from '#lib/api.ts';
	import { StepUpCancelled, withStepUp } from '#lib/stepup.svelte.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { formatter, initials } from '#lib/format.ts';
	import type { AdminUser } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const fmt = $derived(formatter(data.shell.user?.localization));

	const roleName = $derived(new Map(data.roles.map((r) => [r.key, r.name])));
	const invitedCount = $derived(data.users.filter((u) => u.status === 'invited').length);

	// --- filters --------------------------------------------------------------------------
	let tab = $state<'users' | 'roles'>(
		untrack(() => (page.url.searchParams.get('tab') === 'rollen' ? 'roles' : 'users'))
	);
	let query = $state(untrack(() => page.url.searchParams.get('q') ?? ''));
	$effect(() => {
		const q = page.url.searchParams.get('q');
		const t = page.url.searchParams.get('tab');
		untrack(() => {
			if (q !== null) {
				query = q;
				tab = 'users';
			}
			if (t === 'rollen') tab = 'roles';
		});
	});
	let roleFilter = $state('');
	let statusFilter = $state('');

	const visible = $derived(
		data.users.filter((u) => {
			const q = query.trim().toLowerCase();
			if (q && !u.display_name.toLowerCase().includes(q) && !u.email.includes(q)) return false;
			if (roleFilter && !u.roles.includes(roleFilter)) return false;
			if (statusFilter && u.status !== statusFilter) return false;
			return true;
		})
	);

	const STATUS: Record<AdminUser['status'], { label: string; tone: string }> = {
		active: { label: 'Aktiv', tone: 'ok' },
		invited: { label: 'Eingeladen', tone: 'info' },
		deactivated: { label: 'Deaktiviert', tone: 'muted' }
	};

	// --- feedback -------------------------------------------------------------------------
	let notice = $state<{ tone: 'ok' | 'error' | 'info'; text: string } | null>(null);

	const ERRORS: Record<string, string> = {
		email_exists: 'Für diese E-Mail-Adresse gibt es bereits ein Konto.',
		last_admin: 'Das ist die letzte aktive Person mit der Rolle Administration.',
		cannot_deactivate_self: 'Du kannst dich nicht selbst deaktivieren.',
		role_exceeds_own_permissions:
			'Diese Rolle hat Berechtigungen, die du selbst nicht hast. Du kannst sie nicht vergeben.',
		unknown_role: 'Eine der Rollen gibt es nicht mehr. Lade die Seite neu.',
		not_invited: 'Diese Person hat die Einladung bereits angenommen.',
		forbidden: 'Dafür fehlt dir die Berechtigung.',
		role_in_use: 'Die Rolle ist noch Personen zugewiesen. Entferne sie zuerst bei diesen Personen.',
		system_role: 'Fest eingerichtete Rollen können nicht gelöscht werden.',
		admin_role_fixed: 'Die Rolle Administration hat immer alle Berechtigungen.',
		unknown_permission: 'Eine Berechtigung gibt es nicht mehr. Lade die Seite neu.'
	};

	async function act(action: () => Promise<string>) {
		notice = null;
		try {
			notice = { tone: 'ok', text: await action() };
			await invalidateAll();
		} catch (e) {
			if (e instanceof StepUpCancelled) return;
			const detail = e instanceof ApiError ? e.detail : '';
			notice = {
				tone: 'error',
				text: ERRORS[detail] ?? 'Das hat nicht geklappt. Bitte versuche es erneut.'
			};
		}
	}

	const mailNote = (sent: boolean, email: string) =>
		sent
			? `Einladung an ${email} gesendet.`
			: `Die Person ist angelegt, aber die E-Mail an ${email} konnte nicht gesendet werden. Sende die Einladung später erneut.`;

	// --- row menu -------------------------------------------------------------------------
	// The menu is positioned fixed next to its button, so the scrolling table cannot clip it.
	let menuFor = $state<string | null>(null);
	let menuPos = $state({ top: 0, right: 0 });

	function toggleMenu(id: string, e: MouseEvent) {
		if (menuFor === id) {
			menuFor = null;
			return;
		}
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		menuPos = { top: r.bottom + 4, right: window.innerWidth - r.right };
		menuFor = id;
	}

	function closeMenus(e: MouseEvent | KeyboardEvent) {
		if (e instanceof KeyboardEvent && e.key !== 'Escape') return;
		if (e instanceof MouseEvent && (e.target as HTMLElement).closest('.menu-wrap')) return;
		menuFor = null;
	}

	// --- invite dialog --------------------------------------------------------------------
	let inviteDialog: HTMLDialogElement;
	let invite = $state({ email: '', display_name: '', roles: ['staff'] as string[] });
	let inviteError = $state('');
	let busy = $state(false);

	function openInvite() {
		invite = { email: '', display_name: '', roles: ['staff'] };
		inviteError = '';
		inviteDialog.showModal();
	}

	async function submitInvite(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		inviteError = '';
		try {
			const r = await post<{ mail_sent: boolean; user: AdminUser }>('/admin/users', invite);
			inviteDialog.close();
			notice = { tone: r.mail_sent ? 'ok' : 'info', text: mailNote(r.mail_sent, r.user.email) };
			await invalidateAll();
		} catch (err) {
			const detail = err instanceof ApiError ? err.detail : '';
			inviteError =
				ERRORS[detail] ??
				(err instanceof ApiError && err.status === 422
					? 'Bitte prüfe Name und E-Mail-Adresse.'
					: 'Das hat nicht geklappt. Bitte versuche es erneut.');
		} finally {
			busy = false;
		}
	}

	// --- roles dialog ---------------------------------------------------------------------
	let rolesDialog: HTMLDialogElement;
	let rolesUser = $state<AdminUser | null>(null);
	let rolesSel = $state<string[]>([]);

	function openRoles(u: AdminUser) {
		menuFor = null;
		rolesUser = u;
		rolesSel = [...u.roles];
		rolesDialog.showModal();
	}

	async function submitRoles(e: SubmitEvent) {
		e.preventDefault();
		const u = rolesUser;
		if (!u) return;
		rolesDialog.close();
		await act(async () => {
			await withStepUp(() => put(`/admin/users/${u.id}/roles`, { roles: rolesSel }));
			return `Rollen von ${u.display_name} gespeichert.`;
		});
	}

	// --- confirm dialog -------------------------------------------------------------------
	let confirmDialog: HTMLDialogElement;
	let confirmState = $state<{
		title: string;
		text: string;
		action: string;
		run: () => Promise<string>;
	} | null>(null);

	function ask(title: string, text: string, action: string, run: () => Promise<string>) {
		menuFor = null;
		confirmState = { title, text, action, run };
		confirmDialog.showModal();
	}

	async function confirmed() {
		const c = confirmState;
		confirmDialog.close();
		if (c) await act(c.run);
	}

	const deactivate = (u: AdminUser) =>
		ask(
			`${u.display_name} deaktivieren?`,
			'Die Person wird sofort abgemeldet und kann sich nicht mehr anmelden. Ihre Daten bleiben erhalten.',
			'Deaktivieren',
			async () => {
				await post(`/admin/users/${u.id}/deactivate`);
				return `${u.display_name} ist deaktiviert.`;
			}
		);

	const resetMfa = (u: AdminUser) =>
		ask(
			`2FA von ${u.display_name} zurücksetzen?`,
			'Die Person wird abgemeldet und richtet bei der nächsten Anmeldung eine neue Authenticator-App ein. Nutze das, wenn das Telefon verloren ging.',
			'2FA zurücksetzen',
			async () => {
				await post(`/admin/users/${u.id}/mfa-reset`);
				return `2FA von ${u.display_name} ist zurückgesetzt.`;
			}
		);

	const activate = (u: AdminUser) => {
		menuFor = null;
		act(async () => {
			const r = await post<AdminUser>(`/admin/users/${u.id}/activate`);
			return r.status === 'invited'
				? `${u.display_name} ist wieder eingeladen. Sende die Einladung erneut.`
				: `${u.display_name} ist wieder aktiv.`;
		});
	};

	const resend = (u: AdminUser) => {
		menuFor = null;
		act(async () => {
			const r = await post<{ mail_sent: boolean }>(`/admin/users/${u.id}/invite`);
			if (!r.mail_sent) throw new ApiError(502, 'mail_failed');
			return `Einladung an ${u.email} erneut gesendet.`;
		});
	};

	function login(u: AdminUser): { text: string; tone: string } {
		if (!u.has_password) return { text: 'Noch nicht eingerichtet', tone: 'muted' };
		return u.mfa_enabled
			? { text: '2FA aktiv', tone: 'strong' }
			: { text: '2FA ausstehend', tone: 'warn' };
	}

	// --- role editor ----------------------------------------------------------------------
	const mine = $derived(new Set(data.myPermissions));
	let roleDialog: HTMLDialogElement;
	let editing = $state<{
		key: string | null;
		is_system: boolean;
		members: number;
		name: string;
		description: string;
		permissions: string[];
	}>({ key: null, is_system: false, members: 0, name: '', description: '', permissions: [] });
	let roleError = $state('');

	function newRole() {
		editing = {
			key: null,
			is_system: false,
			members: 0,
			name: '',
			description: '',
			permissions: []
		};
		roleError = '';
		roleDialog.showModal();
	}

	function editRole(key: string) {
		const r = data.roles.find((x) => x.key === key);
		if (!r) return;
		editing = {
			key: r.key,
			is_system: r.is_system,
			members: r.members,
			name: r.name,
			description: r.description ?? '',
			permissions: [...r.permissions]
		};
		roleError = '';
		roleDialog.showModal();
	}

	async function saveRole(e: SubmitEvent) {
		e.preventDefault();
		const r = editing;
		const body = { name: r.name, description: r.description || null, permissions: r.permissions };
		roleError = '';
		try {
			await withStepUp(() =>
				r.key ? put(`/admin/roles/${r.key}`, body) : post('/admin/roles', body)
			);
			roleDialog.close();
			notice = {
				tone: 'ok',
				text: r.key ? `Rolle ${r.name} gespeichert.` : `Rolle ${r.name} angelegt.`
			};
			await invalidateAll();
		} catch (err) {
			if (err instanceof StepUpCancelled) return;
			const d = err instanceof ApiError ? err.detail : '';
			roleError = ERRORS[d] ?? 'Das hat nicht geklappt. Bitte versuche es erneut.';
		}
	}

	async function deleteRole() {
		const r = editing;
		if (!r.key) return;
		roleError = '';
		try {
			await withStepUp(() => send('DELETE', `/admin/roles/${r.key}`));
			roleDialog.close();
			notice = { tone: 'ok', text: `Rolle ${r.name} gelöscht.` };
			await invalidateAll();
		} catch (err) {
			if (err instanceof StepUpCancelled) return;
			const d = err instanceof ApiError ? err.detail : '';
			roleError = ERRORS[d] ?? 'Das hat nicht geklappt. Bitte versuche es erneut.';
		}
	}

	// --- roles matrix ---------------------------------------------------------------------
	const groups = $derived(
		Object.entries(
			data.permissions.reduce<Record<string, typeof data.permissions>>((acc, p) => {
				(acc[p.group_label] ??= []).push(p);
				return acc;
			}, {})
		)
	);
	const has = (roleKey: string, perm: string) =>
		data.roles.find((r) => r.key === roleKey)?.permissions.includes(perm) ?? false;
</script>

<svelte:window
	onclick={closeMenus}
	onkeydown={closeMenus}
	onresize={() => (menuFor = null)}
	onscroll={() => (menuFor = null)}
/>
<svelte:head><title>Benutzer & Rollen · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="head">
		<div class="titles">
			<span class="eyebrow">Administration</span>
			<h1>Benutzer &amp; Rollen</h1>
			<p>
				{data.users.length} Benutzer · {data.roles.length} Rollen · Änderungen gelten sofort und werden
				protokolliert.
			</p>
		</div>
		<button class="btn btn-primary" type="button" onclick={openInvite}>
			<Icon name="plus" size={18} />Benutzer einladen
		</button>
	</header>

	<nav class="tabs" aria-label="Bereiche">
		<button
			type="button"
			class="tab"
			class:on={tab === 'users'}
			aria-current={tab === 'users' ? 'page' : undefined}
			onclick={() => (tab = 'users')}
			>Benutzer{#if invitedCount}<span class="count">{invitedCount} eingeladen</span>{/if}</button
		>
		<button
			type="button"
			class="tab"
			class:on={tab === 'roles'}
			aria-current={tab === 'roles' ? 'page' : undefined}
			onclick={() => (tab = 'roles')}>Rollen &amp; Berechtigungen</button
		>
	</nav>

	{#if notice}
		<p class="notice {notice.tone}" role="status">{notice.text}</p>
	{/if}

	{#if tab === 'users'}
		<div class="filters">
			<label class="search">
				<Icon name="search" size={18} />
				<span class="sr-only">Benutzer suchen</span>
				<input type="search" placeholder="Name oder E-Mail" bind:value={query} />
			</label>
			<label>
				<span class="sr-only">Rolle</span>
				<select class="input" bind:value={roleFilter}>
					<option value="">Alle Rollen</option>
					{#each data.roles as r (r.key)}<option value={r.key}>{r.name}</option>{/each}
				</select>
			</label>
			<label>
				<span class="sr-only">Status</span>
				<select class="input" bind:value={statusFilter}>
					<option value="">Alle Status</option>
					<option value="active">Aktiv</option>
					<option value="invited">Eingeladen</option>
					<option value="deactivated">Deaktiviert</option>
				</select>
			</label>
		</div>

		<div class="card table-wrap">
			<table>
				<thead>
					<tr>
						<th scope="col">Name</th>
						<th scope="col">Rollen</th>
						<th scope="col">Anmeldung</th>
						<th scope="col">Status</th>
						<th scope="col">Zuletzt aktiv</th>
						<th scope="col"><span class="sr-only">Aktionen</span></th>
					</tr>
				</thead>
				<tbody>
					{#each visible as u (u.id)}
						{@const l = login(u)}
						<tr class:off={u.status === 'deactivated'}>
							<td>
								<div class="who">
									<span class="avatar" aria-hidden="true">{initials(u.display_name)}</span>
									<span class="names">
										<strong>{u.display_name}</strong>
										<small>{u.email}</small>
									</span>
								</div>
							</td>
							<td>
								<div class="chips">
									{#each u.roles as r (r)}
										<span class="chip" class:ok={r === 'admin'}>{roleName.get(r) ?? r}</span>
									{:else}
										<span class="none">keine</span>
									{/each}
								</div>
							</td>
							<td>
								<span class="login {l.tone}"
									>{u.has_password ? `Passwort · ${l.text}` : l.text}</span
								>
							</td>
							<td><span class="chip {STATUS[u.status].tone}">{STATUS[u.status].label}</span></td>
							<td class="when">
								{u.status === 'invited' && u.invite_expires_at
									? `Einladung bis ${fmt.relative(u.invite_expires_at)}`
									: fmt.relative(u.last_login_at)}
							</td>
							<td class="actions">
								<div class="menu-wrap">
									<button
										class="icon-btn"
										type="button"
										aria-label="Aktionen für {u.display_name}"
										aria-haspopup="menu"
										aria-expanded={menuFor === u.id}
										onclick={(e) => toggleMenu(u.id, e)}
									>
										<Icon name="more" />
									</button>
									{#if menuFor === u.id}
										<div
											class="menu card"
											role="menu"
											style="top: {menuPos.top}px; right: {menuPos.right}px"
										>
											<button role="menuitem" type="button" onclick={() => openRoles(u)}
												>Rollen ändern</button
											>
											{#if u.status === 'invited'}
												<button role="menuitem" type="button" onclick={() => resend(u)}
													>Einladung erneut senden</button
												>
											{/if}
											{#if u.mfa_enabled}
												<button role="menuitem" type="button" onclick={() => resetMfa(u)}
													>2FA zurücksetzen</button
												>
											{/if}
											{#if u.status === 'deactivated'}
												<button role="menuitem" type="button" onclick={() => activate(u)}
													>Wieder aktivieren</button
												>
											{:else}
												<button
													role="menuitem"
													type="button"
													class="danger"
													onclick={() => deactivate(u)}>Deaktivieren</button
												>
											{/if}
										</div>
									{/if}
								</div>
							</td>
						</tr>
					{:else}
						<tr><td colspan="6" class="empty">Keine Benutzer gefunden.</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<section class="roles" aria-labelledby="mx-h">
			<div class="roles-head">
				<div>
					<h2 id="mx-h">Rollen &amp; Berechtigungen</h2>
					<p class="sub">
						Module bringen ihre Berechtigungen mit. Klicke auf eine Rolle, um sie zu bearbeiten.
						Änderungen bestätigst du erneut mit 2FA.
					</p>
				</div>
				<button class="btn btn-secondary" type="button" onclick={newRole}>
					<Icon name="plus" size={18} />Neue Rolle
				</button>
			</div>
			<div class="card table-wrap">
				<table class="matrix">
					<thead>
						<tr>
							<th scope="col">Berechtigung</th>
							{#each data.roles as r (r.key)}
								<th scope="col">
									{#if r.key === 'admin'}
										<span class="rolehead" title="Hat immer alle Berechtigungen">{r.name}</span>
									{:else}
										<button type="button" class="rolehead edit" onclick={() => editRole(r.key)}>
											{r.name}<span class="sr-only"> bearbeiten</span>
										</button>
									{/if}
									<small>{r.members} {r.members === 1 ? 'Person' : 'Personen'}</small>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each groups as [label, perms] (label)}
							<tr class="group"><td colspan={data.roles.length + 1}>{label}</td></tr>
							{#each perms as p (p.id)}
								<tr>
									<td>
										<span class="perm"><strong>{p.label}</strong><code>{p.id}</code></span>
									</td>
									{#each data.roles as r (r.key)}
										<td class="mark">
											{#if has(r.key, p.id)}
												<span class="yes" role="img" aria-label="Ja"><Icon name="check" /></span>
											{:else}
												<span class="no" aria-label="Nein">–</span>
											{/if}
										</td>
									{/each}
								</tr>
							{/each}
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}
</div>

<dialog bind:this={inviteDialog} class="dialog card" aria-labelledby="inv-h">
	<form onsubmit={submitInvite}>
		<h2 id="inv-h">Benutzer einladen</h2>
		<p class="sub">
			Die Person erhält eine E-Mail mit einem Link, der 7 Tage gültig ist. Damit legt sie ihr
			Passwort fest und richtet die Zwei-Faktor-Anmeldung ein.
		</p>
		<label class="field">
			<span>Name</span>
			<input class="input" required maxlength="200" bind:value={invite.display_name} />
		</label>
		<label class="field">
			<span>E-Mail</span>
			<input class="input" type="email" required bind:value={invite.email} />
		</label>
		<fieldset>
			<legend>Rollen</legend>
			{#each data.roles as r (r.key)}
				<label class="check">
					<input type="checkbox" value={r.key} bind:group={invite.roles} />
					<span
						><strong>{r.name}</strong>{#if r.description}<small>{r.description}</small>{/if}</span
					>
				</label>
			{/each}
		</fieldset>
		{#if inviteError}<p class="notice error" role="alert">{inviteError}</p>{/if}
		<div class="buttons">
			<button class="btn btn-secondary" type="button" onclick={() => inviteDialog.close()}
				>Abbrechen</button
			>
			<button class="btn btn-primary" type="submit" disabled={busy}>Einladung senden</button>
		</div>
	</form>
</dialog>

<dialog bind:this={rolesDialog} class="dialog card" aria-labelledby="rl-h">
	<form onsubmit={submitRoles}>
		<h2 id="rl-h">Rollen von {rolesUser?.display_name}</h2>
		<fieldset>
			<legend class="sr-only">Rollen</legend>
			{#each data.roles as r (r.key)}
				<label class="check">
					<input type="checkbox" value={r.key} bind:group={rolesSel} />
					<span
						><strong>{r.name}</strong>{#if r.description}<small>{r.description}</small>{/if}</span
					>
				</label>
			{/each}
		</fieldset>
		<div class="buttons">
			<button class="btn btn-secondary" type="button" onclick={() => rolesDialog.close()}
				>Abbrechen</button
			>
			<button class="btn btn-primary" type="submit">Rollen speichern</button>
		</div>
	</form>
</dialog>

<dialog bind:this={roleDialog} class="dialog card wide" aria-labelledby="re-h">
	<form onsubmit={saveRole}>
		<h2 id="re-h">{editing.key ? `Rolle ${editing.name} bearbeiten` : 'Neue Rolle'}</h2>
		{#if editing.is_system}
			<p class="sub">
				Fest eingerichtete Rolle: Name und Beschreibung bleiben, die Berechtigungen kannst du
				anpassen.
			</p>
		{/if}
		<label class="field">
			<span>Name</span>
			<input
				class="input"
				required
				maxlength="200"
				bind:value={editing.name}
				disabled={editing.is_system}
			/>
		</label>
		<label class="field">
			<span>Beschreibung <small>(optional)</small></span>
			<input
				class="input"
				maxlength="500"
				bind:value={editing.description}
				disabled={editing.is_system}
			/>
		</label>
		<fieldset class="perms">
			<legend>Berechtigungen</legend>
			{#each groups as [label, perms] (label)}
				<p class="group-label">{label}</p>
				{#each perms as p (p.id)}
					<label class="check" class:locked={!mine.has(p.id)}>
						<input
							type="checkbox"
							value={p.id}
							bind:group={editing.permissions}
							disabled={!mine.has(p.id)}
						/>
						<span
							><strong>{p.label}</strong><small
								>{mine.has(p.id) ? p.id : `${p.id} · hast du selbst nicht`}</small
							></span
						>
					</label>
				{/each}
			{/each}
		</fieldset>
		{#if roleError}<p class="notice error" role="alert">{roleError}</p>{/if}
		<div class="buttons">
			{#if editing.key && !editing.is_system}
				<button
					class="btn btn-danger left"
					type="button"
					onclick={deleteRole}
					disabled={editing.members > 0}
					title={editing.members > 0 ? 'Die Rolle ist noch Personen zugewiesen' : undefined}
					>Rolle löschen</button
				>
			{/if}
			<button class="btn btn-secondary" type="button" onclick={() => roleDialog.close()}
				>Abbrechen</button
			>
			<button class="btn btn-primary" type="submit"
				>{editing.key ? 'Speichern' : 'Rolle anlegen'}</button
			>
		</div>
	</form>
</dialog>

<dialog bind:this={confirmDialog} class="dialog card" aria-labelledby="cf-h">
	{#if confirmState}
		<h2 id="cf-h">{confirmState.title}</h2>
		<p class="sub">{confirmState.text}</p>
		<div class="buttons">
			<button class="btn btn-secondary" type="button" onclick={() => confirmDialog.close()}
				>Abbrechen</button
			>
			<button class="btn btn-danger" type="button" onclick={confirmed}>{confirmState.action}</button
			>
		</div>
	{/if}
</dialog>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 24px;
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
	.titles p,
	.sub {
		margin: 0;
		color: var(--muted);
		font-size: 15px;
	}
	h2 {
		margin: 0;
		font-size: 22px;
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
		font-size: 12px;
		font-weight: 600;
		padding: 1px 8px;
		border-radius: 999px;
		background: var(--info-bg);
		color: var(--info-ink);
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
	}
	.search {
		flex: 1 1 280px;
		max-width: 420px;
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
	.search:focus-within {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
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
		white-space: nowrap;
	}
	td {
		padding: 14px 16px;
		font-size: 15px;
		border-bottom: 1px solid var(--line-3);
		vertical-align: middle;
	}
	tbody tr:last-child td {
		border-bottom: 0;
	}
	tr.off .names strong,
	tr.off .avatar {
		color: var(--muted);
	}
	.who {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.avatar {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background: var(--primary-tint);
		color: var(--primary-strong);
		font-size: 13px;
		font-weight: 700;
	}
	.names {
		display: flex;
		flex-direction: column;
	}
	.names small {
		font-size: 13px;
		color: var(--muted);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.none {
		color: var(--muted);
		font-size: 14px;
	}
	.login {
		font-size: 14px;
		font-weight: 600;
	}
	.login.strong {
		color: var(--primary-strong);
	}
	.login {
		white-space: nowrap;
	}
	.login.warn {
		color: var(--warn-ink);
	}
	.login.muted {
		color: var(--muted);
		font-weight: 400;
	}
	.when {
		color: var(--muted);
		font-size: 14px;
		white-space: nowrap;
	}
	.actions {
		width: 44px;
	}
	.menu-wrap {
		position: relative;
	}
	.icon-btn {
		display: inline-grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--ink-2);
		cursor: pointer;
	}
	.icon-btn:hover {
		background: var(--hover);
	}
	.menu {
		position: fixed;
		z-index: 10;
		min-width: 220px;
		padding: 6px;
		display: flex;
		flex-direction: column;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.12);
	}
	.menu button {
		min-height: 40px;
		padding: 0 12px;
		border: 0;
		border-radius: 8px;
		background: none;
		color: var(--ink);
		font: inherit;
		font-size: 15px;
		text-align: left;
		cursor: pointer;
	}
	.menu button:hover,
	.menu button:focus-visible {
		background: var(--hover);
	}
	.menu .danger {
		color: var(--danger-ink);
	}
	.empty {
		text-align: center;
		color: var(--muted);
		padding: 32px;
	}
	.roles {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.matrix th:not(:first-child),
	.matrix td.mark {
		text-align: center;
	}
	.matrix th small {
		display: block;
		font-weight: 400;
		color: var(--muted-2);
	}
	.group td {
		background: var(--surface-2);
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--muted-2);
		padding: 10px 16px;
	}
	.perm {
		display: flex;
		flex-direction: column;
	}
	.perm code {
		font-size: 12px;
		color: var(--muted);
	}
	.yes {
		display: inline-flex;
		color: var(--primary-strong);
	}
	.no {
		color: var(--muted-2);
	}
	.dialog {
		margin: auto;
		width: min(480px, calc(100vw - 32px));
		padding: 28px;
		border-radius: 18px;
		color: var(--ink);
		box-sizing: border-box;
	}
	.dialog::backdrop {
		background: rgb(0 0 0 / 0.35);
	}
	.dialog form,
	.dialog {
		gap: 16px;
	}
	.dialog form {
		display: flex;
		flex-direction: column;
	}
	.dialog[open]:not(:has(form)) {
		display: flex;
		flex-direction: column;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	legend {
		font-size: 14px;
		font-weight: 600;
		color: var(--ink-2);
		margin-bottom: 6px;
	}
	.check {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		min-height: 44px;
		padding: 8px 10px;
		border: 1px solid var(--line);
		border-radius: 10px;
		cursor: pointer;
	}
	.check input {
		width: 18px;
		height: 18px;
		margin-top: 2px;
		accent-color: var(--primary);
	}
	.check span {
		display: flex;
		flex-direction: column;
	}
	.check small {
		color: var(--muted);
		font-size: 13px;
	}
	.roles-head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-end;
		gap: 12px;
	}
	.rolehead {
		display: inline-flex;
		align-items: center;
		min-height: 36px;
		font: inherit;
		font-weight: 600;
		color: var(--ink);
	}
	.rolehead.edit {
		padding: 0 8px;
		border: 0;
		border-radius: 8px;
		background: none;
		cursor: pointer;
		color: var(--link);
		text-decoration: underline;
		text-decoration-color: color-mix(in oklab, currentColor 30%, transparent);
		text-underline-offset: 3px;
	}
	.rolehead.edit:hover {
		background: var(--hover);
	}
	.dialog.wide {
		width: min(640px, calc(100vw - 32px));
		max-height: calc(100vh - 48px);
	}
	.perms {
		gap: 6px;
	}
	.group-label {
		margin: 8px 0 2px;
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--muted-2);
	}
	.check.locked {
		opacity: 0.6;
		cursor: default;
	}
	.left {
		margin-right: auto;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
		flex-wrap: wrap;
	}
</style>
