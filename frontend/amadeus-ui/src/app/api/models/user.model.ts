export interface UserProfile {
  id: string;
  name: string;
  email: string;
  username: string;
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

export interface UserUpdateRequest {
  name?: string;
  email?: string;
  username?: string;
  password?: string;
}
