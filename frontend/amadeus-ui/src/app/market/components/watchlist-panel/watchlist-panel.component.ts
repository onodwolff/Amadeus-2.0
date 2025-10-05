import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { MarketSelectionStore } from '../../market-selection.store';
import { MarketWatchlistService } from '../../market-watchlist.service';
import { Instrument } from '../../../api/models';

interface WatchlistEntry {
  id: string;
  instrument: Instrument | null;
}

@Component({
  standalone: true,
  selector: 'app-watchlist-panel',
  imports: [CommonModule],
  templateUrl: './watchlist-panel.component.html',
  styleUrls: ['./watchlist-panel.component.scss'],
})
export class WatchlistPanelComponent {
  private readonly store = inject(MarketSelectionStore);
  private readonly watchlist = inject(MarketWatchlistService);

  readonly entries = computed<WatchlistEntry[]>(() => {
    const ids = this.watchlist.watchlistIds();
    const lookup = this.store.instrumentLookup();
    return ids.map((id) => ({ id, instrument: lookup.get(id) ?? null }));
  });

  readonly selectedInstrumentId = this.store.selectedInstrumentId;

  readonly isSyncing = this.watchlist.isSyncing;

  select(entry: WatchlistEntry): void {
    if (entry.instrument) {
      this.store.selectInstrument(entry.instrument);
    }
  }

  remove(entry: WatchlistEntry, event: Event): void {
    event.stopPropagation();
    this.watchlist.toggleInstrument(entry.id);
  }
}
