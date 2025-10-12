import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  inject,
  signal,
} from '@angular/core';
import {
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { finalize } from 'rxjs';

import { UsersApi } from '../../api/clients/users.api';
import { UserCreateRequest } from '../../api/models';

const PROVISIONABLE_ROLES = ['member', 'viewer'] as const;
type ProvisionableRole = (typeof PROVISIONABLE_ROLES)[number];

type CreateUserFormGroup = FormGroup<{
  email: FormControl<string>;
  name: FormControl<string>;
  password: FormControl<string>;
  confirmPassword: FormControl<string>;
  role: FormControl<ProvisionableRole>;
}>;

const matchPasswordsValidator: ValidatorFn = (control) => {
  const password = control.get('password')?.value as string | null | undefined;
  const confirm = control.get('confirmPassword')?.value as string | null | undefined;

  if (!password || !confirm) {
    return null;
  }

  return password === confirm ? null : { passwordMismatch: true };
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
    MatSelectModule,
    MatButtonModule,
    MatSnackBarModule,
    MatProgressSpinnerModule,
  ],
})
export class AdminUserCreateDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly usersApi = inject(UsersApi);
  private readonly dialogRef = inject(MatDialogRef<AdminUserCreateDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);

  readonly isSubmitting = signal(false);

  readonly roles = PROVISIONABLE_ROLES;

  readonly form: CreateUserFormGroup = this.createForm();

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { confirmPassword, ...value } = this.form.getRawValue();

    if (!PROVISIONABLE_ROLES.includes(value.role as ProvisionableRole)) {
      this.snackBar.open('The admin role cannot be assigned through this interface.', 'Dismiss', {
        duration: 5000,
      });
      this.form.controls.role.setValue(PROVISIONABLE_ROLES[0]);
      return;
    }

    const payload: UserCreateRequest = value;

    this.isSubmitting.set(true);
    this.usersApi
      .createUser(payload)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => this.dialogRef.close('created'),
        error: (error: unknown) => {
          this.snackBar.open(this.resolveErrorMessage(error, 'Unable to create user.'), 'Dismiss', {
            duration: 5000,
          });
        },
      });
  }

  cancel(): void {
    if (!this.isSubmitting()) {
      this.dialogRef.close();
    }
  }

  get passwordMismatch(): boolean {
    return (
      this.form.hasError('passwordMismatch') &&
      !!this.form.controls.confirmPassword.touched &&
      this.form.controls.confirmPassword.value !== ''
    );
  }

  private createForm(): CreateUserFormGroup {
    return this.fb.nonNullable.group(
      {
        email: ['', [Validators.required, Validators.email]],
        name: ['', [Validators.required, Validators.minLength(2)]],
        password: ['', [Validators.required, Validators.minLength(8)]],
        confirmPassword: ['', [Validators.required]],
        role: this.fb.nonNullable.control<ProvisionableRole>('member', Validators.required),
      },
      { validators: matchPasswordsValidator },
    );
  }

  private resolveErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse) {
      const apiMessage = (error.error as { message?: string } | null)?.message;
      if (apiMessage) {
        return apiMessage;
      }
    }

    return fallback;
  }
}
