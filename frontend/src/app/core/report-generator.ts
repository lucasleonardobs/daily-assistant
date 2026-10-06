import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { streamAgent } from './agent-stream';
import { Session } from './session.service';

export const REPORT_STEPS = ['Carregando check-ins', 'Analisando progresso', 'Cruzando bloqueios', 'Revisão do crítico', 'Publicando'];

/** Gera o report (SSE do grafo) e informa a etapa atual. Usado pelo painel e pela tela do report. */
@Injectable({ providedIn: 'root' })
export class ReportGenerator {
  private session = inject(Session);
  private router = inject(Router);

  readonly generating = signal(false);
  readonly step = signal(0);
  readonly error = signal<string | null>(null);

  async generate(): Promise<void> {
    const team = this.session.teamId();
    if (!team || this.generating()) return;
    this.generating.set(true);
    this.step.set(0);
    this.error.set(null);
    try {
      for await (const event of streamAgent(`/api/teams/${team}/reports`, {}, this.session.devEmail())) {
        if (event.type === 'step') this.step.set(event.step);
        if (event.type === 'error') this.error.set(event.text);
        if (event.type === 'done') {
          await this.session.refreshToday();
          await this.router.navigate(['/report'], { queryParams: { id: event.report_id } });
        }
      }
    } catch (e: any) {
      this.error.set(e.message);
    } finally {
      this.generating.set(false);
    }
  }
}
