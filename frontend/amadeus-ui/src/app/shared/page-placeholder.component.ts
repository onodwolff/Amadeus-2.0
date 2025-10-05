import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

export interface PagePlaceholderCta {
  label: string;
  routerLink?: string | any[];
  href?: string;
  target?: '_self' | '_blank' | '_parent' | '_top';
  rel?: string;
  onClick?: (event: Event) => void;
}

@Component({
  standalone: true,
  selector: 'app-page-placeholder',
  imports: [CommonModule, RouterModule],
  template: `
    <section class="page-placeholder">
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
      <p *ngIf="hint" class="hint">{{ hint }}</p>

      <div *ngIf="ctas.length > 0" class="cta-container">
        <ng-container *ngFor="let cta of ctas">
          <a
            *ngIf="cta.href"
            class="cta-button"
            [href]="cta.href"
            [attr.target]="cta.target || '_self'"
            [attr.rel]="cta.rel || (cta.target === '_blank' ? 'noopener noreferrer' : null)"
          >
            {{ cta.label }}
          </a>
          <a *ngIf="cta.routerLink && !cta.href" class="cta-button" [routerLink]="cta.routerLink">
            {{ cta.label }}
          </a>
          <button
            *ngIf="!cta.href && !cta.routerLink"
            type="button"
            class="cta-button"
            (click)="cta.onClick?.($event)"
          >
            {{ cta.label }}
          </button>
        </ng-container>
      </div>
    </section>
  `,
  styles: [
    `
      .page-placeholder {
        display: grid;
        gap: 12px;
        padding: 24px;
        border-radius: 16px;
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(148, 163, 184, 0.16);
      }

      h1 {
        margin: 0;
        font-size: 1.75rem;
      }

      .hint {
        color: rgba(148, 163, 184, 0.9);
        font-style: italic;
      }

      .cta-container {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 8px;
      }

      .cta-button {
        padding: 8px 16px;
        border-radius: 999px;
        border: 1px solid rgba(148, 163, 184, 0.35);
        background: rgba(148, 163, 184, 0.1);
        color: inherit;
        text-decoration: none;
        font-weight: 500;
        cursor: pointer;
        transition: background 0.2s ease, border-color 0.2s ease;
      }

      .cta-button:hover,
      .cta-button:focus-visible {
        border-color: rgba(148, 163, 184, 0.6);
        background: rgba(148, 163, 184, 0.16);
        outline: none;
      }

      .cta-button:active {
        background: rgba(148, 163, 184, 0.24);
      }

      button.cta-button {
        font: inherit;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PagePlaceholderComponent {
  @Input({ required: true }) title!: string;
  @Input({ required: true }) description!: string;
  @Input() hint?: string;
  @Input() ctas: PagePlaceholderCta[] = [];
}
