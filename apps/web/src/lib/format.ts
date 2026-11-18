// Display formatting with the user's resolved settings (shell.user.localization):
// language, time zone, date and time format, first day of week, number format.
// The API delivers ISO 8601 (UTC) and raw numbers; only this module turns them into text.

export type Localization = {
	language: string;
	timezone: string;
	date_format: string; // dd.MM.yyyy | yyyy-MM-dd | dd/MM/yyyy | MM/dd/yyyy
	time_format: string; // 24h | 12h
	first_day_of_week: string;
	number_format: string; // 1'234.50 | 1.234,50 | 1,234.50 | 1 234,50
};

export const FALLBACK: Localization = {
	language: 'de-CH',
	timezone: 'Europe/Zurich',
	date_format: 'dd.MM.yyyy',
	time_format: '24h',
	first_day_of_week: 'monday',
	number_format: "1'234.50"
};

export type Formatter = ReturnType<typeof formatter>;

export function formatter(loc: Partial<Localization> | null | undefined) {
	const l = { ...FALLBACK, ...(loc ?? {}) };
	const tz = l.timezone;
	const parts = new Intl.DateTimeFormat('en-GB', {
		timeZone: tz,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	});
	const timeFmt = new Intl.DateTimeFormat(l.time_format === '12h' ? 'en-US' : 'de-CH', {
		timeZone: tz,
		hour: l.time_format === '12h' ? 'numeric' : '2-digit',
		minute: '2-digit',
		hour12: l.time_format === '12h'
	});
	const dayMonth = new Intl.DateTimeFormat(l.language, {
		timeZone: tz,
		day: 'numeric',
		month: 'long'
	});
	const weekday = new Intl.DateTimeFormat(l.language, { timeZone: tz, weekday: 'long' });

	function ymd(d: Date) {
		const p = Object.fromEntries(parts.formatToParts(d).map((x) => [x.type, x.value]));
		return { y: p.year, m: p.month, d: p.day };
	}

	function date(value: string | Date): string {
		const { y, m, d } = ymd(new Date(value));
		switch (l.date_format) {
			case 'yyyy-MM-dd':
				return `${y}-${m}-${d}`;
			case 'dd/MM/yyyy':
				return `${d}/${m}/${y}`;
			case 'MM/dd/yyyy':
				return `${m}/${d}/${y}`;
			default:
				return `${d}.${m}.${y}`;
		}
	}

	const time = (value: string | Date) => timeFmt.format(new Date(value));

	function number(n: number, decimals = 2): string {
		const [int, frac] = Math.abs(n).toFixed(decimals).split('.');
		const [group, dec] = { "1'234.50": ["'", '.'], '1.234,50': ['.', ','], '1,234.50': [',', '.'] }[
			l.number_format
		] ?? [' ', ','];
		const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, group);
		return `${n < 0 ? '-' : ''}${grouped}${frac ? dec + frac : ''}`;
	}

	/** "heute, 08:41" · "gestern, 17:02" · "13. November" · "02.10.2025" */
	function relative(value: string | null, never = 'noch nie'): string {
		if (!value) return never;
		const d = new Date(value);
		const now = new Date();
		const key = (x: Date) => Object.values(ymd(x)).join('-');
		if (key(d) === key(now)) return `heute, ${time(d)}`;
		if (key(d) === key(new Date(now.getTime() - 86_400_000))) return `gestern, ${time(d)}`;
		return ymd(d).y === ymd(now).y ? dayMonth.format(d) : date(d);
	}

	return {
		loc: l,
		date,
		time,
		dateTime: (v: string | Date) => `${date(v)} ${time(v)}`,
		weekday: (v: string | Date) => weekday.format(new Date(v)),
		number,
		relative,
		/** Same calendar day in the user's time zone. */
		dayKey: (v: string | Date) => Object.values(ymd(new Date(v))).join('-')
	};
}

export function initials(name: string): string {
	const parts = name.split(/\s+/).filter(Boolean);
	return (parts.length ? parts.slice(0, 2).map((p) => p[0]) : ['?']).join('').toUpperCase();
}
