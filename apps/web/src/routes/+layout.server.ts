import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { Shell } from '#lib/shell.ts';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ fetch }) => {
	// hooks.server.ts adds the session cookie and the host the browser used (tenant).
	const res = await fetch(`${API_URL}/api/v1/shell`).catch(() => null);
	if (!res) error(503, 'Heinzel API nicht erreichbar');
	if (res.status === 404) error(404, 'Unbekannter Mandant');
	if (res.status === 503) error(503, 'Mandant nicht eingerichtet (heinzel seed-tenants)');
	if (!res.ok) error(502, 'Fehler beim Laden der Oberfläche');
	return { shell: (await res.json()) as Shell };
};
