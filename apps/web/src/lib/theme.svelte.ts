// Light/dark theme: stored per browser, default from the tenant branding.

const KEY = 'heinzel.theme';

export type ThemePref = 'light' | 'dark' | 'system';

export const theme = $state({ dark: false, pref: 'system' as ThemePref });

let media: MediaQueryList | null = null;

function apply() {
	const dark = theme.pref === 'dark' || (theme.pref === 'system' && (media?.matches ?? false));
	theme.dark = dark;
	document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

export function initTheme(tenantDefault: string) {
	media = window.matchMedia('(prefers-color-scheme: dark)');
	media.addEventListener('change', apply);
	let stored: string | null = null;
	try {
		stored = localStorage.getItem(KEY);
	} catch {
		/* storage may be unavailable */
	}
	const pref = stored ?? tenantDefault;
	theme.pref = pref === 'dark' || pref === 'light' ? pref : 'system';
	apply();
}

export function setTheme(pref: ThemePref) {
	theme.pref = pref;
	apply();
	try {
		localStorage.setItem(KEY, pref);
	} catch {
		/* ignore */
	}
}

/** Sidebar switch: flips between light and dark explicitly. */
export function toggleTheme() {
	setTheme(theme.dark ? 'light' : 'dark');
}
