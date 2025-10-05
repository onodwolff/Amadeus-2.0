import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  standalone: true,
  selector: 'app-market-page',
  imports: [CommonModule],
  template: `
    <section class="page-placeholder">
      <h1>Market overview</h1>
      <p>The market dashboard will display price charts, order books and trade feeds for the selected venue.</p>
      <p class="hint">This view is under construction as we adapt the Amadeus 1.0 market components.</p>
    </section>
  `,
  styles: [`
    .page-placeholder { display: grid; gap: 12px; padding: 24px; border-radius: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.16); }
    h1 { margin: 0; font-size: 1.75rem; }
    .hint { color: rgba(148, 163, 184, 0.9); font-style: italic; }
  `],
})
export class MarketPage {}
