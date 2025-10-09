import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { PagePlaceholderComponent } from '../../shared/page-placeholder.component';

@Component({
  standalone: true,
  selector: 'app-admin-users-page',
  imports: [CommonModule, PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="Admin users"
      description="Manage platform users and their permissions."
      hint="User management tools are coming soon."
    />
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminUsersPage {}
