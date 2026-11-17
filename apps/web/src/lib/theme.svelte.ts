// Light/dark theme: stored per browser, default from the tenant branding.

const KEY = 'heinzel.theme';

export const theme = $state({ dark: false });

function apply(isDark: boolean) {
	theme.dark = isDark;
	document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
}

export function initTheme(tenantDefault: string) {
	let stored: string | null = null;
	try {
		stored = localStorage.getItem(KEY);
	} catch {
		/* storage may be unavailable */
	}
	const pref = stored ?? tenantDefault;
	apply(
		pref === 'dark' ||
			(pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
	);
}

export function toggleTheme() {
	apply(!theme.dark);
	try {
		localStorage.setItem(KEY, theme.dark ? 'dark' : 'light');
	} catch {
		/* ignore */
	}
}
