import { Component } from '@angular/core';
import { PagePlaceholderComponent } from '../shared/page-placeholder.component';
import { OrderSummary } from '../api/models';

@Component({
  standalone: true,
  selector: 'app-orders-page',
  imports: [PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="Orders & fills"
      description="This page will list live and historical orders, along with execution reports from Nautilus Trader nodes."
      hint="Integration with node-specific streams is planned in the next iteration."
    ></app-page-placeholder>
  `,
})
export class OrdersPage {
  readonly pendingOrders: OrderSummary[] = [];
}
