import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { finalize } from 'rxjs';
import { DataApi } from '../api/clients';
import { HistoricalDatasetDto } from '../api/models';

const FIELD_HELP_TEXT = {
  venue:
    'Specify the exchange venue code (for example BINANCE). The dataset will be downloaded from this venue.',
  instrument:
    'Provide the instrument symbol in uppercase (for example BTCUSDT). Only trades for this pair will be included.',
  timeframe:
    'Choose the bar interval to aggregate the data. Use short codes such as 1m, 5m, 1h, or 1d.',
  start:
    'Select the UTC date and time where the dataset should start. The download task will include data from this moment onwards.',
  end:
    'Select the UTC date and time where the dataset should finish. Data after this moment will be excluded.',
  label:
    'Optionally add a descriptive name so you can recognise this dataset later. Leave blank to use the default identifier.',
} as const;

type FieldHelpKey = keyof typeof FIELD_HELP_TEXT;

@Component({
  standalone: true,
  selector: 'app-historical-data-page',
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './historical-data.page.html',
  styleUrls: ['./historical-data.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HistoricalDataPage {
  private readonly fb = inject(FormBuilder);
  private readonly dataApi = inject(DataApi);

  readonly datasets = signal<HistoricalDatasetDto[]>([]);
  readonly isLoading = signal(false);
  readonly loadError = signal<string | null>(null);
  readonly submissionError = signal<string | null>(null);
  readonly submissionSuccess = signal<string | null>(null);
  readonly isSubmitting = signal(false);

  readonly form = this.fb.nonNullable.group({
    venue: this.fb.nonNullable.control<string>('BINANCE', Validators.required),
    instrument: this.fb.nonNullable.control<string>('BTCUSDT', Validators.required),
    timeframe: this.fb.nonNullable.control<string>('1m', Validators.required),
    start: this.fb.nonNullable.control<string>('', Validators.required),
    end: this.fb.nonNullable.control<string>('', Validators.required),
    label: this.fb.control<string>(''),
  });

  readonly fieldHelpText = FIELD_HELP_TEXT;
  readonly activeHelpField = signal<FieldHelpKey | null>(null);

  constructor() {
    const now = new Date();
    const start = new Date(now);
    start.setUTCDate(start.getUTCDate() - 7);
    this.form.patchValue({
      start: this.toLocalInput(start),
      end: this.toLocalInput(now),
    });
    this.refreshDatasets();
  }

  refreshDatasets(): void {
    this.isLoading.set(true);
    this.loadError.set(null);
    this.dataApi
      .listDatasets()
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: response => this.datasets.set(response.datasets ?? []),
        error: () => this.loadError.set('Failed to load cached datasets.'),
      });
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const value = this.form.getRawValue();
    this.isSubmitting.set(true);
    this.submissionError.set(null);
    this.submissionSuccess.set(null);

    const trimmedLabel = value.label?.trim();
    const request = {
      venue: value.venue,
      instrument: value.instrument,
      timeframe: value.timeframe,
      start: this.toIso(value.start),
      end: this.toIso(value.end),
      label: trimmedLabel?.length ? trimmedLabel : null,
      source: 'ui' as const,
    };

    this.dataApi
      .requestDownload(request)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: response => {
          const dataset = response.dataset;
          this.submissionSuccess.set(`Dataset ${dataset.datasetId} queued (${dataset.status}).`);
          this.refreshDatasets();
        },
        error: error => {
          const message = error?.error?.message || error?.message || 'Failed to request dataset download.';
          this.submissionError.set(message);
        },
      });
  }

  trackByDatasetId(_index: number, dataset: HistoricalDatasetDto): number {
    return dataset.id;
  }

  toggleHelp(field: FieldHelpKey): void {
    this.activeHelpField.update(current => (current === field ? null : field));
  }

  isHelpVisible(field: FieldHelpKey): boolean {
    return this.activeHelpField() === field;
  }

  closeHelp(): void {
    this.activeHelpField.set(null);
  }

  private toLocalInput(date: Date): string {
    const pad = (value: number) => `${value}`.padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(
      date.getMinutes(),
    )}`;
  }

  private toIso(value: string): string {
    const date = new Date(value);
    if (isNaN(date.getTime())) {
      return value;
    }
    return date.toISOString();
  }
}
