<script lang="ts">
	import { untrack } from 'svelte';
	import { invalidateAll } from '$app/navigation';
	import { ApiError, post, put } from '#lib/api.ts';
	import { formatter, initials, type Localization } from '#lib/format.ts';
	import { setTheme, theme, type ThemePref } from '#lib/theme.svelte.ts';
	import type { Preferences } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	type Tab = 'region' | 'appearance' | 'security';
	let tab = $state<Tab>('region');

	const ROLE_NAMES: Record<string, string> = { admin: 'Administration', staff: 'Mitarbeitende' };

	// --- Sprache & Region -----------------------------------------------------------------
	const KEYS = [
		'language',
		'timezone',
		'date_format',
		'time_format',
		'first_day_of_week',
		'number_format'
	] as const;
	type Key = (typeof KEYS)[number];

	const META: Record<Key, { label: string; hint: string }> = {
		language: { label: 'Sprache', hint: 'Sprache der Oberfläche und der E-Mails' },
		timezone: { label: 'Zeitzone', hint: 'Für Termine, Fristen und Zeitstempel' },
		date_format: { label: 'Datumsformat', hint: 'Wie Daten angezeigt werden' },
		time_format: { label: 'Zeitformat', hint: '24 Stunden oder 12 Stunden mit AM/PM' },
		first_day_of_week: { label: 'Erster Wochentag', hint: 'Für Kalender und Wochenansichten' },
		number_format: { label: 'Zahlenformat', hint: 'Tausender- und Dezimaltrennzeichen' }
	};

	const WEEKDAYS: Record<string, string> = {
		monday: 'Montag',
		sunday: 'Sonntag',
		saturday: 'Samstag'
	};

	// '' = Standard (follow the tenant default)
	// Initial values only; after saving the form is reset from the reloaded data.
	let form = $state<Record<Key, string>>(untrack(() => blank(data.prefs)));
	let saving = $state(false);
	let saved = $state<'ok' | 'error' | null>(null);

	function blank(p: Preferences): Record<Key, string> {
		return Object.fromEntries(KEYS.map((k) => [k, p.values[k] ?? ''])) as Record<Key, string>;
	}

	const locked = $derived(new Set(data.prefs.locked));
	const preview = $derived(
		formatter(
			Object.fromEntries(
				KEYS.map((k) => [k, form[k] || data.prefs.defaults[k]])
			) as unknown as Localization
		)
	);
	const sample = new Date();
	const dirty = $derived(KEYS.some((k) => (data.prefs.values[k] ?? '') !== form[k]));

	function optionLabel(key: Key, value: string): string {
		switch (key) {
			case 'language':
				return data.prefs.language_labels[value] ?? value;
			case 'date_format':
				return formatter({ date_format: value }).date(sample);
			case 'time_format':
				return value === '12h' ? '12 Std. · 2:24 PM' : '24 Std. · 14:24';
			case 'first_day_of_week':
				return WEEKDAYS[value] ?? value;
			default:
				return value;
		}
	}

	async function savePrefs(values: Record<Key, string>) {
		saving = true;
		saved = null;
		try {
			const body = Object.fromEntries(
				KEYS.filter((k) => !locked.has(k)).map((k) => [k, values[k] || null])
			);
			await put('/me/preferences', { localization: body });
			await invalidateAll();
			form = blank(data.prefs);
			saved = 'ok';
		} catch {
			saved = 'error';
		} finally {
			saving = false;
		}
	}

	function submitPrefs(e: SubmitEvent) {
		e.preventDefault();
		savePrefs(form);
	}

	function resetPrefs() {
		savePrefs(Object.fromEntries(KEYS.map((k) => [k, ''])) as Record<Key, string>);
	}

	// --- Darstellung ----------------------------------------------------------------------
	const THEMES: { value: ThemePref; label: string; hint: string }[] = [
		{ value: 'system', label: 'Wie das Gerät', hint: 'Folgt der Einstellung des Betriebssystems' },
		{ value: 'light', label: 'Hell', hint: 'Immer hell' },
		{ value: 'dark', label: 'Dunkel', hint: 'Immer dunkel' }
	];

	// --- Sicherheit -----------------------------------------------------------------------
	let pw = $state({ current: '', next: '', repeat: '' });
	let pwMsg = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);
	let pwBusy = $state(false);
	const MIN = 12;

	async function changePassword(e: SubmitEvent) {
		e.preventDefault();
		pwMsg = null;
		if (pw.next.length < MIN) {
			pwMsg = {
				tone: 'error',
				text: `Das neue Passwort muss mindestens ${MIN} Zeichen lang sein.`
			};
			return;
		}
		if (pw.next !== pw.repeat) {
			pwMsg = { tone: 'error', text: 'Die beiden neuen Passwörter stimmen nicht überein.' };
			return;
		}
		pwBusy = true;
		try {
			await post('/me/password', { current_password: pw.current, new_password: pw.next });
			pw = { current: '', next: '', repeat: '' };
			pwMsg = {
				tone: 'ok',
				text: 'Passwort geändert. Auf anderen Geräten bist du jetzt abgemeldet.'
			};
		} catch (err) {
			const d = err instanceof ApiError ? err.detail : '';
			pwMsg = {
				tone: 'error',
				text:
					d === 'wrong_password'
						? 'Das aktuelle Passwort stimmt nicht.'
						: d === 'password_policy'
							? `Das neue Passwort muss mindestens ${MIN} Zeichen lang sein.`
							: 'Das hat nicht geklappt. Bitte versuche es erneut.'
			};
		} finally {
			pwBusy = false;
		}
	}
</script>

<svelte:head><title>Mein Profil · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="head">
		<span class="avatar" aria-hidden="true">{initials(data.me.display_name)}</span>
		<div>
			<h1>Mein Profil</h1>
			<p>
				{data.me.display_name} · {data.me.email} · {data.me.roles
					.map((r) => ROLE_NAMES[r] ?? r)
					.join(', ')}
			</p>
		</div>
	</header>

	<nav class="tabs" aria-label="Profilbereiche">
		{#each [['region', 'Sprache & Region'], ['appearance', 'Darstellung'], ['security', 'Sicherheit']] as [key, label] (key)}
			<button
				type="button"
				class="tab"
				class:on={tab === key}
				aria-current={tab === key ? 'page' : undefined}
				onclick={() => (tab = key as Tab)}>{label}</button
			>
		{/each}
	</nav>

	{#if tab === 'region'}
		<form class="layout" onsubmit={submitPrefs}>
			<section class="card settings" aria-labelledby="lr-h">
				<div class="sec-head">
					<h2 id="lr-h">Sprache &amp; Region</h2>
					<p>Ohne eigene Wahl gilt der Standard von {data.shell.branding.display_name}.</p>
				</div>
				{#each KEYS as key (key)}
					<div class="srow">
						<div class="sl">
							<label class="lab" for="p-{key}">{META[key].label}</label>
							<span class="hint">
								{locked.has(key) ? 'Von der Administration für alle festgelegt' : META[key].hint}
							</span>
						</div>
						<div class="sc">
							{#if key === 'time_format' && !locked.has(key)}
								<div class="pills" role="radiogroup" aria-label={META[key].label} id="p-{key}">
									{#each ['', ...data.prefs.options[key]] as v (v)}
										<button
											type="button"
											role="radio"
											aria-checked={form[key] === v}
											class="pill"
											class:on={form[key] === v}
											onclick={() => (form[key] = v)}
										>
											{v
												? optionLabel(key, v)
												: `Standard (${data.prefs.defaults[key] === '12h' ? '12' : '24'} Std.)`}
										</button>
									{/each}
								</div>
							{:else}
								<select
									id="p-{key}"
									class="input"
									bind:value={form[key]}
									disabled={locked.has(key)}
								>
									{#if locked.has(key)}
										<option value="">{optionLabel(key, data.prefs.defaults[key])}</option>
									{:else}
										<option value="">Standard: {optionLabel(key, data.prefs.defaults[key])}</option>
										{#each data.prefs.options[key] as v (v)}
											<option value={v}>{optionLabel(key, v)}</option>
										{/each}
									{/if}
								</select>
							{/if}
						</div>
					</div>
				{/each}
			</section>

			<aside class="side">
				<section class="card preview" aria-labelledby="pv-h">
					<h2 id="pv-h">Vorschau</h2>
					<dl>
						<dt>Datum und Zeit</dt>
						<dd class="strong">
							{preview.weekday(sample)}, {preview.date(sample)} · {preview.time(sample)}
						</dd>
						<dt>Zahl</dt>
						<dd>CHF {preview.number(1234.5)}</dd>
						<dt>Woche beginnt</dt>
						<dd>{WEEKDAYS[preview.loc.first_day_of_week]}</dd>
						<dt>Zeitzone</dt>
						<dd>{preview.loc.timezone}</dd>
					</dl>
				</section>
				<p class="note">
					Einige Einstellungen kann die Administration für alle festlegen. Sie sind dann hier nicht
					änderbar.
				</p>
			</aside>

			<div class="actions">
				{#if saved === 'ok'}<p class="notice ok" role="status">Gespeichert.</p>{/if}
				{#if saved === 'error'}
					<p class="notice error" role="alert">Speichern hat nicht geklappt.</p>
				{/if}
				<button class="btn btn-secondary" type="button" onclick={resetPrefs} disabled={saving}
					>Alles auf Standard zurücksetzen</button
				>
				<button class="btn btn-primary" type="submit" disabled={saving || !dirty}>Speichern</button>
			</div>
		</form>
	{:else if tab === 'appearance'}
		<section class="card settings narrow" aria-labelledby="ap-h">
			<div class="sec-head">
				<h2 id="ap-h">Darstellung</h2>
				<p>Gilt für diesen Browser. Wird sofort übernommen.</p>
			</div>
			<fieldset>
				<legend class="sr-only">Farbschema</legend>
				{#each THEMES as t (t.value)}
					<label class="choice">
						<input
							type="radio"
							name="theme"
							value={t.value}
							checked={theme.pref === t.value}
							onchange={() => setTheme(t.value)}
						/>
						<span><strong>{t.label}</strong><small>{t.hint}</small></span>
					</label>
				{/each}
			</fieldset>
		</section>
	{:else}
		<div class="layout">
			<section class="card settings" aria-labelledby="pw-h">
				<form onsubmit={changePassword}>
					<div class="sec-head">
						<h2 id="pw-h">Passwort ändern</h2>
						<p>Nach der Änderung bist du auf allen anderen Geräten abgemeldet.</p>
					</div>
					<input type="email" autocomplete="username" value={data.me.email} hidden readonly />
					<label class="field">
						<span>Aktuelles Passwort</span>
						<input
							class="input"
							type="password"
							autocomplete="current-password"
							required
							bind:value={pw.current}
						/>
					</label>
					<label class="field">
						<span>Neues Passwort</span>
						<input
							class="input"
							type="password"
							autocomplete="new-password"
							minlength={MIN}
							required
							bind:value={pw.next}
						/>
						<small>Mindestens {MIN} Zeichen. Ein Satz aus mehreren Wörtern ist gut.</small>
					</label>
					<label class="field">
						<span>Neues Passwort wiederholen</span>
						<input
							class="input"
							type="password"
							autocomplete="new-password"
							required
							bind:value={pw.repeat}
						/>
					</label>
					{#if pwMsg}
						<p class="notice {pwMsg.tone}" role={pwMsg.tone === 'error' ? 'alert' : 'status'}>
							{pwMsg.text}
						</p>
					{/if}
					<div class="actions">
						<button class="btn btn-primary" type="submit" disabled={pwBusy}>Passwort ändern</button>
					</div>
				</form>
			</section>
			<aside class="side">
				<section class="card preview" aria-labelledby="mfa-h">
					<h2 id="mfa-h">Zwei-Faktor-Anmeldung</h2>
					{#if data.me.mfa_enabled}
						<p><span class="chip ok">Aktiv</span></p>
						<p class="note">
							Bei jeder Anmeldung fragen wir nach dem Code aus deiner Authenticator-App. Neues
							Telefon oder App verloren? Die Administration setzt 2FA zurück, danach richtest du es
							bei der nächsten Anmeldung neu ein.
						</p>
					{:else}
						<p><span class="chip warn">Nicht eingerichtet</span></p>
						<p class="note">Du richtest 2FA bei der nächsten Anmeldung ein.</p>
					{/if}
				</section>
			</aside>
		</div>
	{/if}
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 22px;
		max-width: 1080px;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 18px;
	}
	.avatar {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 64px;
		height: 64px;
		border-radius: 50%;
		background: var(--primary-tint);
		color: var(--primary-strong);
		font-size: 22px;
		font-weight: 700;
	}
	h1 {
		margin: 0;
		font-size: 30px;
		letter-spacing: -0.02em;
	}
	.head p {
		margin: 4px 0 0;
		color: var(--muted);
	}
	.tabs {
		display: flex;
		flex-wrap: wrap;
		gap: 28px;
		border-bottom: 1px solid var(--line);
	}
	.tab {
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
	.layout {
		display: flex;
		flex-wrap: wrap;
		gap: 20px;
		align-items: flex-start;
	}
	.settings {
		flex: 2 1 520px;
		min-width: 0;
		padding: 8px 24px 20px;
	}
	.settings form {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.narrow {
		max-width: 640px;
	}
	.sec-head {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 16px 0 8px;
	}
	h2 {
		margin: 0;
		font-size: 18px;
	}
	.sec-head p,
	.note {
		margin: 0;
		font-size: 14px;
		color: var(--muted);
		line-height: 1.5;
	}
	.srow {
		display: flex;
		flex-wrap: wrap;
		gap: 12px 24px;
		align-items: center;
		padding: 14px 0;
		border-top: 1px solid var(--line-3);
	}
	.sl {
		flex: 1 1 220px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.lab {
		font-weight: 600;
	}
	.hint {
		font-size: 13px;
		color: var(--muted);
	}
	.sc {
		flex: 1 1 260px;
	}
	.sc select {
		width: 100%;
	}
	.sc select:disabled {
		background: var(--surface-2);
		color: var(--muted);
	}
	.pills {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.pill {
		min-height: 40px;
		padding: 0 12px;
		border: 1px solid var(--input);
		border-radius: 999px;
		background: var(--surface);
		color: var(--ink-2);
		font: inherit;
		font-size: 14px;
		cursor: pointer;
	}
	.pill.on {
		background: var(--primary-tint);
		border-color: var(--primary);
		color: var(--primary-strong);
		font-weight: 600;
	}
	.side {
		flex: 1 1 280px;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.preview {
		padding: 20px 22px;
		display: flex;
		flex-direction: column;
		gap: 12px;
		background: var(--primary-tint);
		border-color: transparent;
	}
	.preview h2 {
		font-size: 14px;
		color: var(--primary-strong);
	}
	.preview p {
		margin: 0;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 8px 16px;
		margin: 0;
		font-size: 14px;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	.strong {
		font-weight: 600;
	}
	.actions {
		flex: 1 1 100%;
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		justify-content: flex-end;
		align-items: center;
	}
	.actions .notice {
		margin-right: auto;
	}
	fieldset {
		margin: 0 0 8px;
		padding: 0;
		border: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.choice {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		min-height: 44px;
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: 10px;
		cursor: pointer;
	}
	.choice input {
		width: 18px;
		height: 18px;
		margin-top: 2px;
		accent-color: var(--primary);
	}
	.choice span {
		display: flex;
		flex-direction: column;
	}
	.choice small {
		color: var(--muted);
		font-size: 13px;
	}
</style>
