export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  oauth: {
    issuer: 'http://localhost:8080/realms/amadeus',
    clientId: 'amadeus-spa',
    redirectUri: 'http://localhost:4200',
    scope: 'openid profile email offline_access',
  },
};
