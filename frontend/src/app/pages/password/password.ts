import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Session } from '../../core/session.service';

/** Troca de senha. Obrigatória quando a conta foi criada com senha provisória. */
@Component({
  selector: 'app-password',
  imports: [FormsModule],
  template: `
    <form class="card card-pad box" (ngSubmit)="save()">
      <h1>{{ session.me()?.must_change_password ? 'Defina uma nova senha' : 'Alterar senha' }}</h1>
      @if (session.me()?.must_change_password) { <span class="muted">Por segurança, troque a senha provisória para continuar.</span> }
      <input type="text" name="username" autocomplete="username" [value]="session.me()?.email ?? ''" hidden />
      <label class="field">Senha atual<input type="password" name="cur" [(ngModel)]="current" autocomplete="current-password" required /></label>
      <label class="field">Nova senha<input type="password" name="n1" [(ngModel)]="next" autocomplete="new-password" required /></label>
      <label class="field">Repita a nova senha<input type="password" name="n2" [(ngModel)]="confirm" autocomplete="new-password" required /></label>
      <span class="muted small">Mínimo de 10 caracteres. Ao trocar, as outras sessões abertas serão encerradas.</span>
      @if (error()) { <div class="error-box">{{ error() }}</div> }
      @if (done()) { <div class="ok-box">Senha alterada.</div> }
      <button class="btn" type="submit" [disabled]="!current || !next || next !== confirm">Salvar</button>
    </form>`,
  styles: [`.box { max-width: 460px; display: flex; flex-direction: column; gap: 14px; } .small { font-size: 13px; }
    .ok-box { background: var(--ok-bg); color: var(--ok-fg); border-radius: 12px; padding: 12px 16px; font-weight: 700; }`],
})
export class PasswordPage {
  protected session = inject(Session);
  private router = inject(Router);
  protected current = '';
  protected next = '';
  protected confirm = '';
  protected error = signal<string | null>(null);
  protected done = signal(false);

  protected async save() {
    this.error.set(null);
    const message = await this.session.changePassword(this.current, this.next);
    if (message) { this.error.set(message); return; }
    this.current = this.next = this.confirm = '';
    this.done.set(true);
    await this.router.navigateByUrl(this.session.isManager() ? '/painel' : '/checkin');
  }
}
