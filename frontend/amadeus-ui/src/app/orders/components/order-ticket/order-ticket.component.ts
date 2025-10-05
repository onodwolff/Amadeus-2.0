import { CommonModule } from '@angular/common';
import { Component, EventEmitter, OnInit, Output, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, finalize, forkJoin, of } from 'rxjs';
import { OrdersApi } from '../../../api/clients/orders.api';
import { PortfolioApi } from '../../../api/clients/portfolio.api';
import { RiskApi } from '../../../api/clients/risk.api';
import {
  Balance,
  CreateOrderPayload,
  OrderResponse,
  OrderSummary,
  Position,
  RiskExposure,
  RiskLimit,
} from '../../../api/models';
import { NotificationService } from '../../../shared/notifications/notification.service';

interface OrderTypeOption {
  label: string;
  value: 'market' | 'limit' | 'stop';
}

@Component({
  standalone: true,
  selector: 'app-order-ticket',
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './order-ticket.component.html',
  styleUrls: ['./order-ticket.component.scss'],
})
export class OrderTicketComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly ordersApi = inject(OrdersApi);
  private readonly portfolioApi = inject(PortfolioApi);
  private readonly riskApi = inject(RiskApi);
  private readonly notifications = inject(NotificationService);

  @Output() readonly orderCreated = new EventEmitter<OrderSummary>();

  readonly form = this.fb.nonNullable.group({
    symbol: ['', [Validators.required, Validators.maxLength(32)]],
    venue: ['', [Validators.required, Validators.maxLength(32)]],
    side: ['buy', Validators.required],
    type: ['market' as OrderTypeOption['value'], Validators.required],
    quantity: [1, [Validators.required, Validators.min(0.0001)]],
    price: [null as number | null],
    time_in_force: ['GTC'],
    node_id: [''],
    client_order_id: [''],
  });

  readonly orderTypes: OrderTypeOption[] = [
    { label: 'Market', value: 'market' },
    { label: 'Limit', value: 'limit' },
    { label: 'Stop', value: 'stop' },
  ];

  readonly tifOptions: { label: string; value: string }[] = [
    { label: 'Good till cancel (GTC)', value: 'GTC' },
    { label: 'Immediate or cancel (IOC)', value: 'IOC' },
    { label: 'Fill or kill (FOK)', value: 'FOK' },
  ];

  readonly balances = signal<Balance[]>([]);
  readonly positions = signal<Position[]>([]);
  readonly riskLimits = signal<RiskLimit[]>([]);
  readonly riskExposures = signal<RiskExposure[]>([]);
  readonly isLoading = signal(true);
  readonly isSubmitting = signal(false);
  readonly formErrors = signal<string[]>([]);

  readonly selectedType = computed(() => this.form.controls.type.value);

  ngOnInit(): void {
    this.bootstrapData();
    this.form.controls.type.valueChanges
      .pipe(takeUntilDestroyed())
      .subscribe(() => {
        if (this.selectedType() === 'market') {
          this.form.controls.price.setValue(null);
        }
      });
  }

  private bootstrapData(): void {
    forkJoin({
      portfolio: this.portfolioApi.getPortfolio(),
      risk: this.riskApi.getRisk().pipe(catchError(() => of(null))),
    })
      .pipe(
        takeUntilDestroyed(),
        finalize(() => this.isLoading.set(false)),
      )
      .subscribe({
        next: (payload) => {
          const portfolio = payload.portfolio?.portfolio;
          if (portfolio) {
            this.balances.set(portfolio.balances ?? []);
            this.positions.set(portfolio.positions ?? []);
            if (portfolio.positions?.length) {
              const first = portfolio.positions[0];
              this.form.patchValue({ symbol: first.symbol, venue: first.venue });
            }
          }

          if (payload.risk?.risk) {
            this.riskLimits.set(payload.risk.risk.exposure_limits ?? []);
            this.riskExposures.set(payload.risk.risk.exposures ?? []);
          }
        },
        error: (err) => {
          console.error('Failed to load ticket context', err);
          this.notifications.error('Unable to load portfolio or risk context.');
        },
      });
  }

  onSubmit(): void {
    this.form.markAllAsTouched();
    const errors = this.validateOrder();
    this.formErrors.set(errors);
    if (errors.length > 0) {
      return;
    }

    const payload = this.buildPayload();
    if (!payload) {
      return;
    }

    this.isSubmitting.set(true);
    this.ordersApi
      .createOrder(payload)
      .pipe(
        takeUntilDestroyed(),
        finalize(() => this.isSubmitting.set(false)),
      )
      .subscribe({
        next: (response: OrderResponse) => {
          const order = response?.order;
          if (!order) {
            this.notifications.warning('Order API returned no order payload.', 'Orders gateway');
            return;
          }
          this.notifications.success(
            `${order.type.toUpperCase()} ${order.side.toUpperCase()} order submitted`,
            'Order accepted',
          );
          this.orderCreated.emit(order);
          this.formErrors.set([]);
          this.afterSubmitReset(order.type);
        },
        error: (err) => {
          console.error('Order submission failed', err);
          this.notifications.error('Failed to submit order. Please review gateway logs.');
        },
      });
  }

  private buildPayload(): CreateOrderPayload | null {
    const raw = this.form.getRawValue();
    const symbol = (raw.symbol ?? '').trim().toUpperCase();
    const venue = (raw.venue ?? '').trim().toUpperCase();
    const side = (raw.side ?? 'buy').toLowerCase();
    const type = (raw.type ?? 'market').toLowerCase() as 'market' | 'limit' | 'stop';
    const quantity = Number(raw.quantity);
    const priceValue = raw.price != null ? Number(raw.price) : null;
    const price = priceValue != null && !Number.isNaN(priceValue) ? priceValue : null;
    const tif = (raw.time_in_force ?? '').trim().toUpperCase();
    const nodeId = (raw.node_id ?? '').trim();
    const clientOrderId = (raw.client_order_id ?? '').trim();

    if (!symbol || !venue || Number.isNaN(quantity)) {
      return null;
    }

    const payload: CreateOrderPayload = {
      symbol,
      venue,
      side,
      type,
      quantity,
    };

    if (price != null && price > 0) {
      payload.price = price;
    }
    if (tif) {
      payload.time_in_force = tif;
    }
    if (nodeId) {
      payload.node_id = nodeId;
    }
    if (clientOrderId) {
      payload.client_order_id = clientOrderId;
    }

    return payload;
  }

  private afterSubmitReset(orderType: string): void {
    const defaults = {
      quantity: 1,
      client_order_id: '',
    };
    this.form.patchValue({ ...defaults, price: orderType === 'market' ? null : this.form.controls.price.value });
  }

  private validateOrder(): string[] {
    const errors: string[] = [];
    const value = this.form.getRawValue();

    const symbol = (value.symbol ?? '').trim();
    const venue = (value.venue ?? '').trim();
    const side = (value.side ?? 'buy').toLowerCase();
    const type = (value.type ?? 'market').toLowerCase();
    const quantity = Number(value.quantity);
    const price = value.price != null ? Number(value.price) : null;

    if (!symbol) {
      errors.push('Symbol is required.');
    }
    if (!venue) {
      errors.push('Venue is required.');
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      errors.push('Quantity must be greater than zero.');
    }
    if ((type === 'limit' || type === 'stop') && (!price || price <= 0)) {
      errors.push('Price is required for limit and stop orders.');
    }

    if (errors.length) {
      return errors;
    }

    const normalizedSymbol = symbol.toUpperCase();
    const normalizedVenue = venue.toUpperCase();
    const notional = this.estimateNotional(quantity, price, normalizedSymbol, normalizedVenue);

    if (side === 'sell') {
      const positionQty = this.availablePositionQuantity(normalizedSymbol, normalizedVenue);
      if (quantity > positionQty + 1e-8) {
        errors.push(`Sell quantity exceeds available position (${positionQty.toFixed(4)}).`);
      }
    } else if (side === 'buy' && notional != null) {
      const quoteCurrency = this.guessQuoteCurrency(normalizedSymbol);
      const availableFunds = this.availableFunds(quoteCurrency);
      if (availableFunds != null && notional > availableFunds + 1e-8) {
        errors.push(
          `Notional ${notional.toFixed(2)} exceeds available ${quoteCurrency} balance (${availableFunds.toFixed(2)}).`,
        );
      }
    }

    const quantityLimit = this.findRiskLimit('Max order quantity');
    if (quantityLimit != null && quantity > quantityLimit) {
      errors.push(`Quantity breaches risk limit (${quantityLimit}).`);
    }

    const notionalLimit = this.findRiskLimit('Max order notional');
    if (notionalLimit != null && notional != null && notional > notionalLimit) {
      errors.push(`Notional breaches risk limit (${notionalLimit.toFixed(2)}).`);
    }

    return errors;
  }

  private estimateNotional(
    quantity: number,
    price: number | null,
    symbol: string,
    venue: string,
  ): number | null {
    if (price != null && price > 0) {
      return quantity * price;
    }

    const position = this.positions().find(
      (pos) => pos.symbol.toUpperCase() === symbol && pos.venue.toUpperCase() === venue,
    );
    const referencePrice = position?.mark_price ?? position?.average_price;
    if (referencePrice && referencePrice > 0) {
      return quantity * referencePrice;
    }

    const exposure = this.riskExposures().find(
      (item) => item.symbol.toUpperCase() === symbol && item.venue.toUpperCase() === venue,
    );
    if (exposure?.notional_value && position?.quantity) {
      const unitPrice = Math.abs(exposure.notional_value / (position.quantity || 1));
      if (Number.isFinite(unitPrice) && unitPrice > 0) {
        return quantity * unitPrice;
      }
    }

    return null;
  }

  private availableFunds(currency: string): number | null {
    if (!currency) {
      return null;
    }
    const total = this.balances()
      .filter((balance) => balance.currency?.toUpperCase() === currency)
      .reduce((acc, balance) => acc + (balance.available ?? balance.total ?? 0), 0);
    return total > 0 ? total : null;
  }

  private availablePositionQuantity(symbol: string, venue: string): number {
    return this.positions()
      .filter((position) => position.symbol.toUpperCase() === symbol && position.venue.toUpperCase() === venue)
      .reduce((acc, position) => acc + Math.max(0, position.quantity), 0);
  }

  private findRiskLimit(name: string): number | null {
    const target = this.riskLimits().find((limit) => limit.name?.toLowerCase() === name.toLowerCase());
    if (!target?.limit || target.limit <= 0) {
      return null;
    }
    return target.limit;
  }

  private guessQuoteCurrency(symbol: string): string {
    const upper = symbol.toUpperCase();
    if (upper.includes('/')) {
      return upper.split('/')[1] ?? 'USD';
    }
    if (upper.endsWith('USDT')) {
      return 'USDT';
    }
    if (upper.endsWith('USD')) {
      return 'USD';
    }
    if (upper.includes('.X')) {
      return 'USD';
    }
    if (upper.length >= 6) {
      return upper.slice(-3);
    }
    return 'USD';
  }

  readonly currentQuoteCurrency = computed(() => this.guessQuoteCurrency(this.form.controls.symbol.value));

  readonly estimatedNotional = computed(() => {
    const raw = this.form.getRawValue();
    const quantity = Number(raw.quantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return null;
    }
    const price = raw.price != null ? Number(raw.price) : null;
    const symbol = (raw.symbol ?? '').trim().toUpperCase();
    const venue = (raw.venue ?? '').trim().toUpperCase();
    if (!symbol || !venue) {
      return null;
    }
    return this.estimateNotional(quantity, price, symbol, venue);
  });

  readonly availableBalance = computed(() => {
    const currency = this.currentQuoteCurrency();
    if (!currency) {
      return null;
    }
    return this.availableFunds(currency.toUpperCase());
  });

  readonly sellableQuantity = computed(() => {
    const raw = this.form.getRawValue();
    const symbol = (raw.symbol ?? '').trim().toUpperCase();
    const venue = (raw.venue ?? '').trim().toUpperCase();
    if (!symbol || !venue) {
      return 0;
    }
    return this.availablePositionQuantity(symbol, venue);
  });
}
