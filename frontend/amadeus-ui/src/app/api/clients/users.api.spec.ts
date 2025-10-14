import { TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';

import { UsersApi } from './users.api';

describe('UsersApi', () => {
  let api: UsersApi;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
    });

    api = TestBed.inject(UsersApi);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should call the admin disable MFA endpoint', () => {
    const userId = 42;
    let detail: string | undefined;

    api.disableUserMfa(userId).subscribe((result) => {
      detail = result.detail;
    });

    const request = httpMock.expectOne(
      'http://localhost:8000/api/admin/users/42/mfa/disable',
    );

    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({});

    request.flush({ detail: 'Two-factor authentication disabled.' });

    expect(detail).toBe('Two-factor authentication disabled.');
  });

  it('should call the admin revoke sessions endpoint', () => {
    const userId = 17;
    let detail: string | undefined;

    api.revokeUserSessions(userId).subscribe((result) => {
      detail = result.detail;
    });

    const request = httpMock.expectOne('http://localhost:8000/api/admin/users/17/logout');

    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({});

    request.flush({ detail: 'Sessions revoked.' });

    expect(detail).toBe('Sessions revoked.');
  });
});
