import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  standalone: true,
  selector: 'app-orders-page',
  imports: [CommonModule],
  template: `
    <section class="page-placeholder">
      <h1>Orders & fills</h1>
      <p>This page will list live and historical orders, along with execution reports from Nautilus Trader nodes.</p>
      <p class="hint">Integration with node-specific streams is planned in the next iteration.</p>
    </section>
  `,
  styles: [`
    .page-placeholder { display: grid; gap: 12px; padding: 24px; border-radius: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.16); }
    h1 { margin: 0; font-size: 1.75rem; }
    .hint { color: rgba(148, 163, 184, 0.9); font-style: italic; }
  `],
})
export class OrdersPage {}
