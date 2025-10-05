import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import {
  NodeConfiguration,
  NodeDetailResponse,
  NodeHandle,
  NodeLifecycleEvent,
  NodeLogEntry,
} from '../api/models';
import { WsConnectionState } from '../ws.service';

@Component({
  selector: 'app-node-detail',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './node-detail.component.html',
  styleUrls: ['./node-detail.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeDetailComponent {
  @Input() node: NodeHandle | null = null;
  @Input() detail: NodeDetailResponse | null = null;
  @Input() lifecycle: NodeLifecycleEvent[] | null = null;
  @Input() logs: NodeLogEntry[] | null = null;
  @Input() isLoadingDetail = false;
  @Input() isLoadingLogs = false;
  @Input() detailError: string | null = null;
  @Input() logsError: string | null = null;
  @Input() logStreamState: WsConnectionState = 'connecting';
  @Input() isRestarting = false;
  @Input() isStopping = false;
  @Input() isDownloadingLogs = false;

  @Output() readonly close = new EventEmitter<void>();
  @Output() readonly restart = new EventEmitter<void>();
  @Output() readonly stop = new EventEmitter<void>();
  @Output() readonly downloadLogs = new EventEmitter<void>();

  readonly trackLifecycle = (_: number, item: NodeLifecycleEvent) => `${item.timestamp}-${item.status}`;
  readonly trackLog = (_: number, item: NodeLogEntry) => item.id;

  get hasLifecycle(): boolean {
    return Array.isArray(this.lifecycle) && this.lifecycle.length > 0;
  }

  get hasLogs(): boolean {
    return Array.isArray(this.logs) && this.logs.length > 0;
  }

  get configuration(): NodeConfiguration | null {
    return this.detail?.config ?? null;
  }
}
