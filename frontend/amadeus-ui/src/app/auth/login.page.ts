import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { RouterModule } from '@angular/router';

import { AuthService, PasswordLoginError } from './auth.service';
import { AuthStateService } from '../shared/auth/auth-state.service';

@Component({
  standalone: true,
  selector: 'app-login-page',
  imports: [CommonModule, ReactiveFormsModule, RouterModule],
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPage {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly authState = inject(AuthStateService);
  private readonly fb = inject(FormBuilder);

  protected readonly isSubmitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = this.fb.nonNullable.group({
    identifier: ['', [Validators.required, Validators.minLength(3)]],
    password: ['', [Validators.required, Validators.minLength(6)]],
    rememberMe: this.fb.nonNullable.control(true),
  });

  private readonly storageKey = 'amadeus:last-login-identifier';

  constructor() {
    effect(
      () => {
        if (this.authState.currentUser()) {
          void this.router.navigateByUrl('/dashboard');
        }
      },
      { allowSignalWrites: true },
    );

    if (typeof window !== 'undefined') {
      try {
        const storedIdentifier = window.localStorage?.getItem(this.storageKey);
        if (storedIdentifier) {
          this.form.patchValue({ identifier: storedIdentifier, rememberMe: true });
        }
      } catch (error) {
        console.warn('Unable to restore remembered identifier.', error);
      }
    }
  }

  protected showIdentifierError(): boolean {
    const control = this.form.controls.identifier;
    return control.invalid && (control.dirty || control.touched);
  }

  protected identifierError(): string {
    const control = this.form.controls.identifier;
    if (control.hasError('required')) {
      return 'Enter the email address or username associated with your account.';
    }
    if (control.hasError('minlength')) {
      return 'Usernames and email addresses must be at least three characters.';
    }
    return 'Enter a valid email address or username.';
  }

  protected showPasswordError(): boolean {
    const control = this.form.controls.password;
    return control.invalid && (control.dirty || control.touched);
  }

  protected passwordError(): string {
    const control = this.form.controls.password;
    if (control.hasError('required')) {
      return 'Enter your password to continue.';
    }
    if (control.hasError('minlength')) {
      return 'Passwords must be at least six characters long.';
    }
    return 'Enter a valid password.';
  }

  protected async submit(): Promise<void> {
    if (this.isSubmitting()) {
      return;
    }

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.error.set('Check the highlighted fields and try again.');
      return;
    }

    const identifier = this.form.controls.identifier.value.trim();
    const password = this.form.controls.password.value;

    if (!identifier) {
      this.form.controls.identifier.markAsTouched();
      this.error.set('Enter the email address or username associated with your account.');
      return;
    }

    if (!password) {
      this.form.controls.password.markAsTouched();
      this.error.set('Enter your password to continue.');
      return;
    }

    this.isSubmitting.set(true);
    this.error.set(null);

    try {
      const result = await this.auth.loginWithPassword({
        identifier,
        password,
        rememberMe: this.form.controls.rememberMe.value,
      });

      if (result.kind === 'authenticated') {
        await this.router.navigateByUrl('/dashboard');
        return;
      }

      const detail = result.challenge.detail?.trim();
      await this.router.navigate(['/login/mfa'], {
        queryParams: {
          token: result.challenge.challengeToken,
          detail: detail && detail.length > 0 ? detail : 'Multi-factor verification required to continue.',
        },
      });
    } catch (error) {
      console.error('Unable to complete the sign-in flow.', error);
      if (error instanceof PasswordLoginError) {
        this.error.set(error.message);
      } else {
        this.error.set('Unable to sign in. Try again in a moment.');
      }
    } finally {
      this.isSubmitting.set(false);
      this.rememberIdentifier();
      this.form.controls.password.setValue('');
      this.form.controls.password.markAsPristine();
      this.form.controls.password.markAsUntouched();
    }
  }

  private rememberIdentifier(): void {
    if (typeof window === 'undefined') {
      return;
    }

    try {
      if (this.form.controls.rememberMe.value) {
        window.localStorage?.setItem(this.storageKey, this.form.controls.identifier.value.trim());
      } else {
        window.localStorage?.removeItem(this.storageKey);
      }
    } catch (error) {
      console.warn('Unable to update remembered identifier.', error);
    }
  }
}
