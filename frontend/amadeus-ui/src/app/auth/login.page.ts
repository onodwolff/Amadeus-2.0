import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';

import { AuthService } from './auth.service';
import { AuthStateService } from '../shared/auth/auth-state.service';

@Component({
  standalone: true,
  selector: 'app-login-page',
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPage {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly authState = inject(AuthStateService);

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  protected readonly emailControl = this.form.controls.email;
  protected readonly passwordControl = this.form.controls.password;

  protected readonly isSubmitting = signal(false);
  protected readonly error = signal<string | null>(null);

  protected submit(): void {
    if (this.form.invalid || this.isSubmitting()) {
      this.form.markAllAsTouched();
      return;
    }

    const { email, password } = this.form.getRawValue();
    this.isSubmitting.set(true);
    this.error.set(null);

    this.auth
      .login({ email, password })
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: (user) => {
          this.authState.setCurrentUser(user);
          void this.router.navigateByUrl('/dashboard');
        },
        error: (error) => {
          const detail = (error as any)?.error?.detail ?? (error as any)?.message;
          const message =
            typeof detail === 'string' && detail.trim().length > 0
              ? (detail as string)
              : 'Unable to sign in with the provided credentials.';
          this.error.set(message);
        },
      });
  }
}
