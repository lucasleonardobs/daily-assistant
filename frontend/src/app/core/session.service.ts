import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { DevUser, Me, Today } from './models';

const KEY_EMAIL = 'daily.dev-email';
const KEY_TEAM = 'daily.team';

/** Quem está logado, em qual time e o estado do dia. Um único lugar para o resto do app consultar. */
@Injectable({ providedIn: 'root' })
export class Session {
  private http = inject(HttpClient);

  /** E-mail enviado no header X-User-Email (só dev). Em produção o IAP identifica a pessoa. */
  readonly devEmail = signal<string | null>(localStorage.getItem(KEY_EMAIL));
  readonly devUsers = signal<DevUser[]>([]);
  readonly me = signal<Me | null>(null);
  readonly error = signal<string | null>(null);
  readonly teamId = signal<string | null>(null);
  readonly today = signal<Today | null>(null);

  readonly membership = computed(() => this.me()?.memberships.find((m) => m.team_id === this.teamId()) ?? null);
  readonly isManager = computed(() => this.membership()?.role === 'manager');

  async start(): Promise<void> {
    try {
      this.devUsers.set(await firstValueFrom(this.http.get<DevUser[]>('/api/dev/users')));
      if (!this.devEmail()) this.setDevEmail(this.devUsers().find((u) => !u.roles.includes('manager'))?.email ?? this.devUsers()[0]?.email);
    } catch { /* fora do modo dev a rota não existe */ }
    await this.load();
  }

  async load(): Promise<void> {
    try {
      const me = await firstValueFrom(this.http.get<Me>('/api/me'));
      this.me.set(me);
      this.error.set(null);
      const saved = localStorage.getItem(KEY_TEAM);
      this.teamId.set(me.memberships.find((m) => m.team_id === saved)?.team_id ?? me.memberships[0].team_id);
      await this.refreshToday();
    } catch (e: any) {
      this.me.set(null);
      this.error.set(e?.error?.detail ?? 'Não foi possível entrar.');
    }
  }

  async switchUser(email: string): Promise<void> {
    this.setDevEmail(email);
    this.today.set(null);
    await this.load();
  }

  async selectTeam(teamId: string): Promise<void> {
    localStorage.setItem(KEY_TEAM, teamId);
    this.teamId.set(teamId);
    await this.refreshToday();
  }

  async refreshToday(): Promise<void> {
    const id = this.teamId();
    if (id) this.today.set(await firstValueFrom(this.http.get<Today>(`/api/teams/${id}/cycles/today`)));
  }

  private setDevEmail(email?: string) {
    if (!email) return;
    this.devEmail.set(email);
    localStorage.setItem(KEY_EMAIL, email);
  }
}
