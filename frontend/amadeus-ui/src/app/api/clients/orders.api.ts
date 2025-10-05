import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { CreateOrderPayload, OrderResponse, OrdersResponse } from '../models/order.model';

@Injectable({ providedIn: 'root' })
export class OrdersApi {
  private readonly http = inject(HttpClient);

  listOrders(): Observable<OrdersResponse> {
    return this.http.get<OrdersResponse>(buildApiUrl('/orders'));
  }

  createOrder(payload: CreateOrderPayload): Observable<OrderResponse> {
    return this.http.post<OrderResponse>(buildApiUrl('/orders'), payload);
  }

  getOrder(orderId: string): Observable<OrderResponse> {
    return this.http.get<OrderResponse>(buildApiUrl(`/orders/${orderId}`));
  }

  cancelOrder(orderId: string): Observable<OrderResponse> {
    return this.http.post<OrderResponse>(buildApiUrl(`/orders/${orderId}/cancel`), {});
  }

  duplicateOrder(orderId: string): Observable<OrderResponse> {
    return this.http.post<OrderResponse>(buildApiUrl(`/orders/${orderId}/duplicate`), {});
  }
}
