import { Signal, WritableSignal, signal } from '@angular/core';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { StrategyTestsApi } from '../api/clients';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { StrategyTestingPage } from './strategy-testing.page';

describe('StrategyTestingPage (role-based UI)', () => {
  let rolesSignal: WritableSignal<string[]>;
  let permissionsSignal: WritableSignal<string[]>;

  beforeEach(async () => {
    rolesSignal = signal<string[]>([]);
    permissionsSignal = signal<string[]>([]);

    await TestBed.configureTestingModule({
      imports: [StrategyTestingPage],
      providers: [
        provideZonelessChangeDetection(),
        {
          provide: StrategyTestsApi,
          useValue: {
            createRun: jasmine.createSpy('createRun').and.returnValue(of({ run: { id: 'run-1', status: 'queued' } })),
            getRun: jasmine.createSpy('getRun').and.returnValue(of({ run: { id: 'run-1', status: 'completed' } })),
            listRuns: jasmine.createSpy('listRuns').and.returnValue(of({ runs: [] })),
          } satisfies Partial<StrategyTestsApi>,
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
    const fixture = TestBed.createComponent(StrategyTestingPage);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.querySelector('form#strategyTestingForm')).toBeNull();
    expect(compiled.querySelector('[data-testid="strategy-testing-locked"]')).not.toBeNull();
  });
});
