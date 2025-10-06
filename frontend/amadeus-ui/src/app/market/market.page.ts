import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { MarketSelectionStore } from './market-selection.store';
import { MarketWatchlistService } from './market-watchlist.service';
import { Instrument } from '../api/models';
import { VenueSelectorComponent } from './components/venue-selector/venue-selector.component';
import { InstrumentFiltersComponent } from './components/instrument-filters/instrument-filters.component';
import { WatchlistPanelComponent } from './components/watchlist-panel/watchlist-panel.component';
import {
  PriceChartComponent,
  PriceChartIndicator,
  PriceChartScale,
} from './components/price-chart/price-chart.component';
import { OrderBookComponent } from './components/order-book/order-book.component';
import { TradeTapeComponent } from './components/trade-tape/trade-tape.component';

@Component({
  standalone: true,
  selector: 'app-market-page',
  imports: [
    CommonModule,
    VenueSelectorComponent,
    InstrumentFiltersComponent,
    WatchlistPanelComponent,
    PriceChartComponent,
    OrderBookComponent,
    TradeTapeComponent,
  ],
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
  readonly usingInstrumentFallback = this.store.isUsingFallback;

  readonly timeframeOptions = [
    { value: '1m', label: '1m' },
    { value: '5m', label: '5m' },
    { value: '15m', label: '15m' },
    { value: '1h', label: '1H' },
    { value: '4h', label: '4H' },
    { value: '1d', label: '1D' },
  ];

  readonly indicatorOptions: { value: PriceChartIndicator; label: string }[] = [
    { value: 'none', label: 'None' },
    { value: 'sma', label: 'SMA (20)' },
    { value: 'ema', label: 'EMA (20)' },
  ];

  readonly scaleOptions: { value: PriceChartScale; label: string }[] = [
    { value: 'linear', label: 'Linear' },
    { value: 'log', label: 'Log' },
    { value: 'percent', label: 'Percent' },
  ];

  readonly selectedTimeframe = signal(this.timeframeOptions[3].value);
  readonly selectedIndicator = signal<PriceChartIndicator>('none');
  readonly selectedScale = signal<PriceChartScale>('linear');

  readonly watchlistIds = this.watchlist.watchlistIds;
  readonly isSyncing = this.watchlist.isSyncing;
  readonly syncError = this.watchlist.syncError;
  readonly usingLocalWatchlist = this.watchlist.isUsingLocal;

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

  setTimeframe(value: string): void {
    this.selectedTimeframe.set(value);
  }

  setIndicator(value: string): void {
    this.selectedIndicator.set(value as PriceChartIndicator);
  }

  setScale(value: string): void {
    this.selectedScale.set(value as PriceChartScale);
  }
}
