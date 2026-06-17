export type ProjectStatus =
  | 'draft'
  | 'queued'
  | 'researching'
  | 'sources_ready'
  | 'script_ready'
  | 'visuals_ready'
  | 'voice_ready'
  | 'rendering'
  | 'completed'
  | 'cancelled'
  | 'failed';

export type JobStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed';
export type JobType =
  | 'generate_script'
  | 'collect_sources'
  | 'generate_slides'
  | 'generate_voice'
  | 'prepare_avatar'
  | 'render'
  | 'generate_all';

export type ProjectJob = {
  id: string;
  project_id: string;
  owner_id?: string | null;
  type: JobType;
  status: JobStatus;
  progress: number;
  current_step: string;
  error?: string | null;
  events?: JobEvent[];
  result_project_status?: ProjectStatus | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type JobEvent = {
  event: string;
  message?: string | null;
  progress?: number | null;
  created_at: string;
};

export type ProjectArtifact = {
  key: string;
  path?: string | null;
  url?: string | null;
  exists: boolean;
  size_bytes: number;
};

export type ProjectManifest = {
  project_id: string;
  topic: string;
  status: ProjectStatus;
  current_step: string;
  error?: string | null;
  warnings: string[];
  counts: {
    scenes: number;
    sources: number;
    scenes_with_visuals: number;
    scenes_with_audio: number;
    sources_with_screenshots: number;
    expected_artifacts: number;
    ready_artifacts: number;
    missing_artifacts: number;
  };
  readiness: {
    script: boolean;
    sources: boolean;
    visuals: boolean;
    voice: boolean;
    render: boolean;
    export_package: boolean;
    publish_ready: boolean;
  };
  artifacts: ProjectArtifact[];
  missing_artifacts: string[];
};

export type SourceCandidate = {
  id: string;
  name: string;
  url: string;
  kind: string;
  status: string;
  screenshot_url?: string | null;
};

export type Scene = {
  id: string;
  order: number;
  title: string;
  goal?: string;
  narration?: string;
  on_screen_text?: string;
  visual_type: 'ai_slide' | 'screenshot' | 'table' | 'diagram';
  start_sec: number;
  duration_sec: number;
  source_name?: string | null;
  visual_url?: string | null;
  audio_url?: string | null;
};

export type ScenePatch = {
  title?: string;
  narration?: string;
  duration_sec?: number;
  on_screen_text?: string;
};

export type SceneCreate = {
  title: string;
  narration: string;
  duration_sec: number;
  visual_type?: Scene['visual_type'];
};

export type Project = {
  id: string;
  owner_id?: string | null;
  topic: string;
  duration_minutes: number;
  status: ProjectStatus;
  current_step: string;
  script_provider?: 'template' | 'openai';
  voice_provider?: 'placeholder' | 'openai';
  brand_theme?: 'dark' | 'light' | 'neon';
  burn_subtitles?: boolean;
  error?: string | null;
  scenes: Scene[];
  sources: SourceCandidate[];
  result: {
    final_video_url?: string | null;
    subtitles_url?: string | null;
    captions_vtt_url?: string | null;
    description_url?: string | null;
    sources_url?: string | null;
    storyboard_url?: string | null;
    thumbnail_prompt_url?: string | null;
    thumbnail_url?: string | null;
    quality_report_url?: string | null;
    title_options_url?: string | null;
    youtube_metadata_url?: string | null;
    voice_manifest_url?: string | null;
    render_manifest_url?: string | null;
    export_package_url?: string | null;
    warnings?: string[];
  };
  created_at?: string;
  updated_at?: string;
};

export type UserPublic = {
  id: string;
  email: string;
  name?: string | null;
  created_at: string;
};

export type AuthToken = {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: UserPublic;
};
