import type { HandleFetch } from '@sveltejs/kit/hooks';
import { API_URL } from '$app/env/private';

// Server-side calls to the Heinzel API carry the browser's session cookie, the host name
// the browser used (the API resolves the tenant from it) and the client address.
export const handleFetch: HandleFetch = async ({ event, request, fetch }) => {
	if (request.url.startsWith(`${API_URL}/`)) {
		const cookie = event.request.headers.get('cookie');
		if (cookie) request.headers.set('cookie', cookie);
		request.headers.set('x-forwarded-host', event.url.host);
		request.headers.set('x-forwarded-for', event.getClientAddress());
	}
	return fetch(request);
};
