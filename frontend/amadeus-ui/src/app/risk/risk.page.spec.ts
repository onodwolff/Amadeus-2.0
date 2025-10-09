import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { RiskApi } from '../api/clients';
import { RiskLimits } from '../api/models';
import { NotificationService } from '../shared/notifications/notification.service';
import { RiskPage } from './risk.page';

describe('RiskPage advanced controls', () => {
  let fixture: ComponentFixture<RiskPage>;
  let component: RiskPage;
  let riskApi: jasmine.SpyObj<RiskApi>;

  const limits: RiskLimits = {
    position_limits: {
      enabled: true,
      status: 'up_to_date',
      limits: [
        {
          venue: 'BINANCE',
          node: 'node-1',
          limit: 250000,
        },
      ],
    },
    max_loss: {
      enabled: true,
      status: 'up_to_date',
      daily: 100000,
      weekly: 250000,
    },
    trade_locks: {
      enabled: true,
      status: 'up_to_date',
      locks: [
        {
          venue: 'BINANCE',
          node: 'node-1',
          locked: false,
          reason: null,
        },
      ],
    },
    controls: {
      halt_on_breach: true,
      notify_on_recovery: true,
      escalation: {
        warn_after: 1,
        halt_after: 2,
        reset_minutes: 30,
      },
    },
  };

  const scope = { user_id: 'user-1', node_id: null };

  beforeEach(async () => {
    riskApi = jasmine.createSpyObj<RiskApi>('RiskApi', ['getRiskLimits', 'updateRiskLimits', 'getRisk']);
    riskApi.getRiskLimits.and.returnValue(of({ limits, scope }));
    riskApi.updateRiskLimits.and.returnValue(of({ limits, scope }));
    riskApi.getRisk.and.returnValue(
      of({
        risk: {
          timestamp: new Date().toISOString(),
          exposure_limits: [],
          drawdown_limits: [],
        },
        limits,
      }),
    );

    const notificationServiceStub = jasmine.createSpyObj<NotificationService>(
      'NotificationService',
      ['success', 'info', 'warning', 'error'],
    );

    await TestBed.configureTestingModule({
      imports: [RiskPage],
      providers: [
        provideZonelessChangeDetection(),
        { provide: RiskApi, useValue: riskApi },
        { provide: NotificationService, useValue: notificationServiceStub },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RiskPage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  function getAdvancedToggle(host: HTMLElement): HTMLButtonElement {
    const toggle = host.querySelector('.risk-advanced__toggle') as HTMLButtonElement | null;
    if (!toggle) {
      throw new Error('Advanced controls toggle not found');
    }
    return toggle;
  }

  it('should collapse advanced controls by default and expand when toggled', () => {
    const host = fixture.nativeElement as HTMLElement;
    const toggle = getAdvancedToggle(host);
    const content = host.querySelector('.risk-advanced__content') as HTMLElement | null;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(content?.getAttribute('aria-hidden')).toBe('true');

    toggle.click();
    fixture.detectChanges();

    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(content?.getAttribute('aria-hidden')).toBe('false');
    expect(component.advancedControlsExpanded()).toBeTrue();
    expect(content?.querySelector('[formControlName="halt_on_breach"]')).not.toBeNull();
    expect(content?.querySelector('[formControlName="notify_on_recovery"]')).not.toBeNull();
    expect(content?.querySelector('fieldset[formGroupName="escalation"]')).not.toBeNull();
  });

  it('should keep validation active for advanced controls when collapsed', () => {
    const host = fixture.nativeElement as HTMLElement;
    const toggle = getAdvancedToggle(host);
    const content = host.querySelector('.risk-advanced__content') as HTMLElement | null;

    expect(component.form.valid).withContext('form should start valid').toBeTrue();
    expect(component.advancedControlsExpanded()).toBeFalse();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(content?.getAttribute('aria-hidden')).toBe('true');

    const escalationGroup = component.controlsGroup.controls.escalation;
    escalationGroup.controls.warn_after.setValue(0);
    component.form.updateValueAndValidity();
    fixture.detectChanges();

    expect(component.advancedControlsExpanded()).toBeFalse();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(content?.getAttribute('aria-hidden')).toBe('true');
    expect(escalationGroup.invalid).withContext('escalation group should become invalid').toBeTrue();
    expect(component.form.invalid).withContext('form should reflect invalid advanced controls').toBeTrue();
  });
});

