import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  Input,
  OnChanges,
  SimpleChanges,
  ViewChild,
} from '@angular/core';

@Component({
  selector: 'app-position-sparkline',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './position-sparkline.component.html',
  styleUrls: ['./position-sparkline.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PositionSparklineComponent implements AfterViewInit, OnChanges {
  @Input() values: readonly number[] = [];

  @ViewChild('canvas', { static: true }) private readonly canvas?: ElementRef<HTMLCanvasElement>;

  private viewReady = false;

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.render();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['values']) {
      this.render();
    }
  }

  @HostListener('window:resize')
  onWindowResize(): void {
    this.render();
  }

  private render(): void {
    if (!this.viewReady || !this.canvas) {
      return;
    }

    const canvas = this.canvas.nativeElement;
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const width = rect.width || 120;
    const height = rect.height || 44;
    const dpr =
      typeof window !== 'undefined' && window.devicePixelRatio ? window.devicePixelRatio : 1;
    const displayWidth = Math.max(1, Math.floor(width * dpr));
    const displayHeight = Math.max(1, Math.floor(height * dpr));

    if (canvas.width !== displayWidth || canvas.height !== displayHeight) {
      canvas.width = displayWidth;
      canvas.height = displayHeight;
    }

    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);

    const values = Array.isArray(this.values) ? this.values : [];
    if (values.length === 0) {
      return;
    }

    const background = context.createLinearGradient(0, 0, 0, height);
    background.addColorStop(0, 'rgba(15, 23, 42, 0.85)');
    background.addColorStop(1, 'rgba(15, 23, 42, 0.55)');
    context.fillStyle = background;
    context.fillRect(0, 0, width, height);

    if (values.length === 1) {
      const value = values[0];
      const min = Math.min(value, 0);
      const max = Math.max(value, 0);
      const range = Math.max(max - min, 1e-6);
      const padding = { top: 6, bottom: 6, left: 4, right: 4 };
      const chartHeight = Math.max(1, height - padding.top - padding.bottom);
      const y = padding.top + chartHeight - ((value - min) / range) * chartHeight;
      const x = padding.left + (width - padding.left - padding.right) / 2;
      context.fillStyle = value >= 0 ? '#34d399' : '#f87171';
      context.beginPath();
      context.arc(x, y, 3, 0, Math.PI * 2);
      context.fill();
      return;
    }

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 1e-6);

    const padding = { top: 6, bottom: 6, left: 4, right: 4 };
    const chartWidth = Math.max(1, width - padding.left - padding.right);
    const chartHeight = Math.max(1, height - padding.top - padding.bottom);

    const rising = values[values.length - 1] >= values[0];
    const strokeColor = rising ? '#34d399' : '#f87171';
    const fillColor = rising ? 'rgba(52, 211, 153, 0.22)' : 'rgba(248, 113, 113, 0.22)';

    const points = values.map((value, index) => {
      const ratio = values.length === 1 ? 0.5 : index / (values.length - 1);
      const x = padding.left + ratio * chartWidth;
      const y = padding.top + chartHeight - ((value - min) / range) * chartHeight;
      return { x, y };
    });

    if (!points.length) {
      return;
    }

    context.lineWidth = 1.8;
    context.lineJoin = 'round';
    context.lineCap = 'round';
    context.strokeStyle = strokeColor;
    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) {
        context.moveTo(point.x, point.y);
      } else {
        context.lineTo(point.x, point.y);
      }
    });
    context.stroke();

    const firstPoint = points[0];
    const lastPoint = points.at(-1);
    if (!firstPoint || !lastPoint) {
      return;
    }

    context.beginPath();
    context.moveTo(firstPoint.x, padding.top + chartHeight);
    points.forEach(point => context.lineTo(point.x, point.y));
    context.lineTo(lastPoint.x, padding.top + chartHeight);
    context.closePath();
    context.fillStyle = fillColor;
    context.fill();

    if (min < 0 && max > 0) {
      const zeroRatio = (0 - min) / range;
      const zeroY = padding.top + chartHeight - zeroRatio * chartHeight;
      context.save();
      context.setLineDash([3, 3]);
      context.strokeStyle = 'rgba(148, 163, 184, 0.45)';
      context.beginPath();
      context.moveTo(padding.left, zeroY);
      context.lineTo(padding.left + chartWidth, zeroY);
      context.stroke();
      context.restore();
    }

    const latest = points.at(-1);
    if (!latest) {
      return;
    }
    context.fillStyle = '#e2e8f0';
    context.beginPath();
    context.arc(latest.x, latest.y, 2.4, 0, Math.PI * 2);
    context.fill();
  }
}
