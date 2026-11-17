import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	API_URL: {
		description: 'Where the SvelteKit server reaches the Heinzel API',
		schema: (value) => value || 'http://localhost:8000'
	}
});
