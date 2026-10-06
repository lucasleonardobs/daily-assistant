import { HttpClient } from '@angular/common/http';
import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { SEVERITY, CATEGORY, initials, timeOf } from '../../core/labels';
import { ReportGenerator, REPORT_STEPS } from '../../core/report-generator';
import { Session } from '../../core/session.service';

/** Painel do gestor: quem respondeu, impeditivos abertos e o botão Gerar report. */
@Component({ selector: 'app-panel', imports: [FormsModule, RouterLink], templateUrl: './panel.html', styleUrl: './panel.scss' })
export class Panel implements OnDestroy {
  private http = inject(HttpClient);
  protected session = inject(Session);
  protected generator = inject(ReportGenerator);

  protected steps = REPORT_STEPS;
  protected severity = SEVERITY;
  protected category = CATEGORY;
  protected initials = initials;
  protected timeOf = timeOf;
  protected severityKeys = ['HIGH', 'MEDIUM', 'LOW'];

  protected today = this.session.today;
  protected pct = computed(() => { const t = this.today(); return t && t.total ? Math.round((t.responded / t.total) * 100) : 0; });
  protected resolving = signal<number | null>(null);
  protected note = '';
  private timer = setInterval(() => void this.session.refreshToday(), 30_000);  // F3: polling a cada 30 s

  ngOnDestroy() { clearInterval(this.timer); }

  protected async setSeverity(id: number, severity: string) {
    await firstValueFrom(this.http.patch(`/api/impediments/${id}`, { severity }));
    await this.session.refreshToday();
  }

  protected startResolve(id: number) { this.resolving.set(id); this.note = ''; }

  protected async confirmResolve(id: number) {
    await firstValueFrom(this.http.patch(`/api/impediments/${id}`, { status: 'RESOLVED', note: this.note }));
    this.resolving.set(null);
    await this.session.refreshToday();
  }
}
