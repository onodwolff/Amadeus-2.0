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

export interface UsersResponse {
  users: UserProfile[];
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
