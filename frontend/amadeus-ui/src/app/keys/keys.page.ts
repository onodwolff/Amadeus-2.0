import { Component } from '@angular/core';
import { PagePlaceholderComponent } from '../shared/page-placeholder.component';

@Component({
  standalone: true,
  selector: 'app-keys-page',
  imports: [PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="API keys"
      description="Store and manage exchange credentials for Nautilus Trader adapters."
      hint="Credential storage UI will be migrated once the gateway exposes the keys endpoints."
    ></app-page-placeholder>
  `,
})
export class KeysPage {}
