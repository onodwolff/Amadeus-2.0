import { TestBed } from '@angular/core/testing';
import { Router, UrlTree } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';

import { AdminGuard } from './admin.guard';
import { AuthStateService } from './auth-state.service';

describe('AdminGuard', () => {
  let guard: AdminGuard;
  let authState: jasmine.SpyObj<AuthStateService>;
  let router: Router;

  beforeEach(() => {
    authState = jasmine.createSpyObj<AuthStateService>('AuthStateService', ['initialize', 'hasAnyPermission']);
    authState.initialize.and.resolveTo();

    TestBed.configureTestingModule({
      imports: [RouterTestingModule],
      providers: [{ provide: AuthStateService, useValue: authState }, AdminGuard],
    });

    guard = TestBed.inject(AdminGuard);
    router = TestBed.inject(Router);
  });

  it('allows access when the user has admin permissions', async () => {
    authState.hasAnyPermission.and.returnValue(true);

    await expectAsync(guard.canActivate()).toBeResolvedTo(true);
    expect(authState.initialize).toHaveBeenCalled();
  });

  it('redirects to /403 when the user lacks admin permissions', async () => {
    authState.hasAnyPermission.and.returnValue(false);

    const result = await guard.canActivate();

    expect(authState.initialize).toHaveBeenCalled();
    expect(result instanceof UrlTree).toBeTrue();
    expect(router.serializeUrl(result as UrlTree)).toEqual(router.serializeUrl(router.parseUrl('/403')));
  });
});
