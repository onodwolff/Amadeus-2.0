import { Injectable, computed, inject, signal } from '@angular/core';
import { Instrument, InstrumentType } from '../api/models';
import { MarketApi } from '../api/clients/market.api';
import { take } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class MarketSelectionStore {
  private readonly marketApi = inject(MarketApi);

  readonly instruments = signal<Instrument[]>([]);
  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly selectedVenue = signal<string | null>(null);
  readonly searchTerm = signal('');
  readonly typeFilter = signal<InstrumentType | 'all'>('all');
  readonly selectedInstrumentId = signal<string | null>(null);

  readonly venues = computed(() => {
    const items = this.instruments();
    const venues = Array.from(new Set(items.map((instrument) => instrument.venue)));
    venues.sort((a, b) => a.localeCompare(b));
    return venues;
  });

  readonly instrumentTypes = computed(() => {
    const items = this.instruments();
    const types = Array.from(new Set(items.map((instrument) => instrument.type)));
    types.sort((a, b) => a.localeCompare(b));
    return types;
  });

  readonly filteredInstruments = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const type = this.typeFilter();
    return this.instruments().filter((instrument) => {
      if (type !== 'all' && instrument.type !== type) {
        return false;
      }
      if (!term) {
        return true;
      }
      const haystack = [instrument.symbol, instrument.instrument_id, instrument.base_currency, instrument.quote_currency]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(term);
    });
  });

  readonly selectedInstrument = computed(() => {
    const id = this.selectedInstrumentId();
    if (!id) {
      return null;
    }
    return this.instruments().find((instrument) => instrument.instrument_id === id) ?? null;
  });

  readonly instrumentLookup = computed(() => {
    const map = new Map<string, Instrument>();
    for (const instrument of this.instruments()) {
      map.set(instrument.instrument_id, instrument);
    }
    return map;
  });

  loadInstruments(venue?: string | null): void {
    this.isLoading.set(true);
    this.error.set(null);
    this.marketApi
      .listInstruments(venue ?? undefined)
      .pipe(take(1))
      .subscribe({
        next: (response) => {
          this.instruments.set(response.instruments);
          if (response.instruments.length === 0) {
            this.selectedInstrumentId.set(null);
          } else {
            const currentId = this.selectedInstrumentId();
            if (!currentId || !response.instruments.some((instrument) => instrument.instrument_id === currentId)) {
              this.selectedInstrumentId.set(response.instruments[0]?.instrument_id ?? null);
            }
          }
          this.isLoading.set(false);
        },
        error: (error) => {
          console.error(error);
          this.error.set('Failed to load instruments.');
          this.instruments.set([]);
          this.selectedInstrumentId.set(null);
          this.isLoading.set(false);
        },
      });
  }

  refresh(): void {
    this.loadInstruments(this.selectedVenue());
  }

  setSelectedVenue(venue: string | null): void {
    this.selectedVenue.set(venue);
    this.loadInstruments(venue);
  }

  setSearchTerm(term: string): void {
    this.searchTerm.set(term);
  }

  setTypeFilter(type: InstrumentType | 'all'): void {
    this.typeFilter.set(type);
  }

  selectInstrument(instrument: Instrument): void {
    this.selectedInstrumentId.set(instrument.instrument_id);
  }
}
