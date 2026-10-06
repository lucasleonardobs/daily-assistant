import { Component, computed, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { initials } from './core/labels';
import { Session } from './core/session.service';

/** Casca do app: barra lateral (por papel), cabeçalho (time e data) e a página atual. */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected session = inject(Session);
  private router = inject(Router);
  protected initials = initials;

  protected nav = computed(() => {
    const today = this.session.today();
    return this.session.isManager()
      ? [{ path: '/painel', label: 'Painel do time', badge: today ? `${today.responded}/${today.total}` : '' },
         { path: '/report', label: 'Report', badge: '' },
         { path: '/time', label: 'Configuração', badge: '' }]
      : [{ path: '/checkin', label: 'Check-in', badge: '' },
         { path: '/report', label: 'Report do time', badge: '' }];
  });

  protected dateLabel = computed(() => {
    const t = this.session.today();
    if (!t) return '';
    const d = new Date(t.date + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });
    return `${d[0].toUpperCase()}${d.slice(1)} · corte sugerido ${t.team.cutoff_time} · ${t.team.timezone}`;
  });

  protected async onUser(email: string) {
    await this.session.switchUser(email);
    await this.router.navigateByUrl(this.session.isManager() ? '/painel' : '/checkin');
  }

  protected async onTeam(teamId: string) {
    await this.session.selectTeam(teamId);
    await this.router.navigateByUrl(this.session.isManager() ? '/painel' : '/checkin');
  }
}
