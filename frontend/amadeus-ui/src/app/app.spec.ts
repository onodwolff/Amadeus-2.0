import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { AppComponent } from './app.component';

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent, RouterTestingModule],
      providers: [provideZonelessChangeDetection()]
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render main navigation', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const navLinks = Array.from(
      compiled.querySelectorAll('.app-sidebar__link')
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
      'Settings'
    ]);
  });
});
