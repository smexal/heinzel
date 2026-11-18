import type { Localization } from '#lib/format.ts';

// Types for GET /api/v1/shell (see apps/api/src/heinzel_api/routes/shell.py)

export type NavItem = {
	key: string;
	label: string;
	path: string;
	icon: string | null;
	children: NavItem[];
};

export type NavSection = {
	key: string;
	label: string | null;
	items: NavItem[];
};

export type QuickAction = {
	key: string;
	label: string;
	path: string;
	module: string;
};

export type ShellUser = {
	display_name: string;
	email: string;
	initials: string;
	localization: Localization;
};

export type Shell = {
	tenant: string;
	/** null when nobody is signed in: then navigation and quick_actions are empty */
	user: ShellUser | null;
	branding: {
		display_name: string;
		short_name: string;
		logo_light: string;
		logo_dark: string | null;
		logo_mark: string | null;
		primary: string;
		accent: string;
		theme_default: 'light' | 'dark' | 'system';
		powered_by: boolean;
	};
	navigation: NavSection[];
	quick_actions: QuickAction[];
};
