export const environment = {
  production: true,
  /**
   * Optional base URL for backend HTTP and WebSocket requests.
   * When not provided, the application will default to the current origin.
   */
  apiBaseUrl: undefined as string | undefined,
  oauth: {
    issuer: undefined as string | undefined,
    clientId: undefined as string | undefined,
    redirectUri: undefined as string | undefined,
    scope: 'openid profile email offline_access',
  },
};
