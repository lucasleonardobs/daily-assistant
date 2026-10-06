export const CATEGORY: Record<string, string> = {
  ACCESS: 'Acesso', ENVIRONMENT: 'Ambiente', DEPENDENCY_PERSON: 'Dependência de pessoa',
  DEPENDENCY_TEAM: 'Dependência de time', REQUIREMENT_UNCLEAR: 'Requisito pouco claro',
  TECHNICAL: 'Técnico', EXTERNAL: 'Externo', OTHER: 'Outro',
};

export const SEVERITY: Record<string, { label: string; cls: string }> = {
  HIGH: { label: 'Alta', cls: 'chip-bad' },
  MEDIUM: { label: 'Média', cls: 'chip-warn' },
  LOW: { label: 'Baixa', cls: '' },
};

export const initials = (name: string) => name.split(' ').map((p) => p[0]).slice(0, 2).join('');

export const timeOf = (iso: string) =>
  new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
