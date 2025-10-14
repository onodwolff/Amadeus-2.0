import { Signal, WritableSignal, signal } from '@angular/core';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { provideRouter } from '@angular/router';
import { OrdersApi } from '../api/clients/orders.api';
import { KeysApi } from '../api/clients/keys.api';
import { ExecutionReport, OrderSummary } from '../api/models';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { WsConnectionState, WsService } from '../ws.service';
import { OrdersPage } from './orders.page';

describe('OrdersPage (role-based UI)', () => {
  let rolesSignal: WritableSignal<string[]>;
  let permissionsSignal: WritableSignal<string[]>;

  const sampleOrder: OrderSummary = {
    order_id: 'ORD-1',
    symbol: 'BTCUSDT',
    venue: 'BINANCE',
    side: 'buy',
    type: 'limit',
    quantity: 1,
    filled_quantity: 0,
    status: 'pending',
    created_at: new Date().toISOString(),
  };

  const sampleExecution: ExecutionReport = {
    order_id: 'ORD-1',
    execution_id: 'EX-1',
    symbol: 'BTCUSDT',
    venue: 'BINANCE',
    price: 100,
    quantity: 0.5,
    side: 'buy',
    timestamp: new Date().toISOString(),
  };

  class MockWsService {
    channel() {
      return {
        messages$: of({ orders: [sampleOrder], executions: [sampleExecution] }),
        state$: of('connected' as WsConnectionState),
      };
    }
  }

  beforeEach(async () => {
    rolesSignal = signal<string[]>([]);
    permissionsSignal = signal<string[]>([]);

    await TestBed.configureTestingModule({
      imports: [OrdersPage],
      providers: [
        provideZonelessChangeDetection(),
        provideRouter([]),
        {
          provide: OrdersApi,
          useValue: {
            listOrders: () => of({ orders: [sampleOrder], executions: [sampleExecution] }),
            cancelOrder: jasmine.createSpy('cancelOrder').and.returnValue(of({})),
            duplicateOrder: jasmine.createSpy('duplicateOrder').and.returnValue(of({})),
            modifyOrder: jasmine.createSpy('modifyOrder').and.returnValue(of({})),
          } satisfies Partial<OrdersApi>,
        },
        {
          provide: KeysApi,
          useValue: {
            listKeys: () => of({ keys: [] }),
          } satisfies Partial<KeysApi>,
        },
        { provide: WsService, useClass: MockWsService },
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

  it('hides order submission and actions for non-trader users', () => {
    const fixture = TestBed.createComponent(OrdersPage);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.querySelector('app-order-ticket')).toBeNull();
    expect(compiled.querySelector('[data-testid="orders-ticket-locked"]')).not.toBeNull();
    expect(compiled.querySelector('[data-testid="orders-actions-locked"]')).not.toBeNull();
  });
});
