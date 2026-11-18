import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type Me = {
	id: string;
	email: string;
	display_name: string;
	roles: string[];
	permissions: string[];
	mfa_enabled: boolean;
};

export type Preferences = {
	values: Record<string, string>;
	defaults: Record<string, string>;
	effective: Record<string, string>;
	locked: string[];
	options: Record<string, string[]>;
	language_labels: Record<string, string>;
};

export const load: PageServerLoad = async ({ fetch }) => {
	const [me, prefs] = await Promise.all([
		fetch(`${API_URL}/api/v1/me`),
		fetch(`${API_URL}/api/v1/me/preferences`)
	]);
	if (!me.ok || !prefs.ok) error(502, 'Profil konnte nicht geladen werden');
	return { me: (await me.json()) as Me, prefs: (await prefs.json()) as Preferences };
};
