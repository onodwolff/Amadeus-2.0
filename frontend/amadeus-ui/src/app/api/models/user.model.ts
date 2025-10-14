// User models

export interface PermissionSummary {
  code: string;
  name: string;
  description: string | null;
}

export interface RoleSummary {
  slug: string;
  name: string;
  description: string | null;
  permissions: string[];
}

export interface UserProfile {
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

export type AdminUser = UserProfile;

export interface UserCreateRequest {
  email: string;
  password: string;
  name?: string | null;
  username?: string | null;
  roles?: string[];
  active?: boolean;
}

export interface UserUpdateRequest {
  email?: string;
  username?: string;
  name?: string | null;
  roles?: string[];
  active?: boolean;
  password?: string;
}

export interface AccountUpdateRequest {
  email?: string;
  username?: string;
  name?: string | null;
}

export interface PasswordUpdateRequest {
  currentPassword: string;
  newPassword: string;
}
