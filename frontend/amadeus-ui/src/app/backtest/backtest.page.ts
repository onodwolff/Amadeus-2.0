import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  standalone: true,
  selector: 'app-backtest-page',
  imports: [CommonModule],
  template: `
    <section class="page-placeholder">
      <h1>Backtests</h1>
      <p>Configure and launch historical simulations. The detailed configuration form from Amadeus 1.0 will be ported in a dedicated task.</p>
      <p class="hint">For now, use the controls on the Nodes page to launch a default backtest node.</p>
    </section>
  `,
  styles: [`
    .page-placeholder { display: grid; gap: 12px; padding: 24px; border-radius: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.16); }
    h1 { margin: 0; font-size: 1.75rem; }
    .hint { color: rgba(148, 163, 184, 0.9); font-style: italic; }
  `],
})
export class BacktestPage {}
