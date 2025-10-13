import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { AuthStateService } from '../shared/auth/auth-state.service';

@Component({
  standalone: true,
  selector: 'app-login-page',
  imports: [CommonModule],
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPage {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly authState = inject(AuthStateService);

  protected readonly isSubmitting = signal(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    effect(
      () => {
        if (this.authState.currentUser()) {
          void this.router.navigateByUrl('/dashboard');
        }
      },
      { allowSignalWrites: true },
    );
  }

  protected submit(): void {
    if (this.isSubmitting()) {
      return;
    }

    this.isSubmitting.set(true);
    this.error.set(null);
    try {
      this.auth.login();
    } catch (error) {
      console.error('Unable to start the sign-in flow.', error);
      this.error.set('Unable to start the sign-in flow. Please contact support.');
      this.isSubmitting.set(false);
    }
  }
}
