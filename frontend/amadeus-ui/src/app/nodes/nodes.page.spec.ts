import { Signal, WritableSignal, signal } from '@angular/core';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { NodesApi } from '../api/clients/nodes.api';
import { SystemApi } from '../api/clients/system.api';
import { IntegrationsApi } from '../api/clients/integrations.api';
import { KeysApi } from '../api/clients/keys.api';
import { NodeHandle } from '../api/models';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { WsConnectionState, WsService } from '../ws.service';
import { NodesPage } from './nodes.page';

describe('NodesPage (role-based UI)', () => {
  let rolesSignal: WritableSignal<string[]>;
  let permissionsSignal: WritableSignal<string[]>;

  const sampleNode: NodeHandle = {
    id: 'node-1',
    mode: 'live',
    status: 'running',
    detail: 'Sample node',
  };

  class MockWsService {
    channel() {
      return {
        messages$: of({ nodes: [sampleNode] }),
        state$: of('connected' as WsConnectionState),
      };
    }
  }

  beforeEach(async () => {
    rolesSignal = signal<string[]>([]);
    permissionsSignal = signal<string[]>([]);

    await TestBed.configureTestingModule({
      imports: [NodesPage],
      providers: [
        provideZonelessChangeDetection(),
        {
          provide: NodesApi,
          useValue: {
            listNodes: () => of({ nodes: [sampleNode] }),
            getNodeDetail: () => of({ node: sampleNode, config: {}, lifecycle: [] }),
            getNodeLogs: () => of({ logs: [] }),
            launchNode: jasmine.createSpy('launchNode').and.returnValue(of({})),
            stopNode: jasmine.createSpy('stopNode').and.returnValue(of({})),
            restartNode: jasmine.createSpy('restartNode').and.returnValue(of({})),
            deleteNode: jasmine.createSpy('deleteNode').and.returnValue(of({})),
          } satisfies Partial<NodesApi>,
        },
        {
          provide: SystemApi,
          useValue: {
            health: () => of({ status: 'ok', env: 'test' }),
            coreInfo: () => of({ nautilus_version: '1.0.0', available: true }),
          } satisfies Partial<SystemApi>,
        },
        { provide: WsService, useClass: MockWsService },
        {
          provide: AuthStateService,
          useValue: {
            permissions: permissionsSignal as Signal<string[]>,
            roles: rolesSignal as Signal<string[]>,
            hasRole: (role: string) => rolesSignal().includes(role),
          } satisfies Partial<AuthStateService> & {
            permissions: Signal<string[]>;
            roles: Signal<string[]>;
            hasRole: (role: string) => boolean;
          },
        },
        {
          provide: KeysApi,
          useValue: {
            listKeys: () => of({ keys: [] }),
          } satisfies Partial<KeysApi>,
        },
        {
          provide: IntegrationsApi,
          useValue: {
            listExchanges: () => of({ exchanges: [] }),
          } satisfies Partial<IntegrationsApi>,
        },
      ],
    }).compileComponents();
  });

  it('hides launch controls and node actions for non-trader users', () => {
    const fixture = TestBed.createComponent(NodesPage);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.querySelector('.nodes-page__launch')).toBeNull();
    expect(compiled.querySelector('[data-testid="nodes-controls-locked"]')).not.toBeNull();
  });
});
