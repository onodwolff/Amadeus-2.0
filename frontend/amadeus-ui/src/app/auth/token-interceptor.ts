import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, from, switchMap, throwError } from 'rxjs';

import { AuthService } from './auth.service';

export const tokenInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const token = auth.getAccessToken();

  const authReq = token
    ? req.clone({
        setHeaders: {
          Authorization: `Bearer ${token}`,
        },
      })
    : req;

  return next(authReq).pipe(
    catchError(error => {
      if (
        !(error instanceof HttpErrorResponse) ||
        error.status !== 401 ||
        req.url.includes('/api/auth/refresh') ||
        req.url.includes('/api/auth/oidc/callback')
      ) {
        return throwError(() => error);
      }

      return from(auth.refreshToken()).pipe(
        switchMap(() => {
          const refreshedToken = auth.getAccessToken();
          if (!refreshedToken) {
            auth.logout();
            return throwError(() => error);
          }

          const retryRequest = req.clone({
            setHeaders: {
              Authorization: `Bearer ${refreshedToken}`,
            },
          });

          return next(retryRequest);
        }),
        catchError(refreshError => {
          auth.logout();
          return throwError(() => refreshError);
        }),
      );
    }),
  );
};
