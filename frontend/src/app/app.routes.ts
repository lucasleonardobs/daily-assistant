import { inject } from '@angular/core';
import { CanActivateFn, Router, Routes } from '@angular/router';
import { Session } from './core/session.service';

const home: CanActivateFn = () => inject(Router).createUrlTree([inject(Session).isManager() ? '/painel' : '/checkin']);
const managerOnly: CanActivateFn = () => inject(Session).isManager() || inject(Router).createUrlTree(['/checkin']);

export const routes: Routes = [
  { path: 'checkin', loadComponent: () => import('./pages/checkin/checkin').then((m) => m.Checkin) },
  { path: 'painel', canActivate: [managerOnly], loadComponent: () => import('./pages/panel/panel').then((m) => m.Panel) },
  { path: 'report', loadComponent: () => import('./pages/report/report').then((m) => m.ReportPage) },
  { path: 'time', canActivate: [managerOnly], loadComponent: () => import('./pages/team/team').then((m) => m.TeamPage) },
  { path: '**', canActivate: [home], children: [] },
];
