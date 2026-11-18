import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type TokenInfo = {
	purpose: 'invite' | 'password_reset';
	email: string;
	display_name: string;
	password_min_length: number;
};

// Invitation and password-reset links: /konto/<token>
export const load: PageServerLoad = async ({ fetch, params }) => {
	const res = await fetch(`${API_URL}/api/v1/auth/token/${encodeURIComponent(params.token)}`);
	return { info: res.ok ? ((await res.json()) as TokenInfo) : null };
};
