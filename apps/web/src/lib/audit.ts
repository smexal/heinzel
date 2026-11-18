// Readable labels for audit actions. Unknown actions (e.g. from modules) show their key.

export const ACTION_LABELS: Record<string, string> = {
	'auth.login': 'Anmeldung',
	'auth.password_ok': 'Passwort korrekt, 2FA folgt',
	'auth.login_failed': 'Anmeldung fehlgeschlagen',
	'auth.totp_failed': '2FA-Code falsch',
	'auth.mfa_enabled': '2FA eingerichtet',
	'auth.logout': 'Abmeldung',
	'auth.password_reset_requested': 'Neues Passwort angefordert',
	'auth.password_reset': 'Passwort über Link neu gesetzt',
	'auth.password_changed': 'Passwort geändert',
	'auth.password_change_failed': 'Passwortänderung abgelehnt',
	'user.created': 'Benutzer angelegt',
	'user.invited': 'Benutzer eingeladen',
	'user.invite_resent': 'Einladung erneut gesendet',
	'user.activated': 'Einladung angenommen',
	'user.activated_by_admin': 'Benutzer wieder aktiviert',
	'user.deactivated': 'Benutzer deaktiviert',
	'user.mfa_reset': '2FA zurückgesetzt',
	'user.roles_changed': 'Rollen geändert',
	'user.preferences_changed': 'Persönliche Einstellungen geändert',
	'auth.step_up': 'Änderung mit 2FA bestätigt',
	'auth.step_up_failed': 'Bestätigung fehlgeschlagen',
	'role.created': 'Rolle angelegt',
	'role.updated': 'Rolle geändert',
	'role.deleted': 'Rolle gelöscht',
	'settings.changed': 'Einstellungen geändert',
	'settings.logo_changed': 'Logo geändert',
	'settings.logo_removed': 'Logo entfernt',
	'settings.test_mail': 'Test-E-Mail gesendet',
	'settings.reset_from_seed': 'Einstellungen aus Vorlage zurückgesetzt',
	'tenant.registered': 'Mandant eingerichtet',
	'audit.exported': 'Audit-Log exportiert'
};

export const FAILURE_REASONS: Record<string, string> = {
	invalid: 'falsches Passwort oder unbekannte E-Mail',
	locked: 'Konto vorübergehend gesperrt',
	inactive: 'Konto nicht aktiv'
};

export const CHANNELS: Record<string, string> = {
	web: 'Web',
	api: 'API',
	mcp: 'MCP',
	cli: 'Konsole',
	system: 'System'
};

export const actionLabel = (action: string) => ACTION_LABELS[action] ?? action;

export const PERIODS: Record<string, { label: string; hours: number | null }> = {
	'24h': { label: 'Letzte 24 Stunden', hours: 24 },
	'7d': { label: 'Letzte 7 Tage', hours: 24 * 7 },
	'30d': { label: 'Letzte 30 Tage', hours: 24 * 30 },
	all: { label: 'Gesamter Zeitraum', hours: null }
};

/** Filters live in the URL, so a filtered view can be reloaded and shared. */
export function apiQuery(params: URLSearchParams): URLSearchParams {
	const q = new URLSearchParams();
	for (const key of ['q', 'actor', 'channel', 'area']) {
		const v = params.get(key);
		if (v) q.set(key, v);
	}
	const hours = PERIODS[params.get('zeitraum') ?? '7d']?.hours;
	if (hours) q.set('since', new Date(Date.now() - hours * 3_600_000).toISOString());
	return q;
}
