import { Injectable, inject, signal } from '@angular/core';
import { MarketApi } from '../api/clients/market.api';
import { WatchlistRequest } from '../api/models';
import { take } from 'rxjs';

const STORAGE_KEY = 'amadeus.market.watchlist';

@Injectable({ providedIn: 'root' })
export class MarketWatchlistService {
  private readonly marketApi = inject(MarketApi);

  private readonly initialLocal = this.loadLocal();

  readonly watchlistIds = signal<string[]>([...this.initialLocal]);
  readonly isSyncing = signal(false);
  readonly syncError = signal<string | null>(null);
  readonly isUsingLocal = signal(this.initialLocal.length > 0);

  private isInitialized = false;

  initialize(): void {
    if (this.isInitialized) {
      return;
    }
    this.isInitialized = true;
    const local = this.loadLocal();
    if (local.length > 0) {
      this.watchlistIds.set(local);
      this.isUsingLocal.set(true);
    }

    this.isSyncing.set(true);
    this.marketApi
      .getWatchlist()
      .pipe(take(1))
      .subscribe({
        next: (response) => {
          const favorites = this.sanitiseIds(response?.favorites ?? []);
          this.watchlistIds.set(favorites);
          this.persistLocal(favorites);
          this.syncError.set(null);
          this.isUsingLocal.set(false);
          this.isSyncing.set(false);
        },
        error: (error) => {
          console.error(error);
          this.syncError.set('Unable to load favourites from the server. Using your local watchlist.');
          const fallback = this.loadLocal();
          this.watchlistIds.set(fallback);
          this.isUsingLocal.set(fallback.length > 0);
          this.isSyncing.set(false);
        },
      });
  }

  toggleInstrument(instrumentId: string): void {
    const current = new Set(this.watchlistIds());
    if (current.has(instrumentId)) {
      current.delete(instrumentId);
    } else {
      current.add(instrumentId);
    }
    const updated = this.sanitiseIds(Array.from(current));
    this.watchlistIds.set(updated);
    this.persistLocal(updated);
    this.pushToRemote(updated);
  }

  private loadLocal(): string[] {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) {
        return [];
      }
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        return parsed.filter((item): item is string => typeof item === 'string');
      }
      return [];
    } catch (error) {
      console.warn('Failed to read watchlist from localStorage', error);
      return [];
    }
  }

  private persistLocal(ids: string[]): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch (error) {
      console.warn('Failed to persist watchlist to localStorage', error);
    }
  }

  private pushToRemote(ids: string[]): void {
    this.isSyncing.set(true);
    const payload: WatchlistRequest = { favorites: ids };
    this.marketApi
      .updateWatchlist(payload)
      .pipe(take(1))
      .subscribe({
        next: (response) => {
          const favorites = this.sanitiseIds(response?.favorites ?? []);
          this.watchlistIds.set(favorites);
          this.persistLocal(favorites);
          this.syncError.set(null);
          this.isUsingLocal.set(false);
          this.isSyncing.set(false);
        },
        error: (error) => {
          console.error(error);
          this.syncError.set('Failed to synchronise favourites with the server.');
          this.isUsingLocal.set(true);
          this.isSyncing.set(false);
        },
      });
  }

  private sanitiseIds(values: unknown[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const value of values) {
      if (typeof value !== 'string') {
        continue;
      }
      if (seen.has(value)) {
        continue;
      }
      seen.add(value);
      result.push(value);
    }
    return result;
  }
}
