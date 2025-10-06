import { Injectable, computed, inject, signal } from '@angular/core';
import { Instrument, InstrumentType } from '../api/models';
import { MarketApi } from '../api/clients/market.api';
import { take } from 'rxjs';

const CACHE_KEY = 'amadeus.market.instrument-cache';

@Injectable({ providedIn: 'root' })
export class MarketSelectionStore {
  private readonly marketApi = inject(MarketApi);

  readonly instruments = signal<Instrument[]>(this.loadCachedInstruments());
  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly isUsingFallback = signal(false);
  readonly selectedVenue = signal<string | null>(null);
  readonly searchTerm = signal('');
  readonly typeFilter = signal<InstrumentType | 'all'>('all');
  readonly selectedInstrumentId = signal<string | null>(null);

  private lastVenue: string | null = null;

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

  constructor() {
    const cached = this.instruments();
    if (cached.length > 0) {
      this.ensureSelection(cached);
    }
  }

  loadInstruments(venue?: string | null): void {
    this.isLoading.set(true);
    this.error.set(null);
    this.isUsingFallback.set(false);
    this.lastVenue = venue ?? null;
    this.marketApi
      .listInstruments(venue ?? undefined)
      .pipe(take(1))
      .subscribe({
        next: (response) => {
          const instruments = this.sanitiseInstruments(response.instruments ?? []);
          this.instruments.set(instruments);
          this.persistCachedInstruments(this.lastVenue, instruments);
          this.ensureSelection(instruments);
          this.isUsingFallback.set(false);
          this.isLoading.set(false);
        },
        error: (error) => {
          console.error(error);
          const cached = this.loadCachedInstruments(this.lastVenue);
          if (cached.length > 0) {
            this.instruments.set(cached);
            this.ensureSelection(cached);
            this.isUsingFallback.set(true);
            this.error.set('Unable to refresh instruments from the server. Showing cached data.');
          } else if (this.instruments().length > 0) {
            this.isUsingFallback.set(true);
            this.error.set('Unable to refresh instruments. Displaying the last known list.');
          } else {
            this.error.set('Failed to load instruments.');
            this.instruments.set([]);
            this.selectedInstrumentId.set(null);
            this.isUsingFallback.set(false);
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

  private ensureSelection(instruments: Instrument[]): void {
    if (instruments.length === 0) {
      this.selectedInstrumentId.set(null);
      return;
    }
    const currentId = this.selectedInstrumentId();
    if (!currentId || !instruments.some((instrument) => instrument.instrument_id === currentId)) {
      this.selectedInstrumentId.set(instruments[0]?.instrument_id ?? null);
    }
  }

  private sanitiseInstruments(items: Instrument[]): Instrument[] {
    return items.filter((instrument) => typeof instrument?.instrument_id === 'string');
  }

  private cacheKeyFor(venue?: string | null): string {
    return (venue ?? '__all__').toUpperCase();
  }

  private readCache(): Record<string, { instruments: Instrument[]; updated_at?: string }> {
    try {
      const stored = localStorage.getItem(CACHE_KEY);
      if (!stored) {
        return {};
      }
      const parsed = JSON.parse(stored);
      if (parsed && typeof parsed === 'object') {
        return parsed as Record<string, { instruments: Instrument[]; updated_at?: string }>;
      }
      return {};
    } catch (error) {
      console.warn('Failed to read instrument cache from localStorage', error);
      return {};
    }
  }

  private loadCachedInstruments(venue?: string | null): Instrument[] {
    try {
      const cache = this.readCache();
      const entry = cache[this.cacheKeyFor(venue)];
      if (!entry || !Array.isArray(entry.instruments)) {
        return [];
      }
      return this.sanitiseInstruments(entry.instruments);
    } catch (error) {
      console.warn('Failed to load cached instruments', error);
      return [];
    }
  }

  private persistCachedInstruments(venue: string | null, instruments: Instrument[]): void {
    try {
      const cache = this.readCache();
      cache[this.cacheKeyFor(venue)] = {
        instruments: instruments.map((instrument) => ({ ...instrument })),
        updated_at: new Date().toISOString(),
      };
      localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
    } catch (error) {
      console.warn('Failed to persist instrument cache to localStorage', error);
    }
  }
}
