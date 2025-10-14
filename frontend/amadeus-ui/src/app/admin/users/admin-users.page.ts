import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ViewChild,
  computed,
  inject,
  signal,
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
import { MatSlideToggleChange, MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSelectModule } from '@angular/material/select';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { debounceTime, finalize } from 'rxjs';

import { UsersApi } from '../../api/clients/users.api';
import { AdminUser, RoleSummary } from '../../api/models';
import { AuthStateService } from '../../shared/auth/auth-state.service';
import { AdminUserCreateDialogComponent } from './create-user-dialog.component';

type UserStatusFilter = 'all' | 'active' | 'suspended';

interface UserTableFilters {
  term: string;
  role: string;
  status: UserStatusFilter;
}

interface RoleFilterOption {
  slug: string;
  name: string;
}

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
    MatSlideToggleModule,
    MatTooltipModule,
    MatSelectModule,
  ],
})
export class AdminUsersPage {
  private readonly usersApi = inject(UsersApi);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly authState = inject(AuthStateService);

  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly togglingUserIds = signal<Set<number>>(new Set());
  readonly roleTogglesInFlight = signal<Set<string>>(new Set());
  readonly availableRoles = signal<RoleSummary[]>([]);
  readonly rolesError = signal<string | null>(null);

  readonly canManageUsers = computed(() =>
    this.authState.hasAnyPermission(['gateway.users.manage', 'gateway.admin']),
  );
  readonly canViewUsers = computed(() =>
    this.authState.hasAnyPermission(['gateway.users.view', 'gateway.admin']),
  );
  readonly assignableRoles = computed(() =>
    this.availableRoles().filter((role) => role.slug !== 'admin'),
  );

  readonly displayedColumns: (keyof AdminUser | 'roles')[] = [
    'id',
    'email',
    'name',
    'roles',
    'active',
    'createdAt',
    'updatedAt',
  ];

  private readonly filterDefaults: UserTableFilters = {
    term: '',
    role: 'all',
    status: 'all',
  };

  readonly filterControl = new FormControl<string>(this.filterDefaults.term, { nonNullable: true });
  readonly roleFilterControl = new FormControl<string>(this.filterDefaults.role, { nonNullable: true });
  readonly statusFilterControl = new FormControl<UserStatusFilter>(this.filterDefaults.status, {
    nonNullable: true,
  });
  readonly dataSource = new MatTableDataSource<AdminUser>([]);
  readonly roleFilterOptions = signal<RoleFilterOption[]>([]);

  @ViewChild(MatSort)
  set matSort(sort: MatSort | null) {
    if (sort) {
      this.dataSource.sort = sort;
    }
  }

  constructor() {
    this.dataSource.filterPredicate = (item, filter) => {
      const criteria = this.parseFilters(filter);

      if (criteria.role !== 'all' && !item.roles.includes(criteria.role)) {
        return false;
      }

      if (criteria.status !== 'all') {
        const isActive = criteria.status === 'active';
        if (item.active !== isActive) {
          return false;
        }
      }

      const term = criteria.term.trim().toLowerCase();
      if (!term) {
        return true;
      }

      const normalizedRoles = item.roles.map((role) => role.toLowerCase());
      return (
        item.email.toLowerCase().includes(term) ||
        this.normalizeName(item.name).includes(term) ||
        normalizedRoles.some((role) => role.includes(term)) ||
        (item.active ? 'active' : 'suspended').includes(term) ||
        item.username.toLowerCase().includes(term) ||
        String(item.id).toLowerCase().includes(term)
      );
    };

    this.dataSource.sortingDataAccessor = (item, property) => {
      if (property === 'name') {
        return this.normalizeName(item.name);
      }
      if (property === 'createdAt' || property === 'updatedAt') {
        return new Date(item[property] ?? '').getTime();
      }
      if (property === 'roles') {
        return item.roles.join(',');
      }

      const value = (item as unknown as Record<string, unknown>)[property];
      if (typeof value === 'number') {
        return value;
      }

      return typeof value === 'string' ? value.toLowerCase() : '';
    };

    this.filterControl.valueChanges
      .pipe(takeUntilDestroyed(), debounceTime(150))
      .subscribe((value) => this.applyFilterChanges(value));

    this.roleFilterControl.valueChanges
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.applyFilterChanges(this.filterControl.value));

    this.statusFilterControl.valueChanges
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.applyFilterChanges(this.filterControl.value));

    this.applyFilterChanges(this.filterControl.value);
    this.refreshUsers(false);
    this.loadRoles();
  }

  refreshUsers(showNotificationOnError = true): void {
    if (!this.canViewUsers()) {
      this.error.set('You do not have permission to view user accounts.');
      this.dataSource.data = [];
      return;
    }

    this.isLoading.set(true);
    this.error.set(null);

    this.usersApi
      .listUsers()
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: (users) => {
          this.dataSource.data = [...(users ?? [])];
          this.syncRoleFilterOptions(this.dataSource.data);
          this.applyFilterChanges(this.filterControl.value);
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

  loadRoles(): void {
    if (!this.canManageUsers()) {
      this.availableRoles.set([]);
      this.syncRoleFilterOptions(this.dataSource.data);
      return;
    }

    this.rolesError.set(null);
    this.usersApi.listRoles().subscribe({
      next: (roles) => {
        this.availableRoles.set(roles);
        this.syncRoleFilterOptions(this.dataSource.data);
      },
      error: (err: unknown) => {
        this.rolesError.set(this.resolveErrorMessage(err, 'Unable to load available roles.'));
      },
    });
  }

  openCreateDialog(): void {
    if (!this.canManageUsers()) {
      this.snackBar.open('You do not have permission to create users.', 'Dismiss', {
        duration: 4000,
      });
      return;
    }

    const dialogRef = this.dialog.open(AdminUserCreateDialogComponent, {
      width: '520px',
      disableClose: true,
      data: {
        roles: this.assignableRoles(),
      },
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
    this.filterControl.setValue(this.filterDefaults.term, { emitEvent: false });
    this.roleFilterControl.setValue(this.filterDefaults.role, { emitEvent: false });
    this.statusFilterControl.setValue(this.filterDefaults.status, { emitEvent: false });
    this.applyFilterChanges(this.filterDefaults.term);
  }

  trackByUserId(_: number, item: AdminUser): number {
    return item.id;
  }

  isToggleDisabled(userId: number): boolean {
    return !this.canManageUsers() || this.isLoading() || this.togglingUserIds().has(userId);
  }

  isRoleToggleDisabled(userId: number, role: string): boolean {
    return (
      !this.canManageUsers() ||
      this.isLoading() ||
      this.roleTogglesInFlight().has(this.composeRoleToggleKey(userId, role))
    );
  }

  toggleUserActive(user: AdminUser, change: MatSlideToggleChange): void {
    if (!this.canManageUsers()) {
      change.source.checked = user.active;
      this.snackBar.open('You do not have permission to modify account status.', 'Dismiss', {
        duration: 4000,
      });
      return;
    }

    const nextActive = change.checked;
    const previousActive = user.active;

    if (nextActive === previousActive) {
      return;
    }

    this.updateUserRow(user.id, { active: nextActive });
    this.markToggling(user.id, true);

    this.usersApi
      .updateUser(user.id, { active: nextActive })
      .pipe(finalize(() => this.markToggling(user.id, false)))
      .subscribe({
        next: (updated) => {
          this.updateUserRow(user.id, updated);
          const message = nextActive
            ? 'User account reactivated.'
            : 'User account suspended.';
          this.snackBar.open(message, 'Dismiss', { duration: 4000 });
        },
        error: (err: unknown) => {
          this.updateUserRow(user.id, { active: previousActive });
          const message = this.resolveErrorMessage(
            err,
            nextActive ? 'Unable to reactivate user.' : 'Unable to suspend user.',
          );
          this.snackBar.open(message, 'Dismiss', { duration: 5000 });
        },
      });
  }

  toggleRole(user: AdminUser, role: RoleSummary, change: MatSlideToggleChange): void {
    if (!this.canManageUsers()) {
      change.source.checked = user.roles.includes(role.slug);
      this.snackBar.open('You do not have permission to modify roles.', 'Dismiss', {
        duration: 4000,
      });
      return;
    }

    const desiredState = change.checked;
    const key = this.composeRoleToggleKey(user.id, role.slug);
    this.roleTogglesInFlight.update((current) => new Set(current).add(key));

    const request$ = desiredState
      ? this.usersApi.assignRole(user.id, role.slug)
      : this.usersApi.removeRole(user.id, role.slug);

    request$.pipe(finalize(() => this.clearRoleToggle(key))).subscribe({
      next: (updated) => {
        this.updateUserRow(user.id, updated);
        const verb = desiredState ? 'granted' : 'revoked';
        this.snackBar.open(`Role ${role.name} ${verb}.`, 'Dismiss', { duration: 3500 });
      },
      error: (err: unknown) => {
        this.updateUserRow(user.id, { roles: [...user.roles], permissions: [...user.permissions] });
        const fallback = desiredState
          ? 'Unable to assign role to user.'
          : 'Unable to remove role from user.';
        const message = this.resolveErrorMessage(err, fallback);
        this.snackBar.open(message, 'Dismiss', { duration: 5000 });
      },
    });
  }

  formatUserName(user: AdminUser | null | undefined): string {
    if (!user) {
      return '—';
    }

    const trimmed = user.name?.trim();
    return trimmed && trimmed.length > 0 ? trimmed : '—';
  }

  getRoleTooltip(role: RoleSummary): string {
    if (!role.permissions.length) {
      return `${role.name}\nNo permissions assigned.`;
    }

    return `${role.name}\n${role.permissions.join('\n')}`;
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

  private normalizeName(value: string | null | undefined): string {
    return value?.trim().toLowerCase() ?? '';
  }

  private markToggling(userId: number, toggling: boolean): void {
    this.togglingUserIds.update((current) => {
      const next = new Set(current);
      if (toggling) {
        next.add(userId);
      } else {
        next.delete(userId);
      }
      return next;
    });
  }

  private updateUserRow(userId: number, changes: Partial<AdminUser>): void {
    this.dataSource.data = this.dataSource.data.map((entry) =>
      entry.id === userId ? { ...entry, ...changes } : entry,
    );
    this.syncRoleFilterOptions(this.dataSource.data);
    this.applyFilterChanges(this.filterControl.value);
  }

  private composeRoleToggleKey(userId: number, role: string): string {
    return `${userId}:${role}`;
  }

  private clearRoleToggle(key: string): void {
    this.roleTogglesInFlight.update((current) => {
      const next = new Set(current);
      next.delete(key);
      return next;
    });
  }

  hasActiveFilters(): boolean {
    const current = this.composeFilterPayload(this.filterControl.value);
    return (
      current.term.length > 0 ||
      current.role !== this.filterDefaults.role ||
      current.status !== this.filterDefaults.status
    );
  }

  private applyFilterChanges(term: string): void {
    this.dataSource.filter = JSON.stringify(this.composeFilterPayload(term));
  }

  private composeFilterPayload(term: string): UserTableFilters {
    return {
      term: term.trim().toLowerCase(),
      role: this.roleFilterControl.value,
      status: this.statusFilterControl.value,
    };
  }

  private parseFilters(raw: string): UserTableFilters {
    if (!raw) {
      return { ...this.filterDefaults };
    }

    try {
      const parsed = JSON.parse(raw) as Partial<UserTableFilters> | null;
      return {
        term: typeof parsed?.term === 'string' ? parsed.term : this.filterDefaults.term,
        role: typeof parsed?.role === 'string' ? parsed.role : this.filterDefaults.role,
        status: this.normalizeStatus(parsed?.status),
      };
    } catch {
      return { ...this.filterDefaults };
    }
  }

  private normalizeStatus(value: unknown): UserStatusFilter {
    return value === 'active' || value === 'suspended' ? value : this.filterDefaults.status;
  }

  private syncRoleFilterOptions(users: AdminUser[]): void {
    const roleMap = new Map<string, string>();
    for (const role of this.availableRoles()) {
      roleMap.set(role.slug, role.name);
    }

    for (const user of users) {
      for (const role of user.roles) {
        if (!roleMap.has(role)) {
          roleMap.set(role, this.toTitleCase(role));
        }
      }
    }

    const currentRole = this.roleFilterControl.value;
    if (currentRole !== this.filterDefaults.role && !roleMap.has(currentRole)) {
      roleMap.set(currentRole, this.toTitleCase(currentRole));
    }

    const options: RoleFilterOption[] = Array.from(roleMap.entries())
      .map(([slug, name]) => ({ slug, name }))
      .sort((a, b) => a.name.localeCompare(b.name));

    this.roleFilterOptions.set(options);
  }

  private toTitleCase(value: string): string {
    return value
      .replace(/[-_]+/g, ' ')
      .split(' ')
      .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : ''))
      .join(' ')
      .trim() || value;
  }
}
