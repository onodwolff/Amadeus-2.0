import { Injectable, computed, inject, signal } from '@angular/core';
import { Instrument, InstrumentType } from '../api/models';
import { MarketApi } from '../api/clients/market.api';
import { take } from 'rxjs';

const INSTRUMENT_CACHE_KEY = 'amadeus.market.instruments';

@Injectable({ providedIn: 'root' })
export class MarketSelectionStore {
  private readonly marketApi = inject(MarketApi);

  readonly instruments = signal<Instrument[]>(this.loadLocal());
  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly selectedVenue = signal<string | null>(null);
  readonly searchTerm = signal('');
  readonly typeFilter = signal<InstrumentType | 'all'>('all');
  readonly selectedInstrumentId = signal<string | null>(null);
  readonly usingLocalFallback = signal(false);

  constructor() {
    const cached = this.instruments();
    if (cached.length) {
      this.applySelection(cached);
    }
  }

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
    this.usingLocalFallback.set(false);
    this.marketApi
      .listInstruments(venue ?? undefined)
      .pipe(take(1))
      .subscribe({
        next: (response) => {
          const instruments = response.instruments ?? [];
          this.instruments.set(instruments);
          this.persistLocal(instruments);
          this.applySelection(instruments);
          this.isLoading.set(false);
          this.error.set(null);
        },
        error: (error) => {
          console.error(error);
          const fallback = this.loadLocal();
          if (fallback.length) {
            this.instruments.set(fallback);
            this.applySelection(fallback);
            this.error.set('Failed to load instruments from the server.');
            this.usingLocalFallback.set(true);
          } else {
            this.instruments.set([]);
            this.selectedInstrumentId.set(null);
            this.error.set('Failed to load instruments.');
            this.usingLocalFallback.set(false);
          }
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

  private applySelection(instruments: Instrument[]): void {
    if (instruments.length === 0) {
      this.selectedInstrumentId.set(null);
      return;
    }
    const currentId = this.selectedInstrumentId();
    if (currentId && instruments.some((instrument) => instrument.instrument_id === currentId)) {
      return;
    }
    this.selectedInstrumentId.set(instruments[0]?.instrument_id ?? null);
  }

  private loadLocal(): Instrument[] {
    try {
      const stored = localStorage.getItem(INSTRUMENT_CACHE_KEY);
      if (!stored) {
        return [];
      }
      const parsed = JSON.parse(stored);
      if (!Array.isArray(parsed)) {
        return [];
      }
      return parsed.filter((item: unknown): item is Instrument => {
        if (typeof item !== 'object' || item === null) {
          return false;
        }
        const candidate = item as Partial<Instrument>;
        return (
          typeof candidate.instrument_id === 'string' &&
          typeof candidate.symbol === 'string' &&
          typeof candidate.venue === 'string' &&
          typeof candidate.type === 'string'
        );
      });
    } catch (error) {
      console.warn('Failed to read instrument cache from localStorage', error);
      return [];
    }
  }

  private persistLocal(instruments: Instrument[]): void {
    try {
      localStorage.setItem(INSTRUMENT_CACHE_KEY, JSON.stringify(instruments));
    } catch (error) {
      console.warn('Failed to persist instrument cache to localStorage', error);
    }
  }
}
