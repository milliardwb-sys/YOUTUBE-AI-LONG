import React, { useState } from 'react';
import { ActivityIndicator, Button, SafeAreaView, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import {
  cancelJob,
  createProject,
  delay,
  deleteScene,
  getJob,
  getProject,
  getProjectManifest,
  insertScene,
  listProjects,
  loginUser,
  logoutUser,
  patchScene,
  registerUser,
  regenerateSceneSlide,
  retryJob,
  setAccessToken,
  startProjectJob,
} from './src/api';
import type { Project, ProjectJob, ProjectManifest, Scene, UserPublic } from './src/types';

export default function App() {
  const [topic, setTopic] = useState('5 AI-сервисов для создания видео в 2026 году');
  const [useOfficialSources, setUseOfficialSources] = useState(true);
  const [useLlmScript, setUseLlmScript] = useState(false);
  const [useTtsVoice, setUseTtsVoice] = useState(false);
  const [burnSubtitles, setBurnSubtitles] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [job, setJob] = useState<ProjectJob | null>(null);
  const [manifest, setManifest] = useState<ProjectManifest | null>(null);
  const [loading, setLoading] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authUser, setAuthUser] = useState<UserPublic | null>(null);
  const [authEmail, setAuthEmail] = useState('owner@example.com');
  const [authPassword, setAuthPassword] = useState('strong-password');
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
  const [sceneTitle, setSceneTitle] = useState('');
  const [sceneNarration, setSceneNarration] = useState('');
  const [sceneDuration, setSceneDuration] = useState('12');

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    setJob(null);
    setManifest(null);
    try {
      const created = await createProject({
        topic,
        useOfficialSources,
        useLlmScript,
        useTtsVoice,
        burnSubtitles,
      });
      setProject(created);
      await refreshProjects();

      const queuedJob = await startProjectJob(created.id, 'generate_all');
      setJob(queuedJob);
      await pollJob(created.id, queuedJob);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }

  async function handleAuth(action: 'login' | 'register') {
    setAuthBusy(true);
    setError(null);
    try {
      const payload = action === 'login'
        ? await loginUser(authEmail.trim(), authPassword)
        : await registerUser(authEmail.trim(), authPassword);
      setAuthUser(payload.user);
      await refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Auth failed');
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleLogout() {
    setAuthBusy(true);
    setError(null);
    try {
      await logoutUser();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Logout failed');
    } finally {
      setAccessToken(null);
      setAuthUser(null);
      setProjects([]);
      setProject(null);
      setJob(null);
      setManifest(null);
      setAuthBusy(false);
    }
  }

  async function refreshProjects() {
    setProjectsLoading(true);
    try {
      setProjects(await listProjects());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load projects failed');
    } finally {
      setProjectsLoading(false);
    }
  }

  function selectScene(scene: Scene | null) {
    setSelectedSceneId(scene?.id ?? null);
    setSceneTitle(scene?.title ?? '');
    setSceneNarration(scene?.narration ?? '');
    setSceneDuration(String(scene?.duration_sec ?? 12));
  }

  async function handleOpenProject(projectId: string) {
    setLoading(true);
    setError(null);
    setJob(null);
    try {
      const selected = await getProject(projectId);
      setProject(selected);
      setManifest(await getProjectManifest(projectId));
      selectScene(selected.scenes?.[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Open project failed');
    } finally {
      setLoading(false);
    }
  }

  async function pollJob(projectId: string, initialJob: ProjectJob) {
    let currentJob = initialJob;
    while (currentJob.status === 'queued' || currentJob.status === 'running') {
      await delay(1000);
      currentJob = await getJob(initialJob.id);
      setJob(currentJob);
      setProject(await getProject(projectId));
    }

    const finalProject = await getProject(projectId);
    setProject(finalProject);
    setManifest(await getProjectManifest(projectId));
    selectScene(finalProject.scenes?.[0] ?? null);
    await refreshProjects();
    if (currentJob.status === 'failed') {
      setError(currentJob.error ?? finalProject.error ?? 'Generation job failed');
    }
    if (currentJob.status === 'cancelled') {
      setError(currentJob.error ?? 'Generation job cancelled');
    }
  }

  async function handleCancelJob() {
    if (!job) return;
    setError(null);
    try {
      const cancelled = await cancelJob(job.id);
      setJob(cancelled);
      if (project) {
        setProject(await getProject(project.id));
        setManifest(await getProjectManifest(project.id));
        await refreshProjects();
      }
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cancel failed');
    }
  }

  async function handleRetryJob() {
    if (!job || !project) return;
    setLoading(true);
    setError(null);
    try {
      const retried = await retryJob(job.id);
      setJob(retried);
      setManifest(null);
      await pollJob(project.id, retried);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retry failed');
    } finally {
      setLoading(false);
    }
  }

  async function refreshActiveProject(updated: Project) {
    setProject(updated);
    setManifest(await getProjectManifest(updated.id));
    await refreshProjects();
  }

  async function handleSaveScene() {
    if (!project || !selectedSceneId) return;
    setLoading(true);
    setError(null);
    try {
      const duration = Math.max(5, Math.min(240, Number.parseInt(sceneDuration, 10) || 12));
      const updated = await patchScene(project.id, selectedSceneId, {
        title: sceneTitle.trim(),
        on_screen_text: sceneTitle.trim(),
        narration: sceneNarration.trim(),
        duration_sec: duration,
      });
      await refreshActiveProject(updated);
      selectScene(updated.scenes.find((scene) => scene.id === selectedSceneId) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save scene failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleAddScene() {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await insertScene(project.id, {
        title: sceneTitle.trim() || 'Manual scene',
        narration: sceneNarration.trim() || 'Manual narration for the new scene.',
        duration_sec: Math.max(5, Math.min(240, Number.parseInt(sceneDuration, 10) || 12)),
      });
      await refreshActiveProject(updated);
      selectScene(updated.scenes[updated.scenes.length - 1] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Add scene failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteScene() {
    if (!project || !selectedSceneId) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await deleteScene(project.id, selectedSceneId);
      await refreshActiveProject(updated);
      selectScene(updated.scenes[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete scene failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleRegenerateSceneSlide() {
    if (!project || !selectedSceneId) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await regenerateSceneSlide(project.id, selectedSceneId);
      await refreshActiveProject(updated);
      selectScene(updated.scenes.find((scene) => scene.id === selectedSceneId) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Regenerate slide failed');
    } finally {
      setLoading(false);
    }
  }

  const progress = job?.progress ?? (loading ? 2 : 0);
  const canCancel = job?.status === 'queued' || job?.status === 'running';
  const canRetry = job?.status === 'failed' || job?.status === 'cancelled';
  const selectedScene = project?.scenes?.find((scene) => scene.id === selectedSceneId) ?? null;

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="auto" />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>AI Video Studio MVP v0.4</Text>
        <Text style={styles.subtitle}>Тема → job queue → сценарий → источники → голос → слайды → MP4</Text>
        <View style={styles.authPanel}>
          <Text style={styles.sectionTitle}>Account</Text>
          {authUser ? (
            <View style={styles.authRow}>
              <Text style={styles.authText}>{authUser.email}</Text>
              <Button title="Logout" onPress={handleLogout} disabled={authBusy} />
            </View>
          ) : (
            <>
              <TextInput
                value={authEmail}
                onChangeText={setAuthEmail}
                style={styles.compactInput}
                placeholder="email"
                autoCapitalize="none"
                keyboardType="email-address"
              />
              <TextInput
                value={authPassword}
                onChangeText={setAuthPassword}
                style={styles.compactInput}
                placeholder="password"
                secureTextEntry
              />
              <View style={styles.buttonRow}>
                <Button
                  title="Login"
                  onPress={() => handleAuth('login')}
                  disabled={authBusy || authEmail.trim().length < 3 || authPassword.length < 1}
                />
                <Button
                  title="Register"
                  onPress={() => handleAuth('register')}
                  disabled={authBusy || authEmail.trim().length < 3 || authPassword.length < 8}
                />
              </View>
            </>
          )}
        </View>

        <Text style={styles.label}>Тема ролика</Text>
        <TextInput
          value={topic}
          onChangeText={setTopic}
          multiline
          style={styles.input}
          placeholder="Введите тему YouTube-ролика"
        />

        <View style={styles.projectListPanel}>
          <View style={styles.authRow}>
            <Text style={styles.sectionTitle}>Projects</Text>
            <Button title={projectsLoading ? 'Loading' : 'Refresh'} onPress={refreshProjects} disabled={projectsLoading || loading} />
          </View>
          {projects.length === 0 ? (
            <Text style={styles.emptyText}>No projects loaded</Text>
          ) : (
            projects.slice(0, 8).map((item) => (
              <View key={item.id} style={styles.projectListItem}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.projectListTitle}>{item.topic}</Text>
                  <Text style={styles.projectListMeta}>
                    {item.status} · {item.current_step}
                  </Text>
                  {item.updated_at ? <Text style={styles.projectListMeta}>{new Date(item.updated_at).toLocaleString()}</Text> : null}
                </View>
                <Button title="Open" onPress={() => handleOpenProject(item.id)} disabled={loading} />
              </View>
            ))
          )}
        </View>

        <OptionRow
          title="Официальные сайты + AI-слайды"
          hint="Без чужих YouTube-кадров"
          value={useOfficialSources}
          onValueChange={setUseOfficialSources}
        />
        <OptionRow
          title="LLM-сценарист"
          hint="Нужен OPENAI_API_KEY на backend; иначе fallback"
          value={useLlmScript}
          onValueChange={setUseLlmScript}
        />
        <OptionRow
          title="TTS-голос"
          hint="Нужен OPENAI_API_KEY; иначе audio-заглушка"
          value={useTtsVoice}
          onValueChange={setUseTtsVoice}
        />
        <OptionRow
          title="Встроить субтитры в видео"
          hint="Отдельные SRT/VTT создаются всегда"
          value={burnSubtitles}
          onValueChange={setBurnSubtitles}
        />

        <Button title="Создать ролик через job queue" onPress={handleGenerate} disabled={loading || topic.trim().length < 5} />
        {canCancel ? <Button title="Отменить job" onPress={handleCancelJob} /> : null}
        {canRetry ? <Button title="Повторить job" onPress={handleRetryJob} disabled={loading} /> : null}

        {loading && (
          <View style={styles.loading}>
            <ActivityIndicator />
            <Text style={styles.loadingText}>Генерация: {progress}%</Text>
            {job ? <Text style={styles.loadingText}>{job.current_step}</Text> : null}
            <View style={styles.progressOuter}>
              <View style={[styles.progressInner, { width: `${Math.max(1, progress)}%` }]} />
            </View>
          </View>
        )}

        {error && <Text style={styles.error}>{error}</Text>}

        {project && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>{project.topic}</Text>
            <Text>Project ID: {project.id}</Text>
            <Text>Status: {project.status}</Text>
            <Text>Step: {project.current_step}</Text>
            {job ? <Text>Job: {job.status} · {job.progress}% · {job.current_step}</Text> : null}
            {job?.events?.slice(-5).map((event, index) => (
              <Text key={`${event.created_at}-${index}`} style={styles.event}>
                {event.event}: {event.message ?? event.progress ?? ''}
              </Text>
            ))}
            <Text>Script: {project.script_provider ?? '—'}</Text>
            <Text>Voice: {project.voice_provider ?? '—'}</Text>
            <Text>Scenes: {project.scenes?.length ?? 0}</Text>
            <Text>Sources: {project.sources?.length ?? 0}</Text>
            <View style={styles.sceneEditorPanel}>
              <Text style={styles.cardTitle}>Scene editor</Text>
              {project.scenes?.length ? (
                project.scenes.slice(0, 8).map((scene) => (
                  <View key={scene.id} style={styles.scenePickerRow}>
                    <Text style={styles.scenePickerText}>
                      #{scene.order} {scene.title}
                    </Text>
                    <Button title={scene.id === selectedSceneId ? 'Selected' : 'Edit'} onPress={() => selectScene(scene)} />
                  </View>
                ))
              ) : (
                <Text style={styles.event}>No scenes yet</Text>
              )}
              <TextInput
                value={sceneTitle}
                onChangeText={setSceneTitle}
                style={styles.compactInput}
                placeholder="scene title"
              />
              <TextInput
                value={sceneNarration}
                onChangeText={setSceneNarration}
                multiline
                style={[styles.compactInput, styles.sceneNarrationInput]}
                placeholder="scene narration"
              />
              <TextInput
                value={sceneDuration}
                onChangeText={setSceneDuration}
                style={styles.compactInput}
                placeholder="duration seconds"
                keyboardType="numeric"
              />
              <View style={styles.buttonRow}>
                <Button title="Save" onPress={handleSaveScene} disabled={loading || !selectedScene || sceneTitle.trim().length < 1} />
                <Button title="Add" onPress={handleAddScene} disabled={loading || sceneTitle.trim().length < 1} />
              </View>
              <View style={styles.buttonRow}>
                <Button title="Delete" onPress={handleDeleteScene} disabled={loading || !selectedScene} />
                <Button title="Regen slide" onPress={handleRegenerateSceneSlide} disabled={loading || !selectedScene} />
              </View>
            </View>
            {manifest ? (
              <View style={styles.manifestBox}>
                <Text style={styles.manifestTitle}>Manifest: {manifest.readiness.publish_ready ? 'publish ready' : 'not ready'}</Text>
                <Text>Artifacts: {manifest.counts.ready_artifacts}/{manifest.counts.expected_artifacts}</Text>
                <Text>Visuals: {manifest.counts.scenes_with_visuals}/{manifest.counts.scenes}</Text>
                <Text>Voice: {manifest.counts.scenes_with_audio}/{manifest.counts.scenes}</Text>
                {manifest.missing_artifacts.length ? (
                  <Text style={styles.warning}>Missing: {manifest.missing_artifacts.join(', ')}</Text>
                ) : null}
              </View>
            ) : null}
            {project.result?.final_video_url ? (
              <Text style={styles.link}>Video: {project.result.final_video_url}</Text>
            ) : null}
            {project.result?.thumbnail_url ? (
              <Text style={styles.link}>Thumbnail: {project.result.thumbnail_url}</Text>
            ) : null}
            {project.result?.quality_report_url ? (
              <Text style={styles.link}>Quality: {project.result.quality_report_url}</Text>
            ) : null}
            {project.result?.export_package_url ? (
              <Text style={styles.link}>Package: {project.result.export_package_url}</Text>
            ) : null}
            {project.scenes?.slice(0, 5).map((scene) => (
              <Text key={scene.id} style={styles.scene}>#{scene.order} {scene.title} · {scene.visual_type}</Text>
            ))}
            {project.sources?.slice(0, 4).map((source) => (
              <Text key={source.id} style={styles.source}>• {source.name} — {source.status}</Text>
            ))}
            {project.result?.warnings?.map((warning, index) => (
              <Text key={index} style={styles.warning}>⚠ {warning}</Text>
            ))}
            {project.error ? <Text style={styles.error}>{project.error}</Text> : null}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

type OptionRowProps = {
  title: string;
  hint: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
};

function OptionRow({ title, hint, value, onValueChange }: OptionRowProps) {
  return (
    <View style={styles.switchRow}>
      <View style={{ flex: 1 }}>
        <Text style={styles.switchTitle}>{title}</Text>
        <Text style={styles.switchHint}>{hint}</Text>
      </View>
      <Switch value={value} onValueChange={onValueChange} />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#0f1220' },
  container: { padding: 24, gap: 16 },
  title: { fontSize: 30, fontWeight: '800', color: 'white' },
  subtitle: { fontSize: 16, color: '#c8d0ee' },
  authPanel: { backgroundColor: '#1d2440', borderRadius: 8, padding: 14, gap: 10 },
  projectListPanel: { backgroundColor: '#162034', borderRadius: 8, padding: 14, gap: 10 },
  sectionTitle: { color: 'white', fontWeight: '800', fontSize: 16 },
  authRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  authText: { color: '#e5e7eb', fontWeight: '700', flex: 1 },
  compactInput: {
    backgroundColor: 'white',
    color: '#111827',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
  },
  buttonRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  emptyText: { color: '#c8d0ee' },
  projectListItem: {
    backgroundColor: '#eef2ff',
    borderRadius: 8,
    padding: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  projectListTitle: { color: '#111827', fontWeight: '800' },
  projectListMeta: { color: '#475569', marginTop: 2, fontSize: 12 },
  label: { color: 'white', fontWeight: '700', marginTop: 16 },
  input: {
    minHeight: 110,
    backgroundColor: 'white',
    color: '#111827',
    borderRadius: 16,
    padding: 16,
    fontSize: 16,
  },
  switchRow: {
    backgroundColor: '#1d2440',
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  switchTitle: { color: 'white', fontWeight: '800', fontSize: 16 },
  switchHint: { color: '#c8d0ee', marginTop: 4 },
  loading: { gap: 8, alignItems: 'center', padding: 20 },
  loadingText: { color: 'white' },
  progressOuter: { width: '100%', height: 10, backgroundColor: '#242b46', borderRadius: 20, overflow: 'hidden' },
  progressInner: { height: 10, backgroundColor: '#7c8cff' },
  error: { color: '#ffb4b4', marginTop: 12 },
  warning: { color: '#8a5a00', marginTop: 8 },
  source: { color: '#334155', marginTop: 4 },
  scene: { color: '#334155', marginTop: 4 },
  event: { color: '#475569', marginTop: 3, fontSize: 12 },
  manifestBox: { backgroundColor: '#f8fafc', borderRadius: 10, padding: 12, gap: 4, marginTop: 6 },
  manifestTitle: { color: '#111827', fontWeight: '800' },
  sceneEditorPanel: { borderTopWidth: 1, borderTopColor: '#e5e7eb', paddingTop: 12, gap: 8, marginTop: 8 },
  scenePickerRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  scenePickerText: { color: '#334155', flex: 1 },
  sceneNarrationInput: { minHeight: 90, textAlignVertical: 'top' },
  card: { backgroundColor: 'white', padding: 18, borderRadius: 18, gap: 8, marginTop: 18 },
  cardTitle: { fontSize: 18, fontWeight: '800', color: '#111827' },
  link: { color: '#2457c5' },
});
