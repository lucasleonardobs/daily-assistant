import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { Session } from '../../core/session.service';

/** Abre pelo link de convite (/ativar?token=...): a pessoa define a própria senha, uma única vez. */
@Component({
  selector: 'app-activate',
  imports: [FormsModule],
  template: `
    <div class="wrap">
      <form class="card card-pad box" (ngSubmit)="save()">
        <div class="logo">bv</div>
        @if (invite(); as i) {
          <h1>Olá, {{ i.name.split(' ')[0] }}</h1>
          <span class="muted">Defina a senha de acesso de <b>{{ i.email }}</b>. Este link só funciona uma vez.</span>
          <input type="text" name="username" autocomplete="username" [value]="i.email" hidden />
          <label class="field">Nova senha<input type="password" name="p1" [(ngModel)]="password" autocomplete="new-password" required /></label>
          <label class="field">Repita a senha<input type="password" name="p2" [(ngModel)]="confirm" autocomplete="new-password" required /></label>
          <span class="muted small">Mínimo de 10 caracteres, sem o seu e-mail dentro.</span>
          @if (error()) { <div class="error-box">{{ error() }}</div> }
          <button class="btn" type="submit" [disabled]="busy() || !password || password !== confirm">Salvar e entrar</button>
          @if (password && confirm && password !== confirm) { <span class="muted small">As senhas não coincidem.</span> }
        } @else if (invalid()) {
          <h1>Link inválido ou expirado</h1>
          <span class="muted">Peça um novo link de acesso ao gestor do seu time.</span>
        } @else { <span class="muted">Verificando o convite…</span> }
      </form>
    </div>`,
  styles: [`
    .wrap { min-height: 100vh; display: flex; align-items: flex-start; justify-content: center; padding: 8vh 16px 0; }
    .box { width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 14px; }
    .logo { width: 44px; height: 44px; border-radius: 12px; background: var(--brand); color: #fff; font-weight: 800; font-size: 20px;
      display: flex; align-items: center; justify-content: center; }
    .small { font-size: 13px; }`],
})
export class Activate implements OnInit {
  private http = inject(HttpClient);
  private session = inject(Session);
  private router = inject(Router);
  protected invite = signal<{ email: string; name: string } | null>(null);
  protected invalid = signal(false);
  protected error = signal<string | null>(null);
  protected busy = signal(false);
  protected password = '';
  protected confirm = '';

  async ngOnInit() {
    try {
      this.invite.set(await firstValueFrom(this.http.get<{ email: string; name: string }>(`/api/auth/invite/${this.session.activationToken()}`)));
    } catch { this.invalid.set(true); }
  }

  protected async save() {
    this.busy.set(true);
    const message = await this.session.activate(this.session.activationToken()!, this.password);
    this.busy.set(false);
    if (message) { this.error.set(message); return; }
    await this.router.navigateByUrl('/');  // tira o token da barra de endereço
  }
}
