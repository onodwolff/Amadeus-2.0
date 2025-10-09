import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ViewChild,
  signal,
  inject,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatSort, MatSortModule } from '@angular/material/sort';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { debounceTime, finalize } from 'rxjs';

import { UsersApi } from '../../api/clients/users.api';
import { UserProfile } from '../../api/models';
import { AdminUserCreateDialogComponent } from './create-user-dialog.component';

@Component({
  standalone: true,
  selector: 'app-admin-users-page',
  templateUrl: './admin-users.page.html',
  styleUrls: ['./admin-users.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatSortModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatDialogModule,
    MatSnackBarModule,
    MatProgressSpinnerModule,
  ],
})
export class AdminUsersPage {
  private readonly usersApi = inject(UsersApi);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);

  readonly displayedColumns: (keyof UserProfile)[] = [
    'id',
    'email',
    'name',
    'role',
    'created_at',
    'updated_at',
  ];

  readonly filterControl = new FormControl('', { nonNullable: true });
  readonly dataSource = new MatTableDataSource<UserProfile>([]);

  @ViewChild(MatSort)
  set matSort(sort: MatSort | null) {
    if (sort) {
      this.dataSource.sort = sort;
    }
  }

  constructor() {
    this.dataSource.filterPredicate = (item, filter) => {
      const term = filter.trim().toLowerCase();
      if (!term) {
        return true;
      }

      return (
        item.email.toLowerCase().includes(term) ||
        (item.name ?? '').toLowerCase().includes(term) ||
        item.role.toLowerCase().includes(term) ||
        item.id.toLowerCase().includes(term)
      );
    };

    this.dataSource.sortingDataAccessor = (item, property) => {
      if (property === 'created_at' || property === 'updated_at') {
        return new Date(item[property] ?? '').getTime();
      }

      const value = (item as unknown as Record<string, unknown>)[property];
      if (typeof value === 'number') {
        return value;
      }

      return typeof value === 'string' ? value.toLowerCase() : '';
    };

    this.filterControl.valueChanges
      .pipe(takeUntilDestroyed(), debounceTime(150))
      .subscribe((value) => {
        this.dataSource.filter = value.trim().toLowerCase();
      });

    this.refreshUsers(false);
  }

  refreshUsers(showNotificationOnError = true): void {
    this.isLoading.set(true);
    this.error.set(null);

    this.usersApi
      .listUsers()
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: (response) => {
          this.dataSource.data = [...(response.users ?? [])];
        },
        error: (err: unknown) => {
          const message = this.resolveErrorMessage(err, 'Unable to load users.');
          this.error.set(message);
          if (showNotificationOnError) {
            this.snackBar.open(message, 'Dismiss', { duration: 4000 });
          }
        },
      });
  }

  openCreateDialog(): void {
    const dialogRef = this.dialog.open(AdminUserCreateDialogComponent, {
      width: '480px',
      disableClose: true,
    });

    dialogRef
      .afterClosed()
      .pipe(takeUntilDestroyed())
      .subscribe((result) => {
        if (result === 'created') {
          this.refreshUsers();
          this.snackBar.open('User account created successfully.', 'Dismiss', {
            duration: 4000,
          });
        }
      });
  }

  clearFilter(): void {
    this.filterControl.setValue('');
  }

  trackByUserId(_: number, item: UserProfile): string {
    return item.id;
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
