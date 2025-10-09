import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { UsersApi } from '../../api/clients/users.api';
import { UserCreateRequest, UserProfile } from '../../api/models';

@Component({
  selector: 'app-admin-user-create-dialog',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  template: `
    <section *ngIf="isOpen()" class="admin-user-create-dialog">
      <div class="admin-user-create-dialog__backdrop" (click)="close()" aria-hidden="true"></div>
      <div
        class="admin-user-create-dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="createUserDialogTitle"
      >
        <form
          class="admin-user-create-dialog__form"
          [formGroup]="form"
          (ngSubmit)="submit()"
          novalidate
        >
          <header class="admin-user-create-dialog__header">
            <h2 id="createUserDialogTitle">Create user</h2>
            <p>Invite a new member to the workspace and assign a role.</p>
          </header>

          <div class="admin-user-create-dialog__body">
            <label class="admin-user-create-dialog__field">
              <span>Email</span>
              <input
                type="email"
                formControlName="email"
                autocomplete="off"
                required
              />
            </label>

            <label class="admin-user-create-dialog__field">
              <span>Password</span>
              <input
                type="password"
                formControlName="password"
                autocomplete="new-password"
                required
                minlength="8"
              />
            </label>

            <label class="admin-user-create-dialog__field">
              <span>Name (optional)</span>
              <input type="text" formControlName="name" autocomplete="off" />
            </label>

            <label class="admin-user-create-dialog__field">
              <span>Role</span>
              <select formControlName="role">
                <option *ngFor="let option of roleOptions" [value]="option.value">
                  {{ option.label }}
                </option>
              </select>
            </label>

            <p *ngIf="submissionError() as error" class="admin-user-create-dialog__error">
              {{ error }}
            </p>
          </div>

          <footer class="admin-user-create-dialog__footer">
            <button type="button" (click)="close()" [disabled]="isSubmitting()">
              Cancel
            </button>
            <button type="submit" [disabled]="isSubmitting()">
              <span *ngIf="isSubmitting(); else submitLabel">Creating…</span>
              <ng-template #submitLabel>Create user</ng-template>
            </button>
          </footer>
        </form>
      </div>
    </section>
  `,
  styles: [
    `
      .admin-user-create-dialog {
        position: fixed;
        inset: 0;
        display: grid;
        place-items: center;
        z-index: 1100;
      }

      .admin-user-create-dialog__backdrop {
        position: absolute;
        inset: 0;
        background: rgba(15, 23, 42, 0.55);
      }

      .admin-user-create-dialog__panel {
        position: relative;
        width: min(480px, calc(100vw - 2rem));
        max-height: calc(100vh - 4rem);
        overflow: auto;
        background: var(--surface-elevated, #0f172a);
        border-radius: 0.75rem;
        box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.45);
        color: var(--text-primary, #e2e8f0);
      }

      .admin-user-create-dialog__form {
        display: flex;
        flex-direction: column;
        gap: 1.5rem;
        padding: 2rem;
      }

      .admin-user-create-dialog__header h2 {
        margin: 0 0 0.5rem;
        font-size: 1.5rem;
        font-weight: 600;
      }

      .admin-user-create-dialog__header p {
        margin: 0;
        color: var(--text-secondary, #94a3b8);
      }

      .admin-user-create-dialog__body {
        display: grid;
        gap: 1rem;
      }

      .admin-user-create-dialog__field {
        display: grid;
        gap: 0.5rem;
      }

      .admin-user-create-dialog__field span {
        font-weight: 500;
        color: var(--text-secondary, #94a3b8);
      }

      .admin-user-create-dialog__field input,
      .admin-user-create-dialog__field select {
        padding: 0.625rem 0.75rem;
        border-radius: 0.5rem;
        border: 1px solid rgba(148, 163, 184, 0.35);
        background: rgba(15, 23, 42, 0.6);
        color: inherit;
      }

      .admin-user-create-dialog__field input:focus,
      .admin-user-create-dialog__field select:focus {
        outline: none;
        border-color: var(--accent-primary, #38bdf8);
        box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.25);
      }

      .admin-user-create-dialog__error {
        margin: 0;
        padding: 0.75rem;
        border-radius: 0.5rem;
        background: rgba(248, 113, 113, 0.12);
        color: #fca5a5;
        font-weight: 500;
      }

      .admin-user-create-dialog__footer {
        display: flex;
        justify-content: flex-end;
        gap: 0.75rem;
      }

      .admin-user-create-dialog__footer button {
        min-width: 7rem;
        padding: 0.5rem 1.25rem;
        border-radius: 9999px;
        font-weight: 600;
        border: none;
        cursor: pointer;
        transition: transform 120ms ease, opacity 120ms ease;
      }

      .admin-user-create-dialog__footer button[type='button'] {
        background: rgba(148, 163, 184, 0.15);
        color: var(--text-secondary, #94a3b8);
      }

      .admin-user-create-dialog__footer button[type='submit'] {
        background: var(--accent-primary, #38bdf8);
        color: #0f172a;
      }

      .admin-user-create-dialog__footer button[disabled] {
        opacity: 0.6;
        cursor: default;
      }

      @media (max-width: 30rem) {
        .admin-user-create-dialog__form {
          padding: 1.5rem;
        }
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminUserCreateDialogComponent {
  @Output() readonly created = new EventEmitter<UserProfile>();
  @Output() readonly cancelled = new EventEmitter<void>();

  private readonly fb = inject(FormBuilder);
  private readonly usersApi = inject(UsersApi);

  readonly isOpen = signal(false);
  readonly isSubmitting = signal(false);
  readonly submissionError = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    email: this.fb.nonNullable.control<string>('', [Validators.required, Validators.email]),
    password: this.fb.nonNullable.control<string>('', [Validators.required, Validators.minLength(8)]),
    name: this.fb.control<string>(''),
    role: this.fb.nonNullable.control<string>('member', Validators.required),
  });

  readonly roleOptions: Array<{ value: string; label: string }> = [
    { value: 'member', label: 'Member' },
    { value: 'viewer', label: 'Viewer' },
  ];

  open(): void {
    this.resetForm();
    this.submissionError.set(null);
    this.isSubmitting.set(false);
    this.isOpen.set(true);
  }

  close(): void {
    this.isOpen.set(false);
    this.isSubmitting.set(false);
    this.submissionError.set(null);
    this.resetForm();
    this.cancelled.emit();
  }

  submit(): void {
    if (this.isSubmitting()) {
      return;
    }

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { email, password, name, role } = this.form.getRawValue();
    const payload: UserCreateRequest = {
      email: email.trim().toLowerCase(),
      password,
      role: role.trim().toLowerCase(),
    };

    const trimmedName = name?.trim();
    if (trimmedName) {
      payload.name = trimmedName;
    }

    this.isSubmitting.set(true);
    this.submissionError.set(null);

    this.usersApi.createUser(payload).subscribe({
      next: (response) => {
        this.isSubmitting.set(false);
        this.isOpen.set(false);
        this.resetForm();
        this.created.emit(response.user);
      },
      error: (error) => {
        let message = 'Failed to create user.';
        if (error?.status === 409) {
          message = 'Email is already associated with another account.';
        } else if (typeof error?.error?.detail === 'string') {
          message = error.error.detail;
        } else if (typeof error?.message === 'string' && error.message.trim()) {
          message = error.message;
        }

        this.submissionError.set(message);
        this.isSubmitting.set(false);
      },
    });
  }

  private resetForm(): void {
    this.form.reset({
      email: '',
      password: '',
      name: '',
      role: 'member',
    });
  }
}
