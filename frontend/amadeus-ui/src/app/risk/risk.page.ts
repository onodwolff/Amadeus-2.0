import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  standalone: true,
  selector: 'app-risk-page',
  imports: [CommonModule],
  template: `
    <section class="page-placeholder">
      <h1>Risk controls</h1>
      <p>The risk management console will expose trading locks and limit configuration similar to Amadeus 1.0.</p>
      <p class="hint">Implementation pending integration with the gateway risk API.</p>
    </section>
  `,
  styles: [`
    .page-placeholder { display: grid; gap: 12px; padding: 24px; border-radius: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.16); }
    h1 { margin: 0; font-size: 1.75rem; }
    .hint { color: rgba(148, 163, 184, 0.9); font-style: italic; }
  `],
})
export class RiskPage {}
