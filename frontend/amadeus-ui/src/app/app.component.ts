// src/app/app.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss'],
})
export class AppComponent implements OnInit {
  title = 'Amadeus 2.0';
  health: any;
  core: any;
  nodes: any;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.api.health().subscribe(h => (this.health = h));
    this.api.coreInfo().subscribe(c => (this.core = c));
    this.api.nodes().subscribe(n => (this.nodes = n));
  }

  startBacktest(): void {
    this.api.startBacktest().subscribe(() => this.refresh());
  }

  startLive(): void {
    this.api.startLive().subscribe(() => this.refresh());
  }

  stop(id: string): void {
    this.api.stopNode(id).subscribe(() => this.refresh());
  }
}
