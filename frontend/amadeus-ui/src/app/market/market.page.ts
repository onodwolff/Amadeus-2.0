import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject } from '@angular/core';
import { MarketSelectionStore } from './market-selection.store';
import { MarketWatchlistService } from './market-watchlist.service';
import { Instrument } from '../api/models';
import { VenueSelectorComponent } from './components/venue-selector/venue-selector.component';
import { InstrumentFiltersComponent } from './components/instrument-filters/instrument-filters.component';
import { WatchlistPanelComponent } from './components/watchlist-panel/watchlist-panel.component';

@Component({
  standalone: true,
  selector: 'app-market-page',
  imports: [CommonModule, VenueSelectorComponent, InstrumentFiltersComponent, WatchlistPanelComponent],
  templateUrl: './market.page.html',
  styleUrls: ['./market.page.scss'],
})
export class MarketPage implements OnInit {
  protected readonly store = inject(MarketSelectionStore);
  protected readonly watchlist = inject(MarketWatchlistService);

  readonly filteredInstruments = this.store.filteredInstruments;
  readonly allInstruments = this.store.instruments;
  readonly selectedInstrument = this.store.selectedInstrument;
  readonly isLoading = this.store.isLoading;
  readonly loadError = this.store.error;

  readonly watchlistIds = this.watchlist.watchlistIds;
  readonly isSyncing = this.watchlist.isSyncing;
  readonly syncError = this.watchlist.syncError;

  readonly hasInstruments = computed(() => this.allInstruments().length > 0);
  readonly hasFilteredResults = computed(() => this.filteredInstruments().length > 0);

  ngOnInit(): void {
    this.watchlist.initialize();
    this.store.loadInstruments();
  }

  onSelectInstrument(instrument: Instrument): void {
    this.store.selectInstrument(instrument);
  }

  onToggleWatchlist(instrument: Instrument, event: Event): void {
    event.stopPropagation();
    this.watchlist.toggleInstrument(instrument.instrument_id);
  }

  isInstrumentInWatchlist(instrument: Instrument): boolean {
    return this.watchlistIds().includes(instrument.instrument_id);
  }
}
