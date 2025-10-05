import { Injectable, inject, signal } from '@angular/core';
import { MarketApi } from '../api/clients/market.api';
import { WatchlistRequest } from '../api/models';
import { finalize, take } from 'rxjs';

const STORAGE_KEY = 'amadeus.market.watchlist';

@Injectable({ providedIn: 'root' })
export class MarketWatchlistService {
  private readonly marketApi = inject(MarketApi);

  readonly watchlistIds = signal<string[]>(this.loadLocal());
  readonly isSyncing = signal(false);
  readonly syncError = signal<string | null>(null);

  private isInitialized = false;

  initialize(): void {
    if (this.isInitialized) {
      return;
    }
    this.isInitialized = true;
    this.isSyncing.set(true);
    this.marketApi
      .getWatchlist()
      .pipe(take(1), finalize(() => this.isSyncing.set(false)))
      .subscribe({
        next: (response) => {
          const favorites = this.normalizeIds(response.favorites ?? []);
          this.watchlistIds.set(favorites);
          this.persistLocal(favorites);
          this.syncError.set(null);
        },
        error: (error) => {
          console.error(error);
          this.syncError.set('Unable to load favourites from the server. Using your local watchlist.');
          const local = this.loadLocal();
          this.watchlistIds.set(local);
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
    const updated = Array.from(current);
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
        return this.normalizeIds(parsed);
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
      .pipe(take(1), finalize(() => this.isSyncing.set(false)))
      .subscribe({
        next: (response) => {
          const favorites = this.normalizeIds(response?.favorites ?? ids);
          this.watchlistIds.set(favorites);
          this.persistLocal(favorites);
          this.syncError.set(null);
        },
        error: (error) => {
          console.error(error);
          this.syncError.set('Failed to synchronise favourites with the server.');
        },
      });
  }

  private normalizeIds(ids: unknown[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const raw of ids) {
      if (typeof raw !== 'string') {
        continue;
      }
      const value = raw.trim();
      if (!value || seen.has(value)) {
        continue;
      }
      seen.add(value);
      result.push(value);
    }
    return result;
  }
}
