import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Session } from './session.service';

/** Em dev, diz ao backend quem está logado (X-User-Email). Em produção o header do IAP faz isso. */
export const devUserInterceptor: HttpInterceptorFn = (req, next) => {
  const email = inject(Session).devEmail();
  return next(email && req.url.startsWith('/api') ? req.clone({ setHeaders: { 'X-User-Email': email } }) : req);
};
