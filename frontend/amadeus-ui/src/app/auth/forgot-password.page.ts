import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { AuthApi } from '../api/clients/auth.api';

@Component({
  standalone: true,
  selector: 'app-forgot-password-page',
  imports: [CommonModule, ReactiveFormsModule, RouterModule],
  templateUrl: './forgot-password.page.html',
  styleUrls: ['./forgot-password.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ForgotPasswordPage {
  private readonly fb = inject(FormBuilder);
  private readonly authApi = inject(AuthApi);

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
  });

  protected readonly isSubmitting = signal(false);
  protected readonly submitted = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async submit(): Promise<void> {
    if (this.submitted()) {
      return;
    }

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    if (this.isSubmitting()) {
      return;
    }

    this.isSubmitting.set(true);
    this.error.set(null);

    const email = this.form.controls.email.value.trim();

    try {
      await firstValueFrom(this.authApi.requestPasswordReset({ email }));
      this.submitted.set(true);
    } catch (error) {
      console.error('Failed to request password reset email.', error);
      const detail = (error as { error?: { detail?: string } })?.error?.detail;
      this.error.set(detail ?? 'Unable to send the reset instructions. Please try again later.');
    } finally {
      this.isSubmitting.set(false);
    }
  }
}
