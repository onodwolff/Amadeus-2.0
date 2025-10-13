import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { AuthApi } from '../api/clients/auth.api';

@Component({
  standalone: true,
  selector: 'app-reset-password-page',
  imports: [CommonModule, ReactiveFormsModule, RouterModule],
  templateUrl: './reset-password.page.html',
  styleUrls: ['./reset-password.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ResetPasswordPage {
  private readonly fb = inject(FormBuilder);
  private readonly authApi = inject(AuthApi);
  private readonly route = inject(ActivatedRoute);

  protected readonly form = this.fb.nonNullable.group({
    newPassword: ['', [Validators.required, Validators.minLength(8)]],
    confirmPassword: ['', [Validators.required]],
  });

  protected readonly token = signal<string | null>(null);
  protected readonly isSubmitting = signal(false);
  protected readonly completed = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly mismatch = signal(false);

  constructor() {
    const token = this.route.snapshot.queryParamMap.get('token');
    if (typeof token === 'string' && token.trim()) {
      this.token.set(token);
    } else {
      this.error.set('The password reset link is missing a token. Please request a new link.');
    }
  }

  protected async submit(): Promise<void> {
    const token = this.token();
    if (!token || this.completed()) {
      return;
    }

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { newPassword, confirmPassword } = this.form.getRawValue();
    if (newPassword !== confirmPassword) {
      this.mismatch.set(true);
      return;
    }
    this.mismatch.set(false);

    if (this.isSubmitting()) {
      return;
    }

    this.isSubmitting.set(true);
    this.error.set(null);

    try {
      await firstValueFrom(this.authApi.resetPassword({ token, newPassword }));
      this.completed.set(true);
    } catch (error) {
      console.error('Password reset failed.', error);
      const detail = (error as { error?: { detail?: string } })?.error?.detail;
      this.error.set(detail ?? 'Unable to reset your password. The link may have expired.');
    } finally {
      this.isSubmitting.set(false);
    }
  }
}
