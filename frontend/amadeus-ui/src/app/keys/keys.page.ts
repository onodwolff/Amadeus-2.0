import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  standalone: true,
  selector: 'app-keys-page',
  imports: [CommonModule],
  template: `
    <section class="page-placeholder">
      <h1>API keys</h1>
      <p>Store and manage exchange credentials for Nautilus Trader adapters.</p>
      <p class="hint">Credential storage UI will be migrated once the gateway exposes the keys endpoints.</p>
    </section>
  `,
  styles: [`
    .page-placeholder { display: grid; gap: 12px; padding: 24px; border-radius: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.16); }
    h1 { margin: 0; font-size: 1.75rem; }
    .hint { color: rgba(148, 163, 184, 0.9); font-style: italic; }
  `],
})
export class KeysPage {}
