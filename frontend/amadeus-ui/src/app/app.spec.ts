import { provideZonelessChangeDetection } from '@angular/core';
import { Signal, WritableSignal, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { AppComponent } from './app.component';
import { AuthStateService } from './shared/auth/auth-state.service';

describe('AppComponent', () => {
  let permissionsSignal: WritableSignal<string[]>;
  let rolesSignal: WritableSignal<string[]>;

  beforeEach(async () => {
    permissionsSignal = signal<string[]>([]);
    rolesSignal = signal<string[]>([]);
    await TestBed.configureTestingModule({
      imports: [AppComponent, RouterTestingModule],
      providers: [
        provideZonelessChangeDetection(),
        {
          provide: AuthStateService,
          useValue: {
            initialize: jasmine.createSpy('initialize'),
            permissions: permissionsSignal,
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

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render trader navigation when role is present', () => {
    const fixture = TestBed.createComponent(AppComponent);
    rolesSignal.set(['trader']);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const navLinks = Array.from(
      compiled.querySelectorAll('.app-sidebar__link'),
    ).map((link) => link.textContent?.trim());

    expect(compiled.querySelector('.app-brand')?.textContent).toBe('Amadeus');
    expect(navLinks).toEqual([
      'Dashboard',
      'Market',
      'Portfolio',
      'Orders',
      'Backtest',
      'Strategy Testing',
      'Data',
      'Risk',
      'Settings',
    ]);
  });

  it('should hide trader navigation for non-trader users', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const navLinks = Array.from(
      compiled.querySelectorAll('.app-sidebar__link'),
    ).map((link) => link.textContent?.trim());

    expect(navLinks).toEqual(['Data', 'Settings']);
  });
});
