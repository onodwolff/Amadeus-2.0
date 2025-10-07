import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  OnChanges,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-equity-sparkline',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './equity-sparkline.component.html',
  styleUrls: ['./equity-sparkline.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EquitySparklineComponent implements AfterViewInit, OnChanges {
  @Input() series: readonly number[] | null = null;
  @Input() width = 120;
  @Input() height = 36;

  @ViewChild('canvas', { static: true }) private canvasRef!: ElementRef<HTMLCanvasElement>;

  private viewReady = false;

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.render();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.viewReady) {
      return;
    }
    if ('series' in changes || 'width' in changes || 'height' in changes) {
      this.render();
    }
  }

  private render(): void {
    const canvasElement = this.canvasRef?.nativeElement;
    if (!canvasElement) {
      return;
    }

    const context = canvasElement.getContext('2d');
    if (!context) {
      return;
    }

    const values = Array.isArray(this.series) ? this.series.filter((value) => Number.isFinite(value)) : [];
    if (values.length < 2) {
      const width = Math.max(1, Math.floor(this.width));
      const height = Math.max(1, Math.floor(this.height));
      canvasElement.width = width;
      canvasElement.height = height;
      canvasElement.style.width = `${this.width}px`;
      canvasElement.style.height = `${this.height}px`;
      context.clearRect(0, 0, width, height);
      return;
    }

    const pixelRatio = typeof window !== 'undefined' && window.devicePixelRatio ? window.devicePixelRatio : 1;
    const displayWidth = Math.max(1, Math.floor(this.width * pixelRatio));
    const displayHeight = Math.max(1, Math.floor(this.height * pixelRatio));
    canvasElement.width = displayWidth;
    canvasElement.height = displayHeight;
    canvasElement.style.width = `${this.width}px`;
    canvasElement.style.height = `${this.height}px`;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, this.width, this.height);

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 1e-6);
    const paddingX = 4;
    const paddingY = 6;
    const chartWidth = this.width - paddingX * 2;
    const chartHeight = this.height - paddingY * 2;

    context.beginPath();
    values.forEach((value, index) => {
      const x = paddingX + (index / (values.length - 1)) * chartWidth;
      const y = paddingY + chartHeight - ((value - min) / range) * chartHeight;
      if (index === 0) {
        context.moveTo(x, y);
      } else {
        context.lineTo(x, y);
      }
    });
    context.strokeStyle = '#facc15';
    context.lineWidth = 1.5;
    context.stroke();

    const lastValue = values[values.length - 1];
    const lastX = paddingX + chartWidth;
    const lastY = paddingY + chartHeight - ((lastValue - min) / range) * chartHeight;
    context.fillStyle = '#facc15';
    context.beginPath();
    context.arc(lastX, lastY, 2.5, 0, Math.PI * 2);
    context.fill();
  }
}
