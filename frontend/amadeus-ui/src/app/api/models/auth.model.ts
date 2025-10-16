export interface AuthUser {
  id: number;
  email: string;
  username: string;
  name: string | null;
  roles: string[];
  permissions: string[];
  active: boolean;
  isAdmin: boolean;
  emailVerified: boolean;
  mfaEnabled: boolean;
  createdAt: string;
  updatedAt: string;
  lastLoginAt: string | null;
}

export interface EmailChangeRequest {
  newEmail: string;
  password: string;
}

export interface EmailChangeResponse {
  verificationToken: string;
}

export interface EmailChangeConfirmRequest {
  token: string;
}

export interface MfaSetupResponse {
  secret: string;
  otpauthUrl: string;
}

export interface MfaEnableRequest {
  code: string;
}

export interface MfaEnableResponse {
  detail: string;
  backupCodes: string[];
}

export interface MfaDisableRequest {
  password?: string;
  code?: string;
}

export interface MfaBackupCodesRequest {
  password?: string;
  code?: string;
}

export interface BackupCodesResponse {
  detail?: string;
  backupCodes: string[];
}

export interface MfaChallengeResponse {
  challengeToken: string;
  detail: string;
  methods: string[];
  ttlSeconds: number;
}

export interface MfaChallengeRequest {
  challengeToken: string;
  code: string;
  rememberDevice?: boolean;
}

export interface PasswordLoginRequest {
  email: string;
  password: string;
  captchaToken?: string | null;
}

export interface TokenResponse {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  refreshExpiresAt: string;
  user: AuthUser;
}

export interface OperationStatus {
  detail: string;
}

export interface OidcCallbackRequest {
  code: string;
  codeVerifier: string;
  redirectUri?: string;
  state?: string;
  nonce: string;
}

export interface SessionsRevokeRequest {
  password: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  newPassword: string;
}
