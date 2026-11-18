import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type AdminUser = {
	id: string;
	email: string;
	display_name: string;
	status: 'invited' | 'active' | 'deactivated';
	roles: string[];
	mfa_enabled: boolean;
	has_password: boolean;
	last_login_at: string | null;
	created_at: string;
	invite_expires_at: string | null;
};

export type AdminRole = {
	key: string;
	name: string;
	description: string | null;
	is_system: boolean;
	permissions: string[];
	members: number;
};

export type Permission = { id: string; label: string; group: string; group_label: string };

export const load: PageServerLoad = async ({ fetch }) => {
	const [users, roles, me] = await Promise.all([
		fetch(`${API_URL}/api/v1/admin/users`),
		fetch(`${API_URL}/api/v1/admin/roles`),
		fetch(`${API_URL}/api/v1/me`)
	]);
	if (users.status === 403 || roles.status === 403) error(403, 'Keine Berechtigung');
	if (!users.ok || !roles.ok || !me.ok) error(502, 'Benutzer konnten nicht geladen werden');
	const r = (await roles.json()) as { roles: AdminRole[]; permissions: Permission[] };
	return {
		users: (await users.json()) as AdminUser[],
		roles: r.roles,
		permissions: r.permissions,
		// What the signed-in admin holds: only these can be granted (the API checks too).
		myPermissions: ((await me.json()) as { permissions: string[] }).permissions
	};
};
