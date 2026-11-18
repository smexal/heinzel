// Simple, safe Markdown for notes (task notes, inbox texts). The input is HTML-escaped first,
// so nothing the user types can become markup except the constructs below:
//   **fett**  *kursiv*  ~~durchgestrichen~~  `code`  [Text](https://…)  bare https://… links
//   # / ## / ### Titel   - Liste   1. Liste   - [ ] / - [x] Punkt   > Zitat
// Line breaks inside a paragraph are kept. Links only to http(s), mailto and paths in the portal.

const ESC: Record<string, string> = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;'
};
const escape = (s: string) => s.replace(/[&<>"']/g, (c) => ESC[c]);

function safeHref(url: string): string | null {
	// url is already escaped; &amp; stays valid inside an attribute
	if (/^(https?:\/\/|mailto:)/i.test(url)) return url;
	if (url.startsWith('/') && !url.startsWith('//')) return url;
	return null;
}

function inline(text: string): string {
	// Code spans first, kept out of all other rules.
	const codes: string[] = [];
	let s = text.replace(/`([^`\n]+)`/g, (_, c) => {
		codes.push(`<code>${c}</code>`);
		return `\u0000${codes.length - 1}\u0000`;
	});
	const links: string[] = [];
	const keep = (html: string) => {
		links.push(html);
		return `\u0001${links.length - 1}\u0001`;
	};
	s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
		const href = safeHref(url);
		if (!href) return m;
		const external = !href.startsWith('/');
		return keep(
			`<a href="${href}"${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${label}</a>`
		);
	});
	s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?'"])/g, (_, pre, url) =>
		keep(`${pre}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`)
	);
	s = s
		.replace(/\*\*(?=\S)([^*\n]*?\S)\*\*/g, '<strong>$1</strong>')
		.replace(/__(?=\S)([^_\n]*?\S)__/g, '<strong>$1</strong>')
		.replace(/(^|[^*\w])\*(?=\S)([^*\n]*?\S)\*(?!\w)/g, '$1<em>$2</em>')
		.replace(/(^|[^_\w])_(?=\S)([^_\n]*?\S)_(?!\w)/g, '$1<em>$2</em>')
		.replace(/~~(?=\S)([^~\n]*?\S)~~/g, '<del>$1</del>');
	s = s.replace(/\u0001(\d+)\u0001/g, (_, i) => links[+i]);
	return s.replace(/\u0000(\d+)\u0000/g, (_, i) => codes[+i]);
}

type Block =
	| { kind: 'p' | 'quote'; lines: string[] }
	| { kind: 'ul' | 'ol'; items: { text: string; check: boolean | null }[] }
	| { kind: 'h'; level: number; text: string };

export function renderMarkdown(source: string | null | undefined): string {
	const lines = escape((source ?? '').replace(/\r\n?/g, '\n')).split('\n');
	const blocks: Block[] = [];
	let cur: Block | null = null;
	const close = () => {
		if (cur) blocks.push(cur);
		cur = null;
	};
	for (const raw of lines) {
		const line = raw.trimEnd();
		let m: RegExpMatchArray | null;
		if (!line.trim()) {
			close();
		} else if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
			close();
			blocks.push({ kind: 'h', level: m[1].length, text: m[2] });
		} else if ((m = line.match(/^\s*[-*+]\s+(?:\[([ xX])\]\s+)?(.*)$/))) {
			if (cur?.kind !== 'ul') {
				close();
				cur = { kind: 'ul', items: [] };
			}
			cur.items.push({ text: m[2], check: m[1] === undefined ? null : m[1].toLowerCase() === 'x' });
		} else if ((m = line.match(/^\s*\d{1,3}[.)]\s+(.*)$/))) {
			if (cur?.kind !== 'ol') {
				close();
				cur = { kind: 'ol', items: [] };
			}
			cur.items.push({ text: m[1], check: null });
		} else if ((m = line.match(/^&gt;\s?(.*)$/))) {
			if (cur?.kind !== 'quote') {
				close();
				cur = { kind: 'quote', lines: [] };
			}
			cur.lines.push(m[1]);
		} else if (cur && (cur.kind === 'ul' || cur.kind === 'ol') && /^\s{2,}\S/.test(raw)) {
			const last = cur.items[cur.items.length - 1];
			last.text += `\n${line.trim()}`;
		} else {
			if (cur?.kind !== 'p') {
				close();
				cur = { kind: 'p', lines: [] };
			}
			cur.lines.push(line);
		}
	}
	close();

	const br = (s: string) => inline(s).replace(/\n/g, '<br>');
	return blocks
		.map((b) => {
			switch (b.kind) {
				case 'h':
					return `<h${b.level + 3}>${inline(b.text)}</h${b.level + 3}>`;
				case 'p':
					return `<p>${br(b.lines.join('\n'))}</p>`;
				case 'quote':
					return `<blockquote>${br(b.lines.join('\n'))}</blockquote>`;
				default: {
					const items = b.items
						.map((i) =>
							i.check === null
								? `<li>${br(i.text)}</li>`
								: `<li class="task${i.check ? ' done' : ''}"><span class="box" aria-hidden="true"></span>${br(i.text)}</li>`
						)
						.join('');
					return `<${b.kind}>${items}</${b.kind}>`;
				}
			}
		})
		.join('');
}
