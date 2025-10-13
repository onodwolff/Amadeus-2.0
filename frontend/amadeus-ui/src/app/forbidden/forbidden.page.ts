import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

@Component({
  standalone: true,
  selector: 'app-forbidden-page',
  imports: [CommonModule, RouterLink],
  templateUrl: './forbidden.page.html',
  styleUrls: ['./forbidden.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ForbiddenPage {}
