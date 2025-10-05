import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { MarketSelectionStore } from '../../market-selection.store';
import { InstrumentType } from '../../../api/models';

@Component({
  standalone: true,
  selector: 'app-instrument-filters',
  imports: [CommonModule],
  templateUrl: './instrument-filters.component.html',
  styleUrls: ['./instrument-filters.component.scss'],
})
export class InstrumentFiltersComponent {
  private readonly store = inject(MarketSelectionStore);

  readonly searchTerm = this.store.searchTerm;
  readonly typeFilter = this.store.typeFilter;
  readonly instrumentTypes = computed(() => ['all', ...this.store.instrumentTypes()] as Array<InstrumentType | 'all'>);

  onSearch(event: Event): void {
    const target = event.target as HTMLInputElement;
    this.store.setSearchTerm(target.value);
  }

  onTypeChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    const value = target.value as InstrumentType | 'all';
    this.store.setTypeFilter(value === 'all' ? 'all' : value);
  }
}
