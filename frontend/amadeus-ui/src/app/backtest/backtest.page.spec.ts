import { Signal, WritableSignal, signal } from '@angular/core';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import { BacktestsApi, DataApi } from '../api/clients';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { BacktestPage } from './backtest.page';

describe('BacktestPage (role-based UI)', () => {
  let rolesSignal: WritableSignal<string[]>;
  let permissionsSignal: WritableSignal<string[]>;

  beforeEach(async () => {
    rolesSignal = signal<string[]>([]);
    permissionsSignal = signal<string[]>([]);

    await TestBed.configureTestingModule({
      imports: [BacktestPage],
      providers: [
        provideZonelessChangeDetection(),
        {
          provide: BacktestsApi,
          useValue: {
            createRun: jasmine.createSpy('createRun').and.returnValue(of({ run: { id: 'run-1' } })),
          } satisfies Partial<BacktestsApi>,
        },
        {
          provide: DataApi,
          useValue: {
            listDatasets: jasmine.createSpy('listDatasets').and.returnValue(of({ datasets: [] })),
          } satisfies Partial<DataApi>,
        },
        {
          provide: Router,
          useValue: {
            navigate: jasmine.createSpy('navigate').and.returnValue(Promise.resolve(true)),
          } satisfies Partial<Router>,
        },
        {
          provide: AuthStateService,
          useValue: {
            permissions: permissionsSignal as Signal<string[]>,
            roles: rolesSignal as Signal<string[]>,
            hasRole: (role: string) => {
              const roles = rolesSignal();
              return roles.includes('admin') || roles.includes(role);
            },
          } satisfies Partial<AuthStateService> & {
            permissions: Signal<string[]>;
            roles: Signal<string[]>;
            hasRole: (role: string) => boolean;
          },
        },
      ],
    }).compileComponents();
  });

  it('shows restriction notice for non-trader users', () => {
    const fixture = TestBed.createComponent(BacktestPage);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.querySelector('form.backtest-form')).toBeNull();
    expect(compiled.querySelector('[data-testid="backtest-locked"]')).not.toBeNull();
  });
});
