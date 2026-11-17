// Browser-side calls to the Heinzel API. Same origin: /api is proxied to the API
// (Vite in development, the reverse proxy in production).

export class ApiError extends Error {
	constructor(
		public status: number,
		public detail: string
	) {
		super(detail);
	}
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
	const res = await fetch(`/api/v1${path}`, {
		method: 'POST',
		headers: body === undefined ? {} : { 'content-type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
		credentials: 'same-origin'
	});
	if (!res.ok) {
		let detail = `http_${res.status}`;
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') detail = data.detail;
		} catch {
			/* no JSON body */
		}
		throw new ApiError(res.status, detail);
	}
	return (res.status === 204 ? undefined : await res.json()) as T;
}

/** Only allow redirects to paths inside the app (no //host, no schemes). */
export function safeNext(value: string | null): string {
	return value && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\')
		? value
		: '/';
}
