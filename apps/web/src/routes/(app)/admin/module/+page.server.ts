import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type ModuleInfo = {
	key: string;
	name: string;
	description: string;
	version: string;
	icon: string | null;
	status: 'active' | 'inactive' | 'available';
	area: string | null;
	default_area: string | null;
	children: { path: string; label: string; visible: boolean }[];
	permissions: { id: string; label: string; roles: string[] }[];
	settings_schema: { properties?: Record<string, unknown> } | null;
	settings: Record<string, unknown>;
	mcp: { name: string; kind: 'read' | 'write' | 'prompt'; title: string; enabled: boolean }[];
};

export type ModulesPage = {
	version: number;
	areas: { key: string; label: string }[];
	modules: ModuleInfo[];
};

export const load: PageServerLoad = async ({ fetch }) => {
	const res = await fetch(`${API_URL}/api/v1/admin/modules`);
	if (res.status === 403) error(403, 'Keine Berechtigung');
	if (!res.ok) error(502, 'Module konnten nicht geladen werden');
	return { modules: (await res.json()) as ModulesPage };
};
