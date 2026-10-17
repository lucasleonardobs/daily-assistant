import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { DevUser, Me, Today } from './models';

export interface AuthConfig { dev_mode: boolean; }

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
  readonly config = signal<AuthConfig | null>(null);
  /** Produção sem sessão aberta: mostra a tela de login. */
  readonly needsLogin = signal(false);
  /** Token do link de convite (/ativar?token=...), enquanto a pessoa define a senha. */
  readonly activationToken = signal<string | null>(
    location.pathname === '/ativar' ? new URLSearchParams(location.search).get('token') : null);
  readonly teamId = signal<string | null>(null);
  readonly today = signal<Today | null>(null);

  readonly membership = computed(() => this.me()?.memberships.find((m) => m.team_id === this.teamId()) ?? null);
  readonly isManager = computed(() => this.membership()?.role === 'manager');

  async start(): Promise<void> {
    try { this.config.set(await firstValueFrom(this.http.get<AuthConfig>('/api/auth/config'))); } catch { /* segue sem config */ }
    if (!this.config()?.dev_mode) { await this.load(); return; }
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
      this.needsLogin.set(false);
      const saved = localStorage.getItem(KEY_TEAM);
      this.teamId.set(me.memberships.find((m) => m.team_id === saved)?.team_id ?? me.memberships[0].team_id);
      if (!me.must_change_password) await this.refreshToday();
    } catch (e: any) {
      this.me.set(null);
      this.needsLogin.set(e?.status === 401 && !this.config()?.dev_mode);
      this.error.set(e?.error?.detail ?? 'Não foi possível entrar.');
    }
  }

  /** Entra com e-mail e senha. Devolve a mensagem de erro, se houver. */
  async login(email: string, password: string): Promise<string | null> {
    try {
      await firstValueFrom(this.http.post('/api/auth/login', { email, password }));
      await this.load();
      return this.me() ? null : this.error();
    } catch (e: any) {
      return e?.error?.detail ?? 'Não foi possível entrar.';
    }
  }

  /** Define a senha a partir do link de convite e já abre a sessão. */
  async activate(token: string, password: string): Promise<string | null> {
    try {
      await firstValueFrom(this.http.post('/api/auth/activate', { token, password }));
      this.activationToken.set(null);
      await this.load();
      return null;
    } catch (e: any) {
      return e?.error?.detail ?? 'Não foi possível definir a senha.';
    }
  }

  async changePassword(current: string, next: string): Promise<string | null> {
    try {
      await firstValueFrom(this.http.post('/api/auth/change-password', { current_password: current, new_password: next }));
      await this.load();
      return null;
    } catch (e: any) {
      return e?.error?.detail ?? 'Não foi possível trocar a senha.';
    }
  }

  async logout(): Promise<void> {
    await firstValueFrom(this.http.post('/api/auth/logout', {}));
    this.me.set(null);
    this.today.set(null);
    this.needsLogin.set(true);
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
