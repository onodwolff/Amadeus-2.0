// User models

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  role: 'admin' | 'user'; // при необходимости добавь 'viewer'
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
  name?: string;
  role: 'admin' | 'user';
}

export interface AccountResponse {
  account: UserProfile;
}

export interface AccountUpdateRequest {
  name?: string;
  email?: string;
}

export interface PasswordUpdateRequest {
  currentPassword: string;
  newPassword: string;
}
