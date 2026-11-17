import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { Shell } from '#lib/shell.ts';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ fetch, url }) => {
	// The API resolves the tenant from the host name the browser used.
	const res = await fetch(`${API_URL}/api/v1/shell`, {
		headers: { 'x-forwarded-host': url.host }
	}).catch(() => null);
	if (!res) error(503, 'Heinzel API nicht erreichbar');
	if (res.status === 404) error(404, 'Unbekannter Mandant');
	if (!res.ok) error(502, 'Fehler beim Laden der Oberfläche');
	return { shell: (await res.json()) as Shell };
};
