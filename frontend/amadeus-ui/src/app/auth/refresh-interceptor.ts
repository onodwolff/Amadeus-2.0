import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { EMPTY, catchError, throwError } from 'rxjs';

const REFRESH_PATH = '/api/auth/refresh';

export const refreshInterceptor: HttpInterceptorFn = (req, next) =>
  next(req).pipe(
    catchError(error => {
      if (
        req.url.includes(REFRESH_PATH) &&
        error instanceof HttpErrorResponse &&
        error.status === 401
      ) {
        return EMPTY;
      }

      return throwError(() => error);
    }),
  );
