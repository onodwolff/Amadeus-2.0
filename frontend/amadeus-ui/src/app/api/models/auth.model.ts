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
  mfaEnabled?: boolean;
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

export interface MfaDisableRequest {
  password?: string;
  code?: string;
}

export interface OperationStatus {
  detail: string;
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
