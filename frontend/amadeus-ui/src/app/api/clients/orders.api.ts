import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  CreateOrderPayload,
  ModifyOrderPayload,
  OrderResponse,
  OrdersResponse,
} from '../models/order.model';

@Injectable({ providedIn: 'root' })
export class OrdersApi {
  private readonly http = inject(HttpClient);

  listOrders(): Observable<OrdersResponse> {
    return this.http.get<OrdersResponse>(buildApiUrl('/api/orders'));
  }

  createOrder(payload: CreateOrderPayload): Observable<OrderResponse> {
    return this.http.post<OrderResponse>(buildApiUrl('/api/orders'), payload);
  }

  getOrder(orderId: string): Observable<OrderResponse> {
    return this.http.get<OrderResponse>(buildApiUrl(`/api/orders/${encodeURIComponent(orderId)}`));
  }

  cancelOrder(orderId: string): Observable<OrderResponse> {
    const path = `/api/orders/${encodeURIComponent(orderId)}/cancel`;
    return this.http.post<OrderResponse>(buildApiUrl(path), {});
  }

  modifyOrder(orderId: string, payload: ModifyOrderPayload): Observable<OrderResponse> {
    const path = `/api/orders/${encodeURIComponent(orderId)}/modify`;
    return this.http.post<OrderResponse>(buildApiUrl(path), payload);
  }

  duplicateOrder(orderId: string): Observable<OrderResponse> {
    const path = `/api/orders/${encodeURIComponent(orderId)}/duplicate`;
    return this.http.post<OrderResponse>(buildApiUrl(path), {});
  }
}
