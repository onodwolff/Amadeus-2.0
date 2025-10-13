import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatCheckboxChange, MatCheckboxModule } from '@angular/material/checkbox';
import { finalize } from 'rxjs';

import { UsersApi } from '../../api/clients/users.api';
import { RoleSummary, UserCreateRequest } from '../../api/models';

interface CreateDialogData {
  roles: RoleSummary[];
}

type CreateUserFormGroup = FormGroup<{
  email: FormControl<string>;
  name: FormControl<string>;
  password: FormControl<string>;
  confirmPassword: FormControl<string>;
  active: FormControl<boolean>;
  roles: FormControl<string[]>;
}>;

const matchPasswordsValidator: ValidatorFn = (control: AbstractControl): ValidationErrors | null => {
  const password = control.get('password')?.value as string | null | undefined;
  const confirm = control.get('confirmPassword')?.value as string | null | undefined;

  if (!password || !confirm) {
    return null;
  }

  return password === confirm ? null : { passwordMismatch: true };
};

const atLeastOneRoleSelected: ValidatorFn = (control: AbstractControl): ValidationErrors | null => {
  const value = control.value as string[] | null | undefined;
  return Array.isArray(value) && value.length > 0 ? null : { required: true };
};

@Component({
  standalone: true,
  selector: 'app-admin-user-create-dialog',
  templateUrl: './create-user-dialog.component.html',
  styleUrls: ['./create-user-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatSnackBarModule,
    MatProgressSpinnerModule,
    MatSlideToggleModule,
    MatCheckboxModule,
  ],
})
export class AdminUserCreateDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly usersApi = inject(UsersApi);
  private readonly dialogRef = inject(MatDialogRef<AdminUserCreateDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);
  private readonly data = inject<CreateDialogData>(MAT_DIALOG_DATA);

  readonly isSubmitting = signal(false);
  readonly submissionError = signal<string | null>(null);

  readonly form: CreateUserFormGroup = this.createForm();

  get availableRoles(): RoleSummary[] {
    return this.data.roles ?? [];
  }

  get defaultRole(): string | null {
    if (!this.availableRoles.length) {
      return null;
    }

    const member = this.availableRoles.find((role) => role.slug === 'member');
    return member?.slug ?? this.availableRoles[0]?.slug ?? null;
  }

  get rolesInvalid(): boolean {
    const control = this.form.controls.roles;
    return control.touched && control.invalid;
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.form.controls.roles.updateValueAndValidity();
      return;
    }

    const { confirmPassword: _confirm, roles, ...raw } = this.form.getRawValue();
    const selectedRoles = roles && roles.length ? roles : this.defaultRole ? [this.defaultRole] : [];

    if (!selectedRoles.length) {
      this.snackBar.open('Select at least one role before creating the account.', 'Dismiss', {
        duration: 4000,
      });
      return;
    }

    const payload: UserCreateRequest = {
      email: raw.email.trim(),
      password: raw.password,
      active: raw.active,
      roles: selectedRoles,
    };

    const trimmedName = raw.name?.trim();
    if (trimmedName) {
      payload.name = trimmedName;
    }

    this.isSubmitting.set(true);
    this.usersApi
      .createUser(payload)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => this.dialogRef.close('created'),
        error: (error: unknown) => {
          this.submissionError.set(this.resolveErrorMessage(error, 'Unable to create user.'));
        },
      });
  }

  cancel(): void {
    if (!this.isSubmitting()) {
      this.dialogRef.close();
    }
  }

  isRoleSelected(role: RoleSummary): boolean {
    return this.form.controls.roles.value.includes(role.slug);
  }

  toggleRole(role: RoleSummary, change: MatCheckboxChange): void {
    const current = new Set(this.form.controls.roles.value);
    if (change.checked) {
      current.add(role.slug);
    } else {
      current.delete(role.slug);
    }
    this.form.controls.roles.setValue(Array.from(current));
    this.form.controls.roles.markAsTouched();
    this.form.controls.roles.updateValueAndValidity();
  }

  private createForm(): CreateUserFormGroup {
    const defaultRole = this.defaultRole;
    return this.fb.nonNullable.group(
      {
        email: ['', [Validators.required, Validators.email]],
        name: ['', [Validators.required, Validators.minLength(2)]],
        password: ['', [Validators.required, Validators.minLength(8)]],
        confirmPassword: ['', [Validators.required]],
        active: this.fb.nonNullable.control(true),
        roles: this.fb.nonNullable.control<string[]>(defaultRole ? [defaultRole] : [], atLeastOneRoleSelected),
      },
      { validators: matchPasswordsValidator },
    );
  }

  private resolveErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse) {
      const detail = (error.error as { detail?: unknown } | null)?.detail;
      if (typeof detail === 'string' && detail.trim().length > 0) {
        return detail;
      }
      if (detail && typeof detail === 'object') {
        const missingRoles = (detail as { missingRoles?: string[] }).missingRoles;
        if (Array.isArray(missingRoles) && missingRoles.length) {
          return `Unknown roles requested: ${missingRoles.join(', ')}`;
        }
      }
    }

    return fallback;
  }
}
