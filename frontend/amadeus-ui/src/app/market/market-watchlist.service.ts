import { Injectable, inject, signal } from '@angular/core';
import { MarketApi } from '../api/clients/market.api';
import { WatchlistRequest } from '../api/models';
import { catchError, of, switchMap, take, tap } from 'rxjs';

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
      .pipe(
        take(1),
        catchError((error) => {
          console.error(error);
          this.syncError.set('Unable to load favourites from the server. Using your local watchlist.');
          return of({ favorites: [] });
        }),
        tap(() => this.isSyncing.set(false)),
      )
      .subscribe((response) => {
        const merged = this.mergeWatchlists(response.favorites ?? []);
        this.watchlistIds.set(merged);
        this.persistLocal(merged);
        this.syncError.set(null);
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

  private mergeWatchlists(remote: string[]): string[] {
    const current = new Set(this.watchlistIds());
    for (const id of remote) {
      current.add(id);
    }
    return Array.from(current);
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
      .pipe(
        take(1),
        tap(() => this.isSyncing.set(false)),
        catchError((error) => {
          console.error(error);
          this.syncError.set('Failed to synchronise favourites with the server.');
          this.isSyncing.set(false);
          return of(null);
        }),
        switchMap((response) => {
          if (!response) {
            return of(null);
          }
          return of(response.favorites ?? []);
        }),
      )
      .subscribe((favorites) => {
        if (!favorites) {
          return;
        }
        this.watchlistIds.set(favorites);
        this.persistLocal(favorites);
        this.syncError.set(null);
      });
  }
}
