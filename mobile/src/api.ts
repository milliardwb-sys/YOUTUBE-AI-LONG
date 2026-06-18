import type {
  AuditEvent,
  AuthToken,
  JobEvent,
  JobType,
  Project,
  ProjectJob,
  ProjectManifest,
  SceneCreate,
  ScenePatch,
  UserPublic,
} from './types';

declare const process: {
  env?: Record<string, string | undefined>;
};

const API_BASE_URL = process.env?.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
const API_KEY = process.env?.EXPO_PUBLIC_API_KEY;
let accessToken: string | null = null;

export type CreateProjectOptions = {
  topic: string;
  useOfficialSources: boolean;
  useLlmScript: boolean;
  useTtsVoice: boolean;
  burnSubtitles: boolean;
};

async function assertOk(response: Response, label: string) {
  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = typeof payload.detail === 'string' ? `: ${payload.detail}` : `: ${JSON.stringify(payload.detail ?? payload)}`;
    } catch {
      detail = '';
    }
    throw new Error(`${label} failed: ${response.status}${detail}`);
  }
}

type ApiHeaders = Record<string, string>;

function headers(extra?: ApiHeaders): ApiHeaders {
  return {
    ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(extra ?? {}),
  };
}

function idempotencyKey(prefix: string): string {
  return `${prefix}:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 10)}`;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export async function registerUser(email: string, password: string): Promise<AuthToken> {
  const response = await fetch(`${API_BASE_URL}/auth/register`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ email, password }),
  });
  await assertOk(response, 'Register');
  const payload = await response.json();
  setAccessToken(payload.access_token);
  return payload;
}

export async function loginUser(email: string, password: string): Promise<AuthToken> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ email, password }),
  });
  await assertOk(response, 'Login');
  const payload = await response.json();
  setAccessToken(payload.access_token);
  return payload;
}

export async function getCurrentUser(): Promise<UserPublic> {
  const response = await fetch(`${API_BASE_URL}/auth/me`, { headers: headers() });
  await assertOk(response, 'Get current user');
  return response.json();
}

export async function logoutUser(): Promise<{ revoked: boolean }> {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: 'POST',
    headers: headers(),
  });
  await assertOk(response, 'Logout');
  return response.json();
}

export async function createProject(options: CreateProjectOptions): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects`, {
    method: 'POST',
    headers: headers({
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey('project-create'),
    }),
    body: JSON.stringify({
      topic: options.topic,
      duration_minutes: 3,
      style: 'expert_review',
      language: 'ru',
      audience: 'создатели YouTube-каналов',
      visual_mode: options.useOfficialSources ? 'official_sites_plus_ai' : 'ai_slides_only',
      source_urls: options.useOfficialSources ? ['https://www.heygen.com/', 'https://runwayml.com/'] : [],
      script_provider: options.useLlmScript ? 'openai' : 'template',
      voice_provider: options.useTtsVoice ? 'openai' : 'placeholder',
      voice_id: 'alloy',
      brand_theme: 'neon',
      avatar_enabled: false,
      burn_subtitles: options.burnSubtitles,
    }),
  });
  await assertOk(response, 'Create project');
  return response.json();
}

export async function listProjects(): Promise<Project[]> {
  const response = await fetch(`${API_BASE_URL}/projects?limit=50&offset=0`, { headers: headers() });
  await assertOk(response, 'List projects');
  return response.json();
}

export async function generateAll(projectId: string): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/generate-all`, {
    method: 'POST',
    headers: headers(),
  });
  await assertOk(response, 'Generation');
  return response.json();
}

export async function startProjectJob(projectId: string, jobType: JobType = 'generate_all'): Promise<ProjectJob> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/jobs/${jobType}`, {
    method: 'POST',
    headers: headers({ 'Idempotency-Key': idempotencyKey(`job-start-${jobType}`) }),
  });
  await assertOk(response, 'Start job');
  return response.json();
}

export async function getJob(jobId: string): Promise<ProjectJob> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`, { headers: headers() });
  await assertOk(response, 'Get job');
  return response.json();
}

export async function getJobEvents(jobId: string): Promise<JobEvent[]> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}/events?limit=100&offset=0`, { headers: headers() });
  await assertOk(response, 'Get job events');
  return response.json();
}

export async function cancelJob(jobId: string): Promise<ProjectJob> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}/cancel`, {
    method: 'POST',
    headers: headers(),
  });
  await assertOk(response, 'Cancel job');
  return response.json();
}

export async function retryJob(jobId: string): Promise<ProjectJob> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}/retry`, {
    method: 'POST',
    headers: headers(),
  });
  await assertOk(response, 'Retry job');
  return response.json();
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}`, { headers: headers() });
  await assertOk(response, 'Get project');
  return response.json();
}

export async function getProjectManifest(projectId: string): Promise<ProjectManifest> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/manifest`, { headers: headers() });
  await assertOk(response, 'Get project manifest');
  return response.json();
}

export async function getAuditEvents(): Promise<AuditEvent[]> {
  const response = await fetch(`${API_BASE_URL}/audit/events?limit=100&offset=0`, { headers: headers() });
  await assertOk(response, 'Get audit events');
  return response.json();
}

export async function patchScene(projectId: string, sceneId: string, payload: ScenePatch): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/scenes/${sceneId}`, {
    method: 'PATCH',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  await assertOk(response, 'Patch scene');
  return response.json();
}

export async function insertScene(projectId: string, payload: SceneCreate): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/scenes`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ visual_type: 'ai_slide', ...payload }),
  });
  await assertOk(response, 'Insert scene');
  return response.json();
}

export async function deleteScene(projectId: string, sceneId: string): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/scenes/${sceneId}`, {
    method: 'DELETE',
    headers: headers(),
  });
  await assertOk(response, 'Delete scene');
  return response.json();
}

export async function regenerateSceneSlide(projectId: string, sceneId: string): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/scenes/${sceneId}/regenerate-slide`, {
    method: 'POST',
    headers: headers(),
  });
  await assertOk(response, 'Regenerate scene slide');
  return response.json();
}

export async function reorderScenes(projectId: string, sceneIds: string[]): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/scenes/reorder`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ scene_ids: sceneIds }),
  });
  await assertOk(response, 'Reorder scenes');
  return response.json();
}

export async function duplicateProject(projectId: string): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/duplicate`, {
    method: 'POST',
    headers: headers({ 'Idempotency-Key': idempotencyKey('project-duplicate') }),
  });
  await assertOk(response, 'Duplicate project');
  return response.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}`, { method: 'DELETE', headers: headers() });
  await assertOk(response, 'Delete project');
}

export function delay(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(() => resolve(), ms);
  });
}
