export interface UserProfile {
  id: string;
  name: string;
  email: string;
  role: string;
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
  name: string;
  password: string;
  role: string;
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
