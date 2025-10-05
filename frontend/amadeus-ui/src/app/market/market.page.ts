import { Component } from '@angular/core';
import { PagePlaceholderComponent } from '../shared/page-placeholder.component';
import { Instrument } from '../api/models';

@Component({
  standalone: true,
  selector: 'app-market-page',
  imports: [PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="Market overview"
      description="The market dashboard will display price charts, order books and trade feeds for the selected venue."
      hint="This view is under construction as we adapt the Amadeus 1.0 market components."
    ></app-page-placeholder>
  `,
})
export class MarketPage {
  readonly instruments: Instrument[] = [];
}
