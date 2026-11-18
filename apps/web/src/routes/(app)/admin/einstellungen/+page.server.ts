import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type Settings = {
	version: number;
	updated_at: string;
	assets_base: string;
	sections: {
		general: {
			display_name: string;
			short_name: string;
			legal: { imprint_url: string | null; privacy_url: string | null };
		};
		branding: {
			logo_light: string;
			logo_dark: string | null;
			logo_mark: string | null;
			colors: { primary: string; accent: string };
			theme_default: 'light' | 'dark' | 'system';
			powered_by: boolean;
		};
		localization: {
			languages: string[];
			defaults: Record<string, string>;
			locked: string[];
		};
		navigation: {
			hide_empty_areas: boolean;
			areas: { key: string; label: Record<string, string>; order: number }[];
		};
		identity: {
			local: {
				enabled: boolean;
				mfa_required: 'all' | 'admins' | 'optional';
				password_min_length: number;
				self_service_reset: boolean;
				lockout: { attempts: number; minutes: number };
				session_idle_hours: number;
			};
			providers: unknown[];
		};
		email: {
			from_name: string;
			from_address: string;
			reply_to: string | null;
			smtp: {
				host: string;
				port: number;
				security: 'none' | 'starttls' | 'tls';
				username: string | null;
				password_set: boolean;
			};
		};
	};
	options: {
		languages: Record<string, string>;
		timezones: string[];
		currencies: string[];
		date_format: string[];
		time_format: string[];
		first_day_of_week: string[];
		number_format: string[];
	};
};

export const load: PageServerLoad = async ({ fetch }) => {
	const res = await fetch(`${API_URL}/api/v1/admin/settings`);
	if (res.status === 403) error(403, 'Keine Berechtigung');
	if (!res.ok) error(502, 'Einstellungen konnten nicht geladen werden');
	return { settings: (await res.json()) as Settings };
};
