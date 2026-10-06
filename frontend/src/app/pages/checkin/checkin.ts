import { HttpClient } from '@angular/common/http';
import { Component, ElementRef, Injector, ViewChild, afterNextRender, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { streamAgent } from '../../core/agent-stream';
import { CATEGORY, SEVERITY, timeOf } from '../../core/labels';
import { AgentEvent, CheckinContext, CheckinDraft } from '../../core/models';
import { Session } from '../../core/session.service';

interface Message {
  kind: 'agent' | 'user' | 'summary';
  text: string;
  time: string;
  draft?: CheckinDraft;
}
type Stage = 'loading' | 'chatting' | 'summary' | 'correcting' | 'done' | 'discarded';

/** Tela do membro: conversa com o agente de check-in. O resumo só é gravado após Confirmar. */
@Component({ selector: 'app-checkin', imports: [FormsModule], templateUrl: './checkin.html', styleUrl: './checkin.scss' })
export class Checkin {
  private http = inject(HttpClient);
  private session = inject(Session);
  private injector = inject(Injector);
  @ViewChild('chat') private chat?: ElementRef<HTMLElement>;

  protected category = CATEGORY;
  protected severity = SEVERITY;
  protected ctx = signal<CheckinContext | null>(null);
  protected messages = signal<Message[]>([]);
  protected stage = signal<Stage>('loading');
  protected typing = signal(false);
  protected error = signal<string | null>(null);
  protected input = '';
  protected confirmedAt = signal<string | null>(null);

  private sessionId = '';
  private review: { interrupt_id: string; invocation_id: string } | null = null;

  protected statusLabel = computed(() => ({
    loading: 'Iniciando…', chatting: 'Em andamento', summary: 'Aguardando confirmação',
    correcting: 'Em andamento', done: 'Confirmado', discarded: 'Não salvo' }[this.stage()]));
  protected canType = computed(() => ['chatting', 'correcting'].includes(this.stage()) && !this.typing());
  protected lastSummaryIndex = computed(() => this.messages().map((m) => m.kind).lastIndexOf('summary'));

  constructor() {
    void this.init();
    // Rola até o fim depois que a tela renderiza a nova mensagem (o resumo é um card alto).
    effect(() => {
      this.messages(); this.typing();
      afterNextRender(() => { const el = this.chat?.nativeElement; if (el) el.scrollTop = el.scrollHeight; },
        { injector: this.injector });
    });
  }

  private get base() { return `/api/teams/${this.session.teamId()}/checkin`; }

  private async init() {
    const ctx = await firstValueFrom(this.http.get<CheckinContext>(`${this.base}/context`));
    this.ctx.set(ctx);
    if (ctx.today) {
      this.confirmedAt.set(timeOf(ctx.today.confirmed_at));
      this.push('agent', 'Seu check-in de hoje já está salvo. Quer editar? A nova versão substitui a anterior.');
      this.stage.set('done');
      return;
    }
    await this.openSession(false, 'Iniciar check-in');
  }

  private async openSession(fresh: boolean, firstMessage: string) {
    this.stage.set('loading');
    const { session_id } = await firstValueFrom(this.http.post<{ session_id: string }>(`${this.base}/session`, { fresh }));
    this.sessionId = session_id;
    this.stage.set('chatting');
    await this.talk({ text: firstMessage });  // sinal de início: o agente abre a conversa
  }

  protected async send() {
    const text = this.input.trim();
    if (!text || !this.canType()) return;
    this.input = '';
    this.push('user', text);
    if (this.stage() === 'correcting' && this.review) {  // a pessoa descreveu o que corrigir
      await this.talk({ review: { ...this.review, action: 'correct', correction: text } });
    } else {
      await this.talk({ text });
    }
  }

  protected async confirm() {
    if (this.review) await this.talk({ review: { ...this.review, action: 'confirm' } });
  }

  protected correct() {
    this.stage.set('correcting');
    this.push('agent', 'Claro. O que devo ajustar?');
  }

  protected async edit() {
    this.messages.set([]);
    this.confirmedAt.set(null);
    await this.openSession(true, 'Quero editar meu check-in de hoje.');
  }

  protected onKey(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void this.send(); }
  }

  /** Uma rodada com o agente: manda a mensagem e mostra os eventos que chegam. */
  private async talk(body: { text?: string; review?: unknown }) {
    this.typing.set(true);
    this.error.set(null);
    try {
      for await (const e of streamAgent(`${this.base}/messages`,
          { session_id: this.sessionId, invocation_id: this.review?.invocation_id, ...body }, this.session.devEmail())) {
        this.onEvent(e);
      }
    } catch (err: any) {
      this.error.set(err.message);
    } finally {
      this.typing.set(false);
    }
  }

  private onEvent(e: AgentEvent) {
    if (e.type === 'agent') this.push('agent', e.text);
    if (e.type === 'review') {
      this.review = { interrupt_id: e.interrupt_id, invocation_id: e.invocation_id };
      this.push('summary', 'Resumo do seu check-in. Está certo?', e.draft);
      this.stage.set('summary');
    }
    if (e.type === 'saved') {
      this.push('agent', e.text);
      this.confirmedAt.set(timeOf(new Date().toISOString()));
      this.review = null;
      this.stage.set('done');
      void this.session.refreshToday();
    }
    if (e.type === 'discarded') {
      this.push('agent', e.text);
      this.review = null;
      this.stage.set('discarded');
    }
    if (e.type === 'error') this.error.set(e.text);
  }

  private push(kind: Message['kind'], text: string, draft?: CheckinDraft) {
    this.messages.update((list) => [...list, { kind, text, draft, time: timeOf(new Date().toISOString()) }]);
  }

  protected ageOf(impId: number | null): string | null {
    return this.ctx()?.open_impediments.find((i) => i.id === impId)?.age_label ?? null;
  }

  protected resolvedTexts(draft: CheckinDraft): string[] {
    const open = this.ctx()?.open_impediments ?? [];
    return draft.resolved_impediment_ids.map((id) => open.find((i) => i.id === id)?.summary).filter((t): t is string => !!t);
  }

  protected dayLabel = (iso: string) =>
    new Date(iso + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'short', day: 'numeric', month: 'short' });

  protected joinSummaries = (items: { summary: string }[]) => items.map((i) => i.summary).join('; ') || '—';
}
