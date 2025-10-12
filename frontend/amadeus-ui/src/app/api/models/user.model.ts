// User models

export interface UserProfile {
  id: string;
  name: string | null;
  email: string;
  role: 'admin' | 'member' | 'viewer';
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AdminUser {
  id: string;
  email: string;
  username: string;
  name: string | null;
  role: 'admin' | 'member' | 'viewer';
  isAdmin: boolean;
  emailVerified: boolean;
  mfaEnabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AdminUsersResponse {
  users: AdminUser[];
}

export interface UserResponse {
  user: UserProfile;
}

export interface UserCreateRequest {
  email: string;
  password: string;
  name?: string | null;
  role: 'admin' | 'member' | 'viewer';
}

export interface AccountResponse {
  account: UserProfile;
}

export interface AccountUpdateRequest {
  name?: string | null;
  email?: string;
}

export interface PasswordUpdateRequest {
  currentPassword: string;
  newPassword: string;
}
