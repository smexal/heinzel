// Date and time display. TODO(preferences): use the user's resolved settings from /me
// instead of the fixed de-CH / Europe/Zurich defaults.

const LOCALE = 'de-CH';
const TZ = 'Europe/Zurich';

const time = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' });
const dayMonth = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'long' });
const full = new Intl.DateTimeFormat(LOCALE, {
	timeZone: TZ,
	day: 'numeric',
	month: 'long',
	year: 'numeric'
});
const dayKey = new Intl.DateTimeFormat('en-CA', { timeZone: TZ });

/** "heute, 08:41" · "gestern" · "13. November" · "2. Oktober 2025" */
export function relativeDay(iso: string | null, never = 'noch nie'): string {
	if (!iso) return never;
	const d = new Date(iso);
	const now = new Date();
	const key = dayKey.format(d);
	if (key === dayKey.format(now)) return `heute, ${time.format(d)}`;
	if (key === dayKey.format(new Date(now.getTime() - 86_400_000))) return 'gestern';
	return d.getFullYear() === now.getFullYear() ? dayMonth.format(d) : full.format(d);
}

export function initials(name: string): string {
	const parts = name.split(/\s+/).filter(Boolean);
	return (parts.length ? parts.slice(0, 2).map((p) => p[0]) : ['?']).join('').toUpperCase();
}
