import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { MarketSelectionStore } from '../../market-selection.store';

@Component({
  standalone: true,
  selector: 'app-venue-selector',
  imports: [CommonModule],
  templateUrl: './venue-selector.component.html',
  styleUrls: ['./venue-selector.component.scss'],
})
export class VenueSelectorComponent {
  private readonly store = inject(MarketSelectionStore);

  readonly venues = this.store.venues;
  readonly selectedVenue = this.store.selectedVenue;

  onVenueChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    const value = target.value || null;
    this.store.setSelectedVenue(value);
  }

  refresh(): void {
    this.store.refresh();
  }
}
