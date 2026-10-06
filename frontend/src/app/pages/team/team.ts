import { HttpClient } from '@angular/common/http';
import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { initials } from '../../core/labels';
import { TeamDetail } from '../../core/models';
import { Session } from '../../core/session.service';

/** Configuração do time (só gestores): nome, fuso, horário de corte, perguntas-base e membros. */
@Component({ selector: 'app-team', imports: [FormsModule], templateUrl: './team.html', styleUrl: './team.scss' })
export class TeamPage {
  private http = inject(HttpClient);
  protected session = inject(Session);
  protected initials = initials;
  protected timezones = ['America/Sao_Paulo', 'America/Manaus', 'America/Recife', 'America/Fortaleza', 'America/Cuiaba', 'America/Belem', 'America/Rio_Branco'];

  protected team = signal<TeamDetail | null>(null);
  protected form = { name: '', timezone: 'America/Sao_Paulo', cutoff_time: '10:00', questions: [''] };
  protected newMember = { name: '', email: '' };
  protected newTeamName = '';
  protected creating = signal(false);
  protected message = signal<string | null>(null);
  protected error = signal<string | null>(null);

  constructor() {
    effect(() => { const id = this.session.teamId(); if (id) void this.load(id); });
  }

  private async load(id: string) {
    this.apply(await firstValueFrom(this.http.get<TeamDetail>(`/api/teams/${id}`)));
  }

  private apply(t: TeamDetail) {
    this.team.set(t);
    this.form = { name: t.name, timezone: t.timezone, cutoff_time: t.cutoff_time, questions: [...t.base_questions] };
  }

  private async attempt(action: () => Promise<void>) {
    this.error.set(null);
    try { await action(); } catch (e: any) { this.error.set(e?.error?.detail ?? 'Não foi possível salvar.'); }
  }

  protected save() {
    return this.attempt(async () => {
      const t = await firstValueFrom(this.http.put<TeamDetail>(`/api/teams/${this.team()!.id}`, {
        name: this.form.name, timezone: this.form.timezone, cutoff_time: this.form.cutoff_time, base_questions: this.form.questions }));
      this.apply(t);
      await this.session.load();
      this.message.set('Alterações salvas.');
    });
  }

  protected addMember() {
    return this.attempt(async () => {
      this.apply(await firstValueFrom(this.http.post<TeamDetail>(`/api/teams/${this.team()!.id}/members`, this.newMember)));
      this.newMember = { name: '', email: '' };
      await this.session.refreshToday();
    });
  }

  protected removeMember(id: number) {
    return this.attempt(async () => {
      this.apply(await firstValueFrom(this.http.delete<TeamDetail>(`/api/teams/${this.team()!.id}/members/${id}`)));
      await this.session.refreshToday();
    });
  }

  protected createTeam() {
    return this.attempt(async () => {
      const t = await firstValueFrom(this.http.post<TeamDetail>('/api/teams', { name: this.newTeamName, base_questions: [] }));
      this.creating.set(false);
      this.newTeamName = '';
      await this.session.load();
      await this.session.selectTeam(t.id);
    });
  }

  protected trackIndex = (i: number) => i;
}
