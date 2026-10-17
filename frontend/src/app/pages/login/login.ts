import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Session } from '../../core/session.service';

/** Tela de entrada em produção: e-mail e senha. Primeiro acesso e "esqueci a senha" são por link do gestor. */
@Component({
  selector: 'app-login',
  imports: [FormsModule],
  template: `
    <form class="card card-pad box" (ngSubmit)="enter()">
      <div class="logo">bv</div>
      <h1>Daily assíncrona</h1>
      <span class="muted">Entre com o seu e-mail e senha.</span>
      <label class="field">E-mail<input type="email" name="email" [(ngModel)]="email" autocomplete="username" required /></label>
      <label class="field">Senha<input type="password" name="password" [(ngModel)]="password" autocomplete="current-password" required /></label>
      @if (error()) { <div class="error-box">{{ error() }}</div> }
      <button class="btn" type="submit" [disabled]="busy() || !email || !password">{{ busy() ? 'Entrando…' : 'Entrar' }}</button>
      <span class="muted small">Primeiro acesso ou esqueceu a senha? Peça um novo link de acesso ao gestor do seu time.</span>
    </form>`,
  styles: [`
    .box { max-width: 420px; margin: 8vh auto 0; display: flex; flex-direction: column; gap: 14px; }
    .logo { width: 44px; height: 44px; border-radius: 12px; background: var(--brand); color: #fff; font-weight: 800; font-size: 20px;
      display: flex; align-items: center; justify-content: center; }
    .small { font-size: 13px; }`],
})
export class Login {
  private session = inject(Session);
  protected email = '';
  protected password = '';
  protected error = signal<string | null>(null);
  protected busy = signal(false);

  protected async enter() {
    this.busy.set(true);
    this.error.set(await this.session.login(this.email.trim(), this.password));
    this.busy.set(false);
  }
}
