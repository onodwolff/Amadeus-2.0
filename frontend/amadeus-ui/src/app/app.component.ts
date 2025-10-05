import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss'],
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'Amadeus 2.0';
  health: any;
  core: any;
  nodes: any = { nodes: [] as any[] };
  wsState = 'disconnected';
  errorText = '';
  private ws?: WebSocket;
  private poll?: any;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.health().subscribe(h => this.health = h);
    this.api.coreInfo().subscribe(c => this.core = c);

    // WS
    this.ws = new WebSocket('ws://localhost:8000/ws/nodes');
    this.ws.onopen = () => { this.wsState = 'connected'; };
    this.ws.onclose = () => { this.wsState = 'closed'; };
    this.ws.onerror = (e) => { this.wsState = 'error'; console.error('WS error', e); };
    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        this.nodes = data;
      } catch (e) {
        console.error('WS parse error', e);
      }
    };

    // Доп. опрос на всякий (каждые 2 сек)
    this.poll = setInterval(() => {
      this.api.nodes().subscribe(n => this.nodes = n);
    }, 2000);
  }

  ngOnDestroy(): void {
    try { this.ws?.close(); } catch {}
    if (this.poll) clearInterval(this.poll);
  }

  startBacktest(): void {
    this.api.startBacktest().subscribe({
      next: () => this.api.nodes().subscribe(n => this.nodes = n),
      error: (e) => this.errorText = 'startBacktest failed',
    });
  }

  startLive(): void {
    this.api.startLive().subscribe({
      next: () => this.api.nodes().subscribe(n => this.nodes = n),
      error: (e) => this.errorText = 'startLive failed',
    });
  }

  stop(id: string): void {
    this.api.stopNode(id).subscribe({
      next: () => this.api.nodes().subscribe(n => this.nodes = n),
      error: () => this.errorText = 'stop failed',
    });
  }

  refreshOnce(): void {
    this.api.nodes().subscribe(n => this.nodes = n);
  }
}
