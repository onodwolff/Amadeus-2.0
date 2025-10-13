import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthApi } from '../api/clients/auth.api';
import { OperationStatus } from '../api/models';

@Component({
  standalone: true,
  selector: 'app-verify-email-page',
  imports: [CommonModule, RouterModule],
  templateUrl: './verify-email.page.html',
  styleUrls: ['./verify-email.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VerifyEmailPage {
  private readonly route = inject(ActivatedRoute);
  private readonly authApi = inject(AuthApi);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly status = signal<'loading' | 'success' | 'error'>('loading');
  protected readonly message = signal('Verifying your e-mail address…');

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      const token = params.get('token');
      if (!token) {
        this.status.set('error');
        this.message.set('A verification token was not provided.');
        return;
      }
      this.verify(token);
    });
  }

  private verify(token: string): void {
    this.status.set('loading');
    this.message.set('Verifying your e-mail address…');
    this.authApi.verifyEmail(token).subscribe({
      next: (response: OperationStatus) => {
        this.status.set('success');
        this.message.set(response.detail ?? 'Your e-mail address has been verified.');
      },
      error: error => {
        console.error('Email verification failed.', error);
        const detail = error?.error?.detail;
        this.status.set('error');
        this.message.set(detail ?? 'Unable to verify the e-mail address. The link may have expired.');
      },
    });
  }
}
