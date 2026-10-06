import { AgentEvent } from './models';

/**
 * POST que responde em SSE (data: {...}\n\n). EventSource só faz GET, por isso usamos fetch.
 * Devolve cada evento do agente à medida que chega.
 */
export async function* streamAgent(url: string, body: unknown, email: string | null): AsyncGenerator<AgentEvent> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(email ? { 'X-User-Email': email } : {}) },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok || !response.body) {
    const detail = await response.json().then((j) => j.detail).catch(() => null);
    throw new Error(detail ?? `Erro ${response.status}`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const line = buffer.slice(0, end).trim();
      buffer = buffer.slice(end + 2);
      if (line.startsWith('data: ')) yield JSON.parse(line.slice(6)) as AgentEvent;
    }
  }
}
