import { HttpClient } from '@angular/common/http';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { SEVERITY, initials, timeOf } from '../../core/labels';
import { Report, ReportVersion } from '../../core/models';
import { ReportGenerator } from '../../core/report-generator';
import { Session } from '../../core/session.service';

const GROUPS = [
  { status: 'NEW', label: 'Novos' },
  { status: 'OPEN', label: 'Abertos' },
  { status: 'RESOLVED', label: 'Resolvidos desde ontem' },
] as const;

/** Report do dia: começa pelo que exige ação. Toda afirmação aponta para o check-in de origem. */
@Component({ selector: 'app-report', templateUrl: './report.html', styleUrl: './report.scss' })
export class ReportPage {
  private http = inject(HttpClient);
  private route = inject(ActivatedRoute);
  protected session = inject(Session);
  protected generator = inject(ReportGenerator);

  protected severity = SEVERITY;
  protected initials = initials;
  protected timeOf = timeOf;
  protected versions = signal<ReportVersion[]>([]);
  protected report = signal<Report | null>(null);
  protected expanded = signal<string | null>(null);
  protected loading = signal(true);

  protected groups = computed(() => {
    const items = this.report()?.content.impediments ?? [];
    return GROUPS.map((g) => ({ label: g.label, items: items.filter((i) => i.status === g.status) })).filter((g) => g.items.length);
  });

  constructor() {
    effect(() => {  // recarrega ao trocar de time ou ao chegar com ?id=
      this.session.teamId();
      void this.load(Number(this.route.snapshot.queryParamMap.get('id')) || null);
    });
  }

  private async load(id: number | null) {
    const team = this.session.teamId();
    if (!team) return;
    this.loading.set(true);
    const versions = await firstValueFrom(this.http.get<ReportVersion[]>(`/api/teams/${team}/reports`));
    this.versions.set(versions);
    const pick = id && versions.some((v) => v.id === id) ? id : versions.at(-1)?.id;
    this.report.set(pick ? await firstValueFrom(this.http.get<Report>(`/api/reports/${pick}`)) : null);
    this.loading.set(false);
  }

  protected select(id: number) { void this.load(id); }

  protected labels(ids: string[]): { id: string; label: string }[] {
    const labels = this.report()?.content.evidence_labels ?? {};
    return ids.map((id) => ({ id, label: labels[id] ?? id }));
  }

  protected open(checkinId: string) {
    const known = this.report()?.content.people.some((p) => p.checkin_id === checkinId);
    this.expanded.set(known ? checkinId : null);
    if (known) document.getElementById('people')?.scrollIntoView({ behavior: 'smooth' });
  }

  protected toggle(checkinId: string) { this.expanded.update((cur) => (cur === checkinId ? null : checkinId)); }

  protected async vote(index: number, value: 'useful' | 'not_useful') {
    const r = this.report();
    if (!r) return;
    const next = r.feedback[index] === value ? null : value;  // clicar de novo desmarca
    const { feedback } = await firstValueFrom(
      this.http.post<{ feedback: Report['feedback'] }>(`/api/reports/${r.id}/feedback`, { action_index: index, value: next }));
    this.report.set({ ...r, feedback });
  }
}
