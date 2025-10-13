export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  oauth: {
    issuer: 'http://localhost:8000/realms/amadeus',
    clientId: 'amadeus-ui',
    redirectUri: 'http://localhost:4200',
    scope: 'openid profile email offline_access',
  },
};
