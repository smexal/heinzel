<script lang="ts">
	import { untrack } from 'svelte';
	import { invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post, put, send } from '#lib/api.ts';
	import { formatter, type Localization } from '#lib/format.ts';
	import { StepUpCancelled, withStepUp } from '#lib/stepup.svelte.ts';
	import type { Settings } from './+page.server.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	type Tab = 'general' | 'branding' | 'localization' | 'navigation' | 'identity' | 'email';
	const TABS: [Tab, string][] = [
		['general', 'Allgemein'],
		['branding', 'Branding'],
		['localization', 'Sprache & Region'],
		['navigation', 'Navigation'],
		['identity', 'Anmeldung'],
		['email', 'E-Mail']
	];
	let tab = $state<Tab>(
		untrack(() => {
			const t = page.url.searchParams.get('tab');
			return (TABS.find(([k]) => k === t)?.[0] ?? 'general') as Tab;
		})
	);
	$effect(() => {
		const t = TABS.find(([k]) => k === page.url.searchParams.get('tab'))?.[0];
		if (t) untrack(() => (tab = t));
	});

	const s = $derived(data.settings);
	const opt = $derived(data.settings.options);

	// Editable copies of every section, re-taken from the server after each save.
	const clone = <T,>(v: T): T => structuredClone($state.snapshot(v) as T);
	let general = $state(untrack(() => clone(data.settings.sections.general)));
	let branding = $state(untrack(() => clone(data.settings.sections.branding)));
	let loc = $state(untrack(() => clone(data.settings.sections.localization)));
	let ident = $state(untrack(() => clone(data.settings.sections.identity)));
	let email = $state(untrack(() => clone(data.settings.sections.email)));
	let nav = $state(untrack(() => navDraft(data.settings.sections.navigation)));

	type NavDraft = { hide_empty_areas: boolean; areas: { key: string | null; label: string }[] };
	function navDraft(n: Settings['sections']['navigation']): NavDraft {
		return {
			hide_empty_areas: n.hide_empty_areas,
			areas: [...n.areas]
				.sort((a, b) => a.order - b.order)
				.map((a) => ({ key: a.key, label: a.label.de ?? Object.values(a.label)[0] ?? a.key }))
		};
	}
	let smtpPassword = $state('');

	function reset(sections: Settings['sections']) {
		general = clone(sections.general);
		branding = clone(sections.branding);
		loc = clone(sections.localization);
		ident = clone(sections.identity);
		email = clone(sections.email);
		nav = navDraft(sections.navigation);
		smtpPassword = '';
	}

	let busy = $state(false);
	let message = $state<{ tone: 'ok' | 'error' | 'info'; text: string } | null>(null);

	const ERRORS: Record<string, string> = {
		version_conflict:
			'Jemand hat die Einstellungen inzwischen geändert. Lade die Seite neu und versuche es nochmals.',
		no_login_left: 'Die Anmeldung mit Passwort ist der einzige Anmeldeweg und bleibt aktiv.',
		default_language_not_offered: 'Die Standardsprache muss eine der verfügbaren Sprachen sein.',
		invalid_values: 'Bitte prüfe die Eingaben.',
		logo_too_large: 'Das Logo ist grösser als 512 KB.',
		logo_type: 'Bitte ein SVG-, PNG- oder WebP-Bild wählen.',
		main_logo_required: 'Das Hauptlogo ist nötig. Ersetze es stattdessen.'
	};

	function errorText(d: string): string | undefined {
		if (d.startsWith('area_in_use:'))
			return 'Ein Bereich wird noch von einem Modul verwendet. Verschiebe das Modul zuerst unter Module.';
		return ERRORS[d];
	}

	// --- navigation -----------------------------------------------------------------------
	function moveArea(i: number, delta: number) {
		const j = i + delta;
		if (j < 0 || j >= nav.areas.length) return;
		const list = [...nav.areas];
		[list[i], list[j]] = [list[j], list[i]];
		nav.areas = list;
	}
	function addArea() {
		nav.areas = [...nav.areas, { key: null, label: '' }];
	}
	function removeArea(i: number) {
		nav.areas = nav.areas.filter((_, k) => k !== i);
	}

	async function run(action: () => Promise<unknown>, ok: string) {
		busy = true;
		message = null;
		try {
			await action();
			await invalidateAll();
			reset(data.settings.sections);
			message = { tone: 'ok', text: ok };
		} catch (e) {
			if (e instanceof StepUpCancelled) return;
			const d = e instanceof ApiError ? e.detail : '';
			message = {
				tone: 'error',
				text:
					errorText(d) ??
					(e instanceof ApiError && e.status === 422
						? 'Bitte prüfe die Eingaben.'
						: 'Speichern hat nicht geklappt. Bitte versuche es erneut.')
			};
		} finally {
			busy = false;
		}
	}

	const save = (section: Tab, values: unknown) =>
		run(() => put(`/admin/settings/${section}`, { version: s.version, values }), 'Gespeichert.');

	const saveSecure = (section: Tab, values: unknown) =>
		run(
			() =>
				withStepUp(() => put(`/admin/settings/secure/${section}`, { version: s.version, values })),
			'Gespeichert.'
		);

	function submit(section: Tab) {
		return (e: SubmitEvent) => {
			e.preventDefault();
			if (section === 'general') save('general', general);
			if (section === 'branding')
				save('branding', {
					colors: branding.colors,
					theme_default: branding.theme_default,
					powered_by: branding.powered_by
				});
			if (section === 'localization') save('localization', loc);
			if (section === 'navigation') save('navigation', nav);
			if (section === 'identity') saveSecure('identity', ident);
			if (section === 'email') {
				const { password_set: _, ...smtp } = email.smtp;
				saveSecure('email', {
					...email,
					reply_to: email.reply_to || null,
					smtp: { ...smtp, username: smtp.username || null, password: smtpPassword || null }
				});
			}
		};
	}

	// --- logos ----------------------------------------------------------------------------
	const SLOTS = [
		{ slot: 'light', key: 'logo_light', label: 'Logo (hell)', hint: 'Auf hellem Hintergrund' },
		{ slot: 'dark', key: 'logo_dark', label: 'Logo (dunkel)', hint: 'Für den Dunkelmodus' },
		{ slot: 'mark', key: 'logo_mark', label: 'Symbol', hint: 'Browser-Tab und kleine Flächen' }
	] as const;

	const assetUrl = (name: string | null) =>
		name ? `${s.assets_base}${name.replace(/^assets\//, '')}` : null;

	function uploadLogo(slot: string, input: HTMLInputElement) {
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		run(() => send('PUT', `/admin/settings/branding/logos/${slot}`, file), 'Logo gespeichert.');
	}

	const removeLogo = (slot: string) =>
		run(() => send('DELETE', `/admin/settings/branding/logos/${slot}`), 'Logo entfernt.');

	// --- localization ---------------------------------------------------------------------
	const LOC_ROWS: { key: string; label: string; hint: string }[] = [
		{ key: 'language', label: 'Standardsprache', hint: 'Für neue Benutzer, Login und E-Mails' },
		{ key: 'timezone', label: 'Zeitzone', hint: 'Für Termine, Fristen und Zeitstempel' },
		{ key: 'date_format', label: 'Datumsformat', hint: '' },
		{ key: 'time_format', label: 'Zeitformat', hint: '24 Stunden oder 12 Stunden mit AM/PM' },
		{ key: 'first_day_of_week', label: 'Erster Wochentag', hint: '' },
		{ key: 'number_format', label: 'Zahlenformat', hint: '' },
		{ key: 'currency', label: 'Währung', hint: 'Für Beträge in Modulen' }
	];
	const WEEKDAYS: Record<string, string> = {
		monday: 'Montag',
		sunday: 'Sonntag',
		saturday: 'Samstag'
	};
	const sample = new Date();

	function locOptions(key: string): string[] {
		switch (key) {
			case 'language':
				return loc.languages;
			case 'timezone':
				return opt.timezones;
			case 'currency':
				return opt.currencies;
			default:
				return (opt as unknown as Record<string, string[]>)[key] ?? [];
		}
	}

	function locLabel(key: string, v: string): string {
		if (key === 'language') return opt.languages[v] ?? v;
		if (key === 'date_format') return formatter({ date_format: v }).date(sample);
		if (key === 'time_format') return v === '12h' ? '12 Std. · 2:24 PM' : '24 Std. · 14:24';
		if (key === 'first_day_of_week') return WEEKDAYS[v] ?? v;
		return v;
	}

	function toggleLock(key: string, userMayChange: boolean) {
		loc.locked = userMayChange ? loc.locked.filter((k) => k !== key) : [...loc.locked, key];
	}

	const preview = $derived(formatter(loc.defaults as unknown as Localization));

	// --- email ----------------------------------------------------------------------------
	let testBusy = $state(false);
	async function testMail() {
		testBusy = true;
		message = null;
		try {
			const r = await post<{ sent: boolean; to: string }>('/admin/settings/email/test');
			message = r.sent
				? { tone: 'ok', text: `Test-E-Mail an ${r.to} gesendet. Prüfe dein Postfach.` }
				: {
						tone: 'error',
						text: 'Die Test-E-Mail konnte nicht gesendet werden. Prüfe Server, Port und Zugangsdaten.'
					};
		} catch {
			message = { tone: 'error', text: 'Die Test-E-Mail konnte nicht gesendet werden.' };
		} finally {
			testBusy = false;
		}
	}
</script>

<svelte:head><title>Einstellungen · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header class="titles">
		<span class="eyebrow">Administration</span>
		<h1>Einstellungen</h1>
		<p>
			Mandant {s.sections.general.display_name} · gilt für alle Benutzer ohne eigene Einstellung.
		</p>
	</header>

	<nav class="tabs" aria-label="Einstellungsbereiche">
		{#each TABS as [key, label] (key)}
			<button
				type="button"
				class="tab"
				class:on={tab === key}
				aria-current={tab === key ? 'page' : undefined}
				onclick={() => {
					tab = key;
					message = null;
				}}>{label}</button
			>
		{/each}
	</nav>

	{#if message}
		<p class="notice {message.tone}" role={message.tone === 'error' ? 'alert' : 'status'}>
			{message.text}
		</p>
	{/if}

	{#if tab === 'general'}
		<form class="card settings" onsubmit={submit('general')}>
			<div class="sec-head">
				<h2>Allgemein</h2>
				<p>Name der Organisation, wie er im Portal und in E-Mails erscheint.</p>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="g-name">Name</label><span class="hint">Voller Name</span>
				</div>
				<div class="sc">
					<input
						id="g-name"
						class="input"
						required
						maxlength="200"
						bind:value={general.display_name}
					/>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="g-short">Kurzname</label><span class="hint"
						>Für knappe Stellen, z. B. die Authenticator-App</span
					>
				</div>
				<div class="sc">
					<input
						id="g-short"
						class="input"
						required
						maxlength="60"
						bind:value={general.short_name}
					/>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="g-imprint">Impressum</label><span class="hint"
						>Link, erscheint im Fuss der Anmeldeseite</span
					>
				</div>
				<div class="sc">
					<input
						id="g-imprint"
						class="input"
						type="url"
						placeholder="https://"
						value={general.legal.imprint_url ?? ''}
						oninput={(e) => (general.legal.imprint_url = e.currentTarget.value || null)}
					/>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="g-privacy">Datenschutzerklärung</label><span class="hint"
						>Link</span
					>
				</div>
				<div class="sc">
					<input
						id="g-privacy"
						class="input"
						type="url"
						placeholder="https://"
						value={general.legal.privacy_url ?? ''}
						oninput={(e) => (general.legal.privacy_url = e.currentTarget.value || null)}
					/>
				</div>
			</div>
			<div class="actions">
				<button class="btn btn-primary" type="submit" disabled={busy}>Speichern</button>
			</div>
		</form>
	{:else if tab === 'branding'}
		<div class="layout">
			<form class="card settings" onsubmit={submit('branding')}>
				<div class="sec-head">
					<h2>Logos</h2>
					<p>SVG, PNG oder WebP, höchstens 512 KB. Ein Wechsel gilt sofort für alle.</p>
				</div>
				{#each SLOTS as l (l.slot)}
					{@const url = assetUrl(branding[l.key])}
					<div class="srow">
						<div class="sl">
							<span class="lab">{l.label}</span><span class="hint">{l.hint}</span>
						</div>
						<div class="sc logo-row">
							<span class="logo-box" class:dark={l.slot === 'dark'}>
								{#if url}<img src={url} alt={l.label} />{:else}<span class="none">Keins</span>{/if}
							</span>
							<label class="btn btn-secondary file">
								{url ? 'Ersetzen' : 'Hochladen'}
								<input
									type="file"
									accept="image/svg+xml,image/png,image/webp"
									onchange={(e) => uploadLogo(l.slot, e.currentTarget)}
									disabled={busy}
								/>
							</label>
							{#if url && l.slot !== 'light'}
								<button
									class="btn btn-link"
									type="button"
									onclick={() => removeLogo(l.slot)}
									disabled={busy}>Entfernen</button
								>
							{/if}
						</div>
					</div>
				{/each}

				<div class="sec-head">
					<h2>Farben &amp; Darstellung</h2>
					<p>Die Hauptfarbe prägt Schaltflächen und Navigation, die Akzentfarbe Markierungen.</p>
				</div>
				{#each [['primary', 'Hauptfarbe'], ['accent', 'Akzentfarbe']] as [key, label] (key)}
					<div class="srow">
						<div class="sl"><label class="lab" for="c-{key}">{label}</label></div>
						<div class="sc color">
							<input
								type="color"
								aria-label="{label} wählen"
								bind:value={branding.colors[key as 'primary' | 'accent']}
							/>
							<input
								id="c-{key}"
								class="input mono"
								pattern={'#[0-9a-fA-F]{6}'}
								required
								bind:value={branding.colors[key as 'primary' | 'accent']}
							/>
						</div>
					</div>
				{/each}
				<div class="srow">
					<div class="sl">
						<label class="lab" for="b-theme">Farbschema</label><span class="hint"
							>Bis jemand selbst wählt</span
						>
					</div>
					<div class="sc">
						<select id="b-theme" class="input" bind:value={branding.theme_default}>
							<option value="system">Wie das Gerät</option>
							<option value="light">Hell</option>
							<option value="dark">Dunkel</option>
						</select>
					</div>
				</div>
				<div class="srow">
					<div class="sl">
						<span class="lab">«powered by Heinzel»</span><span class="hint"
							>Kleiner Hinweis unten in der Navigation</span
						>
					</div>
					<div class="sc">
						<label class="switch"
							><input
								type="checkbox"
								role="switch"
								bind:checked={branding.powered_by}
							/>Anzeigen</label
						>
					</div>
				</div>
				<div class="actions">
					<button class="btn btn-primary" type="submit" disabled={busy}>Speichern</button>
				</div>
			</form>
			<aside class="side">
				<section class="card preview" aria-labelledby="bp-h">
					<h2 id="bp-h">Vorschau</h2>
					<div class="swatch" style="--p:{branding.colors.primary};--a:{branding.colors.accent}">
						<span class="nav-on">Übersicht</span>
						<span class="btn-demo">Speichern</span>
					</div>
					<p class="note">Farben gelten nach dem Speichern. Text auf der Hauptfarbe ist weiss.</p>
				</section>
			</aside>
		</div>
	{:else if tab === 'localization'}
		<form class="layout" onsubmit={submit('localization')}>
			<section class="card settings">
				<div class="sec-head">
					<h2>Standardwerte</h2>
					<p>Pro Einstellung legst du fest, ob Benutzer sie in ihrem Profil ändern dürfen.</p>
				</div>
				<div class="srow">
					<div class="sl">
						<span class="lab">Verfügbare Sprachen</span><span class="hint"
							>Was Benutzer auswählen können</span
						>
					</div>
					<div class="sc stack">
						{#each Object.entries(opt.languages) as [code, label] (code)}
							<label class="inline-check"
								><input type="checkbox" value={code} bind:group={loc.languages} />{label}</label
							>
						{/each}
					</div>
				</div>
				{#each LOC_ROWS as row (row.key)}
					<div class="srow">
						<div class="sl">
							<label class="lab" for="l-{row.key}">{row.label}</label>
							{#if row.hint}<span class="hint">{row.hint}</span>{/if}
						</div>
						<div class="sc stack">
							<select id="l-{row.key}" class="input" bind:value={loc.defaults[row.key]}>
								{#each locOptions(row.key) as v (v)}
									<option value={v}>{locLabel(row.key, v)}</option>
								{/each}
							</select>
							<label class="switch">
								<input
									type="checkbox"
									role="switch"
									checked={!loc.locked.includes(row.key)}
									onchange={(e) => toggleLock(row.key, e.currentTarget.checked)}
								/>Benutzer dürfen ändern
							</label>
						</div>
					</div>
				{/each}
			</section>
			<aside class="side">
				<section class="card preview" aria-labelledby="lp-h">
					<h2 id="lp-h">Vorschau</h2>
					<dl>
						<dt>Datum und Zeit</dt>
						<dd class="strong">
							{preview.weekday(sample)}, {preview.date(sample)} · {preview.time(sample)}
						</dd>
						<dt>Zahl</dt>
						<dd>{loc.defaults.currency} {preview.number(1234.5)}</dd>
						<dt>Woche beginnt</dt>
						<dd>{WEEKDAYS[loc.defaults.first_day_of_week]}</dd>
					</dl>
				</section>
			</aside>
			<div class="actions">
				<button class="btn btn-primary" type="submit" disabled={busy}>Speichern</button>
			</div>
		</form>
	{:else if tab === 'navigation'}
		<form class="layout" onsubmit={submit('navigation')}>
			<section class="card settings">
				<div class="sec-head">
					<h2>Bereiche</h2>
					<p>
						Bereiche gruppieren Module in der Seitenleiste. Welches Modul wo steht, legst du unter
						<a href="/admin/module">Module</a> fest.
					</p>
				</div>
				<ol class="areas">
					{#each nav.areas as a, i (i)}
						<li class="area">
							<span class="pos">{i + 1}</span>
							<label class="sr-only" for="area-{i}">Name des Bereichs {i + 1}</label>
							<input id="area-{i}" class="input" required maxlength="60" bind:value={a.label} />
							<button
								class="icon-btn"
								type="button"
								aria-label="{a.label} nach oben"
								disabled={i === 0}
								onclick={() => moveArea(i, -1)}>↑</button
							>
							<button
								class="icon-btn"
								type="button"
								aria-label="{a.label} nach unten"
								disabled={i === nav.areas.length - 1}
								onclick={() => moveArea(i, 1)}>↓</button
							>
							<button class="btn btn-link" type="button" onclick={() => removeArea(i)}
								>Entfernen</button
							>
						</li>
					{/each}
				</ol>
				<div>
					<button class="btn btn-secondary" type="button" onclick={addArea}
						>Bereich hinzufügen</button
					>
				</div>
				<div class="srow">
					<div class="sl">
						<span class="lab">Leere Bereiche ausblenden</span><span class="hint"
							>Bereiche ohne aktives Modul erscheinen nicht in der Seitenleiste</span
						>
					</div>
					<div class="sc">
						<label class="switch"
							><input
								type="checkbox"
								role="switch"
								bind:checked={nav.hide_empty_areas}
							/>Ausblenden</label
						>
					</div>
				</div>
			</section>
			<aside class="side">
				<section class="card preview" aria-label="Vorschau Seitenleiste">
					<h2>Vorschau Seitenleiste</h2>
					<div class="sidebar">
						{#each data.shell.navigation as sec (sec.key)}
							{#if sec.key === 'top'}
								{#each sec.items as item (item.key)}<span class="si">{item.label}</span>{/each}
							{/if}
						{/each}
						{#each nav.areas as a, i (i)}
							{@const items = data.shell.navigation.find((x) => x.key === a.key)?.items ?? []}
							{#if items.length || !nav.hide_empty_areas}
								<span class="sh">{a.label || 'Neuer Bereich'}</span>
								{#each items as item (item.key)}<span class="si">{item.label}</span>{:else}<span
										class="si empty">leer</span
									>{/each}
							{/if}
						{/each}
					</div>
				</section>
			</aside>
			<div class="actions">
				<button class="btn btn-primary" type="submit" disabled={busy}>Speichern</button>
			</div>
		</form>
	{:else if tab === 'identity'}
		<form class="card settings narrow" onsubmit={submit('identity')}>
			<div class="sec-head">
				<h2>Anmeldung mit Passwort</h2>
				<p>Änderungen hier bestätigst du mit 2FA. Sie gelten ab der nächsten Anmeldung.</p>
			</div>
			<div class="srow">
				<div class="sl">
					<span class="lab">Zwei-Faktor-Anmeldung</span><span class="hint"
						>Wer bei der Anmeldung einen Code eingeben muss</span
					>
				</div>
				<div class="sc stack" role="radiogroup" aria-label="Zwei-Faktor-Anmeldung">
					{#each [['all', 'Für alle (empfohlen)'], ['admins', 'Nur für Personen mit Rolle Administration'], ['optional', 'Freiwillig']] as [v, label] (v)}
						<label class="inline-check"
							><input type="radio" value={v} bind:group={ident.local.mfa_required} />{label}</label
						>
					{/each}
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="i-min">Mindestlänge Passwort</label><span class="hint"
						>Zeichen; lange Sätze sind sicherer als Sonderzeichen</span
					>
				</div>
				<div class="sc">
					<input
						id="i-min"
						class="input short"
						type="number"
						min="10"
						max="128"
						bind:value={ident.local.password_min_length}
					/>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<span class="lab">Passwort vergessen</span><span class="hint"
						>Benutzer setzen ihr Passwort per E-Mail-Link selbst zurück</span
					>
				</div>
				<div class="sc">
					<label class="switch"
						><input
							type="checkbox"
							role="switch"
							bind:checked={ident.local.self_service_reset}
						/>Erlaubt</label
					>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<span class="lab">Sperre nach Fehlversuchen</span><span class="hint"
						>Falsche Passwörter oder Codes in Folge</span
					>
				</div>
				<div class="sc inline">
					<label class="inline-field"
						><input
							class="input short"
							type="number"
							min="3"
							max="20"
							aria-label="Fehlversuche"
							bind:value={ident.local.lockout.attempts}
						/>Versuche</label
					>
					<label class="inline-field"
						><input
							class="input short"
							type="number"
							min="1"
							max="1440"
							aria-label="Sperrdauer in Minuten"
							bind:value={ident.local.lockout.minutes}
						/>Minuten gesperrt</label
					>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="i-idle">Automatisch abmelden</label><span class="hint"
						>Nach so vielen Stunden ohne Aktivität</span
					>
				</div>
				<div class="sc">
					<input
						id="i-idle"
						class="input short"
						type="number"
						min="1"
						max="720"
						bind:value={ident.local.session_idle_hours}
					/>
				</div>
			</div>
			<div class="actions">
				<button class="btn btn-primary" type="submit" disabled={busy}>Speichern</button>
			</div>
		</form>
	{:else}
		<form class="card settings narrow" onsubmit={submit('email')}>
			<div class="sec-head">
				<h2>E-Mail-Versand</h2>
				<p>
					Für Einladungen, Passwort-Links und Benachrichtigungen. Änderungen bestätigst du mit 2FA.
				</p>
			</div>
			<div class="srow">
				<div class="sl"><label class="lab" for="e-from-name">Absendername</label></div>
				<div class="sc">
					<input id="e-from-name" class="input" required bind:value={email.from_name} />
				</div>
			</div>
			<div class="srow">
				<div class="sl"><label class="lab" for="e-from">Absenderadresse</label></div>
				<div class="sc">
					<input id="e-from" class="input" type="email" required bind:value={email.from_address} />
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="e-reply">Antwort an</label><span class="hint">Optional</span>
				</div>
				<div class="sc">
					<input
						id="e-reply"
						class="input"
						type="email"
						value={email.reply_to ?? ''}
						oninput={(e) => (email.reply_to = e.currentTarget.value || null)}
					/>
				</div>
			</div>
			<div class="sec-head">
				<h2>SMTP-Server</h2>
			</div>
			<div class="srow">
				<div class="sl"><label class="lab" for="e-host">Server</label></div>
				<div class="sc inline">
					<input id="e-host" class="input" required bind:value={email.smtp.host} />
					<input
						class="input short"
						type="number"
						min="1"
						max="65535"
						aria-label="Port"
						bind:value={email.smtp.port}
					/>
				</div>
			</div>
			<div class="srow">
				<div class="sl"><label class="lab" for="e-sec">Verschlüsselung</label></div>
				<div class="sc">
					<select id="e-sec" class="input" bind:value={email.smtp.security}>
						<option value="starttls">STARTTLS (meist Port 587)</option>
						<option value="tls">TLS (meist Port 465)</option>
						<option value="none">Keine (nur für Tests)</option>
					</select>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="e-user">Benutzername</label><span class="hint"
						>Leer ohne Anmeldung</span
					>
				</div>
				<div class="sc">
					<input
						id="e-user"
						class="input"
						autocomplete="off"
						value={email.smtp.username ?? ''}
						oninput={(e) => (email.smtp.username = e.currentTarget.value || null)}
					/>
				</div>
			</div>
			<div class="srow">
				<div class="sl">
					<label class="lab" for="e-pw">Passwort</label><span class="hint"
						>Wird verschlüsselt gespeichert und nie angezeigt</span
					>
				</div>
				<div class="sc">
					<input
						id="e-pw"
						class="input"
						type="password"
						autocomplete="new-password"
						placeholder={email.smtp.password_set ? 'Gespeichert, leer lassen für unverändert' : ''}
						bind:value={smtpPassword}
					/>
				</div>
			</div>
			<div class="actions">
				<button
					class="btn btn-secondary"
					type="button"
					onclick={testMail}
					disabled={testBusy || busy}>Test-E-Mail an mich senden</button
				>
				<button class="btn btn-primary" type="submit" disabled={busy}>Speichern</button>
			</div>
		</form>
	{/if}
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 22px;
		max-width: 1080px;
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
	.sec-head p,
	.note {
		margin: 0;
		color: var(--muted);
		font-size: 14px;
		line-height: 1.5;
	}
	.titles p {
		font-size: 16px;
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
		display: flex;
		flex-direction: column;
	}
	.narrow {
		max-width: 760px;
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
		flex: 1 1 300px;
		min-width: 0;
	}
	.sc > .input,
	.sc select {
		width: 100%;
	}
	.stack {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.inline {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
	}
	.inline > .input:not(.short) {
		flex: 1 1 200px;
	}
	.input.short {
		width: 100px;
	}
	.inline-field,
	.inline-check,
	.switch {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 36px;
		font-size: 15px;
	}
	.inline-check input,
	.switch input {
		width: 18px;
		height: 18px;
		accent-color: var(--primary);
	}
	.switch {
		font-size: 14px;
		color: var(--ink-2);
	}
	.mono {
		font-family: ui-monospace, monospace;
		text-transform: uppercase;
		max-width: 160px;
	}
	.color {
		display: flex;
		gap: 10px;
		align-items: center;
	}
	.color input[type='color'] {
		width: 44px;
		height: 44px;
		padding: 2px;
		border: 1px solid var(--input);
		border-radius: 10px;
		background: var(--surface);
		cursor: pointer;
	}
	.logo-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
	}
	.logo-box {
		display: grid;
		place-items: center;
		width: 180px;
		height: 64px;
		padding: 8px;
		box-sizing: border-box;
		border: 1px dashed var(--input);
		border-radius: 10px;
		background: #fff;
	}
	.logo-box.dark {
		background: #161a19;
	}
	.logo-box img {
		max-width: 100%;
		max-height: 100%;
	}
	.none {
		color: #8a8f88;
		font-size: 13px;
	}
	.file {
		position: relative;
		overflow: hidden;
	}
	.file input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.file:focus-within {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
	}
	.side {
		flex: 1 1 280px;
		min-width: 0;
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
	.swatch {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px;
		border-radius: 10px;
		background: var(--surface);
	}
	.nav-on {
		padding: 10px 12px;
		border-radius: 10px;
		background: color-mix(in oklab, var(--p) 13%, white);
		color: color-mix(in oklab, var(--p) 78%, black);
		font-weight: 600;
		box-shadow: inset 3px 0 0 var(--a);
	}
	.btn-demo {
		align-self: flex-start;
		padding: 10px 18px;
		border-radius: 10px;
		background: var(--p);
		color: #fff;
		font-weight: 600;
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
	.areas {
		list-style: none;
		margin: 0 0 12px;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.area {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.area .input {
		flex: 1;
	}
	.pos {
		width: 24px;
		text-align: center;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.icon-btn {
		display: inline-grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border: 1px solid var(--input);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink-2);
		font-size: 16px;
		cursor: pointer;
	}
	.icon-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.sidebar {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 10px;
		border-radius: 10px;
		background: var(--surface);
		font-size: 14px;
	}
	.si {
		padding: 6px 10px;
		color: var(--ink-2);
	}
	.si.empty {
		color: var(--muted-2);
		font-style: italic;
	}
	.sh {
		padding: 12px 10px 2px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--muted-2);
	}
	.actions {
		flex: 1 1 100%;
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		justify-content: flex-end;
		padding-top: 12px;
	}
</style>
