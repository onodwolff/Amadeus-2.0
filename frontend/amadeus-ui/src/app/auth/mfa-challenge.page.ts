import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { AuthApi } from '../api/clients/auth.api';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { NotificationService } from '../shared/notifications/notification.service';

@Component({
  standalone: true,
  selector: 'app-mfa-challenge-page',
  imports: [CommonModule, ReactiveFormsModule, RouterModule],
  templateUrl: './mfa-challenge.page.html',
  styleUrls: ['./mfa-challenge.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MfaChallengePage {
  private readonly authApi = inject(AuthApi);
  private readonly authState = inject(AuthStateService);
  private readonly notifications = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);

  protected readonly form = this.fb.group({
    code: this.fb.nonNullable.control('', [Validators.required, Validators.minLength(6)]),
    rememberDevice: this.fb.nonNullable.control(false),
  });

  protected readonly error = signal<string | null>(null);
  protected readonly info = signal<string | null>(null);
  protected readonly isSubmitting = signal(false);

  private challengeToken: string | null;

  constructor() {
    const params = this.route.snapshot.queryParamMap;
    this.challengeToken = params.get('token');
    const detail = params.get('detail');
    if (detail) {
      this.info.set(detail);
    }
    if (!this.challengeToken) {
      this.error.set('This multi-factor challenge is invalid or has expired. Request a new code.');
    }
  }

  protected async submit(): Promise<void> {
    if (this.isSubmitting()) {
      return;
    }

    const token = this.challengeToken;
    if (!token) {
      this.error.set('This multi-factor challenge is invalid or has expired. Request a new code.');
      return;
    }

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.error.set('Enter the verification code from your authenticator or backup list.');
      return;
    }

    const code = this.form.controls.code.value.trim();
    if (!code) {
      this.error.set('Enter the verification code from your authenticator or backup list.');
      return;
    }

    this.isSubmitting.set(true);
    this.error.set(null);
    try {
      const response = await firstValueFrom(
        this.authApi.completeMfaLogin({
          challengeToken: token,
          code,
          rememberDevice: this.form.controls.rememberDevice.value,
        }),
      );
      this.authState.setCurrentUser(response.user);
      this.notifications.success('Multi-factor verification complete.', 'Security');
      this.challengeToken = null;
      await this.router.navigateByUrl('/dashboard');
    } catch (error) {
      console.error('Unable to complete MFA challenge.', error);
      const detail = (error as any)?.error?.detail;
      const message =
        typeof detail === 'string' && detail.trim().length > 0
          ? (detail as string)
          : 'Invalid or expired verification code. Try again.';
      this.error.set(message);
    } finally {
      this.isSubmitting.set(false);
      this.form.controls.code.setValue('');
      this.form.controls.code.markAsPristine();
      this.form.controls.code.markAsUntouched();
    }
  }
}
