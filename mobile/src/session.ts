import * as SecureStore from 'expo-secure-store';

const ACCESS_TOKEN_KEY = 'ai_video_studio_access_token';

export async function saveSessionToken(token: string): Promise<void> {
  if (!(await SecureStore.isAvailableAsync())) return;
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, token);
}

export async function loadSessionToken(): Promise<string | null> {
  if (!(await SecureStore.isAvailableAsync())) return null;
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
}

export async function clearSessionToken(): Promise<void> {
  if (!(await SecureStore.isAvailableAsync())) return;
  await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
}
