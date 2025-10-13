import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { OrdersApi } from '../api/clients/orders.api';
import {
  ExecutionReport,
  ModifyOrderPayload,
  OrderSummary,
  OrdersStreamMessage,
} from '../api/models';
import { observeOrdersStream } from '../ws';
import { WsConnectionState, WsService } from '../ws.service';
import { OrderTicketComponent } from './components/order-ticket/order-ticket.component';
import { AuthStateService } from '../shared/auth/auth-state.service';

@Component({
  standalone: true,
  selector: 'app-orders-page',
  imports: [CommonModule, FormsModule, OrderTicketComponent],
  templateUrl: './orders.page.html',
  styleUrls: ['./orders.page.scss'],
})
export class OrdersPage implements OnInit {
  private readonly ordersApi = inject(OrdersApi);
  private readonly ws = inject(WsService);
  protected readonly authState = inject(AuthStateService);

  readonly isLoading = signal(true);
  readonly errorText = signal<string | null>(null);
  readonly orders = signal<OrderSummary[]>([]);
  readonly executions = signal<ExecutionReport[]>([]);
  readonly wsState = signal<WsConnectionState>('connecting');

  readonly statusFilter = signal('all');
  readonly venueFilter = signal('all');
  readonly symbolFilter = signal('all');
  readonly nodeFilter = signal('all');

  readonly cancellingOrders = signal<Set<string>>(new Set());
  readonly duplicatingOrders = signal<Set<string>>(new Set());
  readonly modifyingOrders = signal<Set<string>>(new Set());

  private readonly supportedTifs = ['GTC', 'IOC', 'FOK', 'DAY', 'GTD'];

  ngOnInit(): void {
    this.loadInitial();
    this.observeOrdersStream();
  }

  private loadInitial(): void {
    this.isLoading.set(true);
    this.errorText.set(null);
    this.ordersApi.listOrders().subscribe({
      next: (response) => {
        const orders = Array.isArray(response?.orders) ? response.orders : [];
        const executions = Array.isArray(response?.executions) ? response.executions ?? [] : [];
        this.orders.set(orders);
        this.executions.set(executions);
        this.isLoading.set(false);
      },
      error: (err) => {
        console.error('Failed to load orders', err);
        this.errorText.set('Failed to load orders.');
        this.isLoading.set(false);
      },
    });
  }

  private observeOrdersStream(): void {
    const { data$, state$ } = observeOrdersStream(this.ws);

    state$.pipe(takeUntilDestroyed()).subscribe((state) => this.wsState.set(state));

    data$.pipe(takeUntilDestroyed()).subscribe({
      next: (payload: OrdersStreamMessage) => {
        if (Array.isArray(payload?.orders)) {
          this.orders.set(payload.orders);
        }
        if (Array.isArray(payload?.executions)) {
          this.executions.set(payload.executions);
        }
      },
      error: (err) => console.error('Orders stream error', err),
    });
  }

  readonly statusOptions = computed(() => {
    const statuses = new Set<string>();
    for (const order of this.orders()) {
      if (order.status) {
        statuses.add(order.status);
      }
    }
    return ['all', ...Array.from(statuses).sort()];
  });

  readonly venueOptions = computed(() => this.collectOptions('venue'));
  readonly symbolOptions = computed(() => this.collectOptions('symbol'));
  readonly nodeOptions = computed(() => this.collectOptions('node_id'));

  private collectOptions(key: keyof OrderSummary): string[] {
    const values = new Set<string>();
    for (const order of this.orders()) {
      const value = order[key];
      if (typeof value === 'string' && value.trim().length > 0) {
        values.add(value);
      }
    }
    return ['all', ...Array.from(values).sort((a, b) => a.localeCompare(b))];
  }

  readonly filteredOrders = computed(() => {
    const status = this.statusFilter();
    const venue = this.venueFilter();
    const symbol = this.symbolFilter();
    const node = this.nodeFilter();

    return this.orders()
      .filter((order) => {
        if (status !== 'all' && order.status !== status) {
          return false;
        }
        if (venue !== 'all' && order.venue !== venue) {
          return false;
        }
        if (symbol !== 'all' && order.symbol !== symbol) {
          return false;
        }
        if (node !== 'all' && order.node_id !== node) {
          return false;
        }
        return true;
      })
      .sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
  });

  readonly openOrdersCount = computed(
    () =>
      this.filteredOrders().filter(
        (order) => order.status === 'pending' || order.status === 'working',
      ).length,
  );

  readonly completedOrdersCount = computed(
    () =>
      this.filteredOrders().filter((order) => order.status === 'filled' || order.status === 'cancelled')
        .length,
  );

  readonly rejectedOrdersCount = computed(
    () => this.filteredOrders().filter((order) => order.status === 'rejected').length,
  );

  readonly executionsByOrder = computed(() => {
    const map = new Map<string, ExecutionReport[]>();
    for (const execution of this.executions()) {
      if (!execution?.order_id) {
        continue;
      }
      const list = map.get(execution.order_id) ?? [];
      list.push(execution);
      map.set(execution.order_id, list);
    }
    for (const [, list] of map) {
      list.sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : 0));
    }
    return map;
  });

  readonly lastUpdated = computed(() => {
    const source = this.orders();
    let latest: string | null = null;
    for (const order of source) {
      const updated = order.updated_at || order.created_at;
      if (!updated) {
        continue;
      }
      if (latest === null || updated > latest) {
        latest = updated;
      }
    }
    return latest;
  });

  trackByOrderId(_index: number, order: OrderSummary): string {
    return order.order_id;
  }

  orderExecutions(orderId: string): ExecutionReport[] {
    return this.executionsByOrder().get(orderId) ?? [];
  }

  onStatusFilterChange(value: string): void {
    this.statusFilter.set(value || 'all');
  }

  onVenueFilterChange(value: string): void {
    this.venueFilter.set(value || 'all');
  }

  onSymbolFilterChange(value: string): void {
    this.symbolFilter.set(value || 'all');
  }

  onNodeFilterChange(value: string): void {
    this.nodeFilter.set(value || 'all');
  }

  onOrderCreated(order: OrderSummary): void {
    this.upsertOrder(order);
  }

  isOrderModifiable(order: OrderSummary): boolean {
    const status = (order.status ?? '').toLowerCase();
    return ['pending', 'working', 'pending_modify'].includes(status);
  }

  isOrderCancellable(order: OrderSummary): boolean {
    return order.status === 'pending' || order.status === 'working';
  }

  isCancelling(orderId: string): boolean {
    return this.cancellingOrders().has(orderId);
  }

  isDuplicating(orderId: string): boolean {
    return this.duplicatingOrders().has(orderId);
  }

  isModifying(orderId: string): boolean {
    return this.modifyingOrders().has(orderId);
  }

  onCancel(order: OrderSummary, event: Event): void {
    event.stopPropagation();
    if (!this.isOrderCancellable(order)) {
      return;
    }
    if (!window.confirm(`Cancel order ${order.order_id}?`)) {
      return;
    }

    this.errorText.set(null);
    this.markCancelling(order.order_id, true);
    this.ordersApi.cancelOrder(order.order_id).subscribe({
      next: (response) => {
        if (response?.order) {
          this.upsertOrder(response.order);
        }
      },
      error: (err) => {
        console.error('Failed to cancel order', err);
        this.errorText.set(`Failed to cancel order ${order.order_id}.`);
      },
      complete: () => {
        this.markCancelling(order.order_id, false);
      },
    });
  }

  onDuplicate(order: OrderSummary, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Duplicate order ${order.order_id}?`)) {
      return;
    }

    this.errorText.set(null);
    this.markDuplicating(order.order_id, true);
    this.ordersApi.duplicateOrder(order.order_id).subscribe({
      next: (response) => {
        if (response?.order) {
          this.upsertOrder(response.order);
        }
      },
      error: (err) => {
        console.error('Failed to duplicate order', err);
        this.errorText.set(`Failed to duplicate order ${order.order_id}.`);
      },
      complete: () => {
        this.markDuplicating(order.order_id, false);
      },
    });
  }

  onModify(order: OrderSummary, event: Event): void {
    event.stopPropagation();
    if (!this.isOrderModifiable(order)) {
      return;
    }

    const payload = this.promptModifyPayload(order);
    if (!payload) {
      return;
    }

    this.errorText.set(null);
    this.markModifying(order.order_id, true);
    this.ordersApi.modifyOrder(order.order_id, payload).subscribe({
      next: (response) => {
        if (response?.order) {
          this.upsertOrder(response.order);
        }
      },
      error: (err) => {
        console.error('Failed to modify order', err);
        this.errorText.set(`Failed to modify order ${order.order_id}.`);
        this.markModifying(order.order_id, false);
      },
      complete: () => {
        this.markModifying(order.order_id, false);
      },
    });
  }

  private markCancelling(orderId: string, active: boolean): void {
    this.cancellingOrders.update((current) => {
      const next = new Set(current);
      if (active) {
        next.add(orderId);
      } else {
        next.delete(orderId);
      }
      return next;
    });
  }

  private markDuplicating(orderId: string, active: boolean): void {
    this.duplicatingOrders.update((current) => {
      const next = new Set(current);
      if (active) {
        next.add(orderId);
      } else {
        next.delete(orderId);
      }
      return next;
    });
  }

  private markModifying(orderId: string, active: boolean): void {
    this.modifyingOrders.update((current) => {
      const next = new Set(current);
      if (active) {
        next.add(orderId);
      } else {
        next.delete(orderId);
      }
      return next;
    });
  }

  private promptModifyPayload(order: OrderSummary): ModifyOrderPayload | null {
    const payload: ModifyOrderPayload = {};
    let changed = false;

    const quantityResponse = window.prompt(
      `Enter new quantity for ${order.order_id} (current ${order.quantity}). Leave blank to keep current value.`,
      '',
    );
    if (quantityResponse === null) {
      return null;
    }
    const quantityText = quantityResponse.trim();
    if (quantityText.length > 0) {
      const quantityValue = Number(quantityText);
      if (!Number.isFinite(quantityValue) || quantityValue <= 0) {
        window.alert('Quantity must be a positive number.');
        return null;
      }
      const filledQuantity = Number(order.filled_quantity ?? 0);
      if (quantityValue < filledQuantity - 1e-9) {
        window.alert('Quantity cannot be less than the filled amount.');
        return null;
      }
      payload.quantity = quantityValue;
      changed = true;
    }

    if ((order.type ?? '').toLowerCase() !== 'market') {
      const priceResponse = window.prompt(
        `Enter new price for ${order.order_id} (current ${order.price ?? '—'}). Leave blank to keep current value.`,
        '',
      );
      if (priceResponse === null) {
        return null;
      }
      const priceText = priceResponse.trim();
      if (priceText.length > 0) {
        const priceValue = Number(priceText);
        if (!Number.isFinite(priceValue) || priceValue <= 0) {
          window.alert('Price must be a positive number.');
          return null;
        }
        payload.price = priceValue;
        changed = true;
      }
    }

    if ((order.type ?? '').toLowerCase() === 'stop_limit') {
      const offsetResponse = window.prompt(
        `Enter new limit offset (current ${order.limit_offset ?? '—'}). Leave blank to keep, type CLEAR to remove.`,
        '',
      );
      if (offsetResponse === null) {
        return null;
      }
      const offsetText = offsetResponse.trim();
      if (offsetText.length > 0) {
        if (offsetText.toLowerCase() === 'clear') {
          payload.limit_offset = null;
          changed = true;
        } else {
          const offsetValue = Number(offsetText);
          if (!Number.isFinite(offsetValue)) {
            window.alert('Limit offset must be a number.');
            return null;
          }
          payload.limit_offset = offsetValue;
          changed = true;
        }
      }
    }

    const tifResponse = window.prompt(
      `Enter new time in force (${this.supportedTifs.join(', ')}) for ${order.order_id}. Current: ${
        order.time_in_force || 'GTC'
      }. Leave blank to keep current value.`,
      '',
    );
    if (tifResponse === null) {
      return null;
    }
    const tifText = tifResponse.trim().toUpperCase();
    if (tifText.length > 0) {
      if (!this.supportedTifs.includes(tifText)) {
        window.alert('Unsupported time in force.');
        return null;
      }
      payload.time_in_force = tifText;
      changed = true;
    }

    const effectiveTif = (payload.time_in_force ?? order.time_in_force ?? '').toUpperCase();
    if (effectiveTif === 'GTD') {
      const expireResponse = window.prompt(
        `Enter new expire time (ISO format) for ${order.order_id}. Current: ${order.expire_time ?? '—'}.
Leave blank to keep current value or type CLEAR to remove.`,
        '',
      );
      if (expireResponse === null) {
        return null;
      }
      const expireText = expireResponse.trim();
      if (expireText.length > 0) {
        if (expireText.toLowerCase() === 'clear') {
          payload.expire_time = null;
          changed = true;
        } else {
          const parsed = new Date(expireText);
          if (!Number.isNaN(parsed.getTime())) {
            payload.expire_time = parsed.toISOString();
          } else {
            payload.expire_time = expireText;
          }
          changed = true;
        }
      }
    } else if (
      payload.time_in_force &&
      payload.time_in_force !== 'GTD' &&
      (order.time_in_force ?? '').toUpperCase() === 'GTD' &&
      payload.expire_time === undefined
    ) {
      payload.expire_time = null;
      changed = true;
    }

    const postOnlyResponse = window.prompt(
      `Post-only flag for ${order.order_id} (current: ${order.post_only ? 'enabled' : 'disabled'}).
Enter YES, NO, CLEAR, or leave blank to keep current value.`,
      '',
    );
    if (postOnlyResponse === null) {
      return null;
    }
    const postOnlyText = postOnlyResponse.trim().toLowerCase();
    if (postOnlyText.length > 0) {
      if (['yes', 'y', 'true'].includes(postOnlyText)) {
        payload.post_only = true;
        changed = true;
      } else if (['no', 'n', 'false'].includes(postOnlyText)) {
        payload.post_only = false;
        changed = true;
      } else if (postOnlyText === 'clear') {
        payload.post_only = null;
        changed = true;
      } else {
        window.alert('Unrecognised response for post-only flag.');
        return null;
      }
    }

    const reduceOnlyResponse = window.prompt(
      `Reduce-only flag for ${order.order_id} (current: ${order.reduce_only ? 'enabled' : 'disabled'}).
Enter YES, NO, CLEAR, or leave blank to keep current value.`,
      '',
    );
    if (reduceOnlyResponse === null) {
      return null;
    }
    const reduceOnlyText = reduceOnlyResponse.trim().toLowerCase();
    if (reduceOnlyText.length > 0) {
      if (['yes', 'y', 'true'].includes(reduceOnlyText)) {
        payload.reduce_only = true;
        changed = true;
      } else if (['no', 'n', 'false'].includes(reduceOnlyText)) {
        payload.reduce_only = false;
        changed = true;
      } else if (reduceOnlyText === 'clear') {
        payload.reduce_only = null;
        changed = true;
      } else {
        window.alert('Unrecognised response for reduce-only flag.');
        return null;
      }
    }

    if (!changed) {
      window.alert('No changes provided for the order.');
      return null;
    }

    return payload;
  }

  private upsertOrder(order: OrderSummary): void {
    this.orders.update((current) => {
      const index = current.findIndex((existing) => existing.order_id === order.order_id);
      const next = [...current];
      if (index >= 0) {
        next[index] = order;
      } else {
        next.unshift(order);
      }
      return next.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
    });
  }
}
