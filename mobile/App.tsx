import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Button, SafeAreaView, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import {
  cancelJob,
  createProject,
  delay,
  deleteProject,
  deleteScene,
  duplicateProject,
  getAuditEvents,
  getCurrentUser,
  getJob,
  getProject,
  getProjectManifest,
  getUsageMe,
  insertScene,
  listProjects,
  loginUser,
  logoutUser,
  patchScene,
  registerUser,
  regenerateSceneSlide,
  reorderScenes,
  retryJob,
  setAccessToken,
  startProjectJob,
} from './src/api';
import { clearSessionToken, loadSessionToken, saveSessionToken } from './src/session';
import type { AuditEvent, Project, ProjectJob, ProjectManifest, Scene, UsageOverview, UserPublic } from './src/types';

export default function App() {
  const [topic, setTopic] = useState('AI-аватар показывает 5 сервисов для создания YouTube-видео в 2026 году');
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
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [usage, setUsage] = useState<UsageOverview | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authUser, setAuthUser] = useState<UserPublic | null>(null);
  const [authEmail, setAuthEmail] = useState('owner@example.com');
  const [authPassword, setAuthPassword] = useState('strong-password');
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
  const [sceneTitle, setSceneTitle] = useState('');
  const [sceneNarration, setSceneNarration] = useState('');
  const [sceneDuration, setSceneDuration] = useState('12');

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      setAuthBusy(true);
      try {
        const token = await loadSessionToken();
        if (!active || !token) return;
        setAccessToken(token);
        const user = await getCurrentUser();
        if (!active) return;
        setAuthUser(user);
        await refreshProjects();
        await refreshAuditEvents();
        await refreshUsage();
      } catch {
        setAccessToken(null);
        await clearSessionToken();
      } finally {
        if (active) setAuthBusy(false);
      }
    }

    restoreSession();
    return () => {
      active = false;
    };
  }, []);

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
      await refreshAuditEvents();
      await refreshUsage();

      const queuedJob = await startProjectJob(created.id, 'generate_all');
      setJob(queuedJob);
      await pollJob(created.id, queuedJob);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Неизвестная ошибка');
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
      await saveSessionToken(payload.access_token);
      setAuthUser(payload.user);
      await refreshProjects();
      await refreshAuditEvents();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка авторизации');
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
      setError(err instanceof Error ? err.message : 'Не удалось выйти');
    } finally {
      await clearSessionToken();
      setAccessToken(null);
      setAuthUser(null);
      setProjects([]);
      setAuditEvents([]);
      setUsage(null);
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
      setError(err instanceof Error ? err.message : 'Не удалось загрузить проекты');
    } finally {
      setProjectsLoading(false);
    }
  }

  async function refreshAuditEvents() {
    setAuditLoading(true);
    try {
      setAuditEvents(await getAuditEvents());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить аудит');
    } finally {
      setAuditLoading(false);
    }
  }

  async function refreshUsage() {
    setUsageLoading(true);
    try {
      setUsage(await getUsageMe());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить лимиты');
    } finally {
      setUsageLoading(false);
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
      await refreshAuditEvents();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось открыть проект');
    } finally {
      setLoading(false);
    }
  }

  async function handleDuplicateProject() {
    if (!project) return;
    setLoading(true);
    setError(null);
    setJob(null);
    try {
      const copy = await duplicateProject(project.id);
      setProject(copy);
      setManifest(await getProjectManifest(copy.id));
      selectScene(copy.scenes?.[0] ?? null);
      await refreshProjects();
      await refreshAuditEvents();
      await refreshUsage();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скопировать проект');
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteProject() {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await deleteProject(project.id);
      setProject(null);
      setJob(null);
      setManifest(null);
      selectScene(null);
      await refreshProjects();
      await refreshAuditEvents();
      await refreshUsage();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось удалить проект');
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
    await refreshAuditEvents();
    await refreshUsage();
    if (currentJob.status === 'failed') {
      setError(currentJob.error ?? finalProject.error ?? 'Задача генерации завершилась ошибкой');
    }
    if (currentJob.status === 'cancelled') {
      setError(currentJob.error ?? 'Задача генерации отменена');
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
        await refreshAuditEvents();
        await refreshUsage();
      }
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось отменить задачу');
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
      await refreshAuditEvents();
      await refreshUsage();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось повторить задачу');
    } finally {
      setLoading(false);
    }
  }

  async function refreshActiveProject(updated: Project) {
    setProject(updated);
    setManifest(await getProjectManifest(updated.id));
    await refreshProjects();
    await refreshAuditEvents();
    await refreshUsage();
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
      setError(err instanceof Error ? err.message : 'Не удалось сохранить сцену');
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
        title: sceneTitle.trim() || 'Ручная сцена',
        narration: sceneNarration.trim() || 'Ручной текст диктора для новой сцены.',
        duration_sec: Math.max(5, Math.min(240, Number.parseInt(sceneDuration, 10) || 12)),
      });
      await refreshActiveProject(updated);
      selectScene(updated.scenes[updated.scenes.length - 1] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось добавить сцену');
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
      setError(err instanceof Error ? err.message : 'Не удалось удалить сцену');
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
      setError(err instanceof Error ? err.message : 'Не удалось пересобрать кадр');
    } finally {
      setLoading(false);
    }
  }

  async function handleMoveScene(direction: -1 | 1) {
    if (!project || !selectedSceneId) return;
    const currentIndex = project.scenes.findIndex((scene) => scene.id === selectedSceneId);
    const targetIndex = currentIndex + direction;
    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= project.scenes.length) return;
    setLoading(true);
    setError(null);
    try {
      const sceneIds = project.scenes.map((scene) => scene.id);
      const [moved] = sceneIds.splice(currentIndex, 1);
      sceneIds.splice(targetIndex, 0, moved);
      const updated = await reorderScenes(project.id, sceneIds);
      await refreshActiveProject(updated);
      selectScene(updated.scenes.find((scene) => scene.id === selectedSceneId) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось переместить сцену');
    } finally {
      setLoading(false);
    }
  }

  const progress = job?.progress ?? (loading ? 2 : 0);
  const canCancel = job?.status === 'queued' || job?.status === 'running';
  const canRetry = job?.status === 'failed' || job?.status === 'cancelled';
  const selectedScene = project?.scenes?.find((scene) => scene.id === selectedSceneId) ?? null;
  const selectedSceneIndex = project?.scenes?.findIndex((scene) => scene.id === selectedSceneId) ?? -1;
  const canMoveSceneUp = selectedSceneIndex > 0;
  const canMoveSceneDown = Boolean(project?.scenes && selectedSceneIndex >= 0 && selectedSceneIndex < project.scenes.length - 1);

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="auto" />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>YOUTUBE AI LONG</Text>
        <Text style={styles.subtitle}>Тема → очередь задач → сценарий → источники → AI-ведущий → MP4</Text>
        <View style={styles.authPanel}>
          <Text style={styles.sectionTitle}>Аккаунт</Text>
          {authUser ? (
            <View style={styles.authRow}>
              <Text style={styles.authText}>{authUser.email}</Text>
              <Button title="Выйти" onPress={handleLogout} disabled={authBusy} />
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
                placeholder="пароль"
                secureTextEntry
              />
              <View style={styles.buttonRow}>
                <Button
                  title="Войти"
                  onPress={() => handleAuth('login')}
                  disabled={authBusy || authEmail.trim().length < 3 || authPassword.length < 1}
                />
                <Button
                  title="Создать аккаунт"
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
            <Text style={styles.sectionTitle}>Проекты</Text>
            <Button title={projectsLoading ? 'Загрузка' : 'Обновить'} onPress={refreshProjects} disabled={projectsLoading || loading} />
          </View>
          {projects.length === 0 ? (
            <Text style={styles.emptyText}>Проекты не загружены</Text>
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
                <Button title="Открыть" onPress={() => handleOpenProject(item.id)} disabled={loading} />
              </View>
            ))
          )}
        </View>

        <View style={styles.usagePanel}>
          <View style={styles.authRow}>
            <Text style={styles.sectionTitle}>Лимиты</Text>
            <Button title={usageLoading ? 'Загрузка' : 'Обновить'} onPress={refreshUsage} disabled={usageLoading || loading} />
          </View>
          {usage ? (
            <>
              <Text style={styles.usageText}>
                Проекты: {usage.limits.current_projects}/{usage.limits.max_projects || '∞'}
              </Text>
              <Text style={styles.usageText}>
                Активные задачи: {usage.limits.current_active_jobs}/{usage.limits.max_active_jobs || '∞'}
              </Text>
              <Text style={styles.usageText}>
                Оценка стоимости: ${(usage.usage.estimated_cost_cents / 100).toFixed(2)}
              </Text>
              <Text style={styles.usageMeta}>События: {usage.usage.event_count} · Единицы: {usage.usage.total_units}</Text>
            </>
          ) : (
            <Text style={styles.emptyText}>Лимиты не загружены</Text>
          )}
        </View>

        <View style={styles.auditPanel}>
          <View style={styles.authRow}>
            <Text style={styles.sectionTitle}>Журнал аудита</Text>
            <Button title={auditLoading ? 'Загрузка' : 'Обновить'} onPress={refreshAuditEvents} disabled={auditLoading || loading} />
          </View>
          {auditEvents.length === 0 ? (
            <Text style={styles.emptyText}>События аудита не загружены</Text>
          ) : (
            auditEvents.slice(0, 8).map((event) => (
              <View key={event.id} style={styles.auditItem}>
                <Text style={styles.auditAction}>{event.action}</Text>
                <Text style={styles.auditMeta}>
                  {event.resource_type}{event.resource_id ? ` · ${event.resource_id}` : ''}
                </Text>
                <Text style={styles.auditMeta}>{new Date(event.created_at).toLocaleString()}</Text>
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

        <Button title="Создать ролик с AI-ведущим" onPress={handleGenerate} disabled={loading || topic.trim().length < 5} />
        {canCancel ? <Button title="Отменить задачу" onPress={handleCancelJob} /> : null}
        {canRetry ? <Button title="Повторить задачу" onPress={handleRetryJob} disabled={loading} /> : null}

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
            <Text>ID проекта: {project.id}</Text>
            <Text>Статус: {project.status}</Text>
            <Text>Шаг: {project.current_step}</Text>
            <View style={styles.buttonRow}>
              <Button title="Копировать" onPress={handleDuplicateProject} disabled={loading} />
              <Button title="Удалить" onPress={handleDeleteProject} disabled={loading} />
            </View>
            {job ? <Text>Задача: {job.status} · {job.progress}% · {job.current_step}</Text> : null}
            {job?.events?.slice(-5).map((event, index) => (
              <Text key={`${event.created_at}-${index}`} style={styles.event}>
                {event.event}: {event.message ?? event.progress ?? ''}
              </Text>
            ))}
            <Text>Сценарий: {project.script_provider ?? '—'}</Text>
            <Text>Голос: {project.voice_provider ?? '—'}</Text>
            <Text>Сцен: {project.scenes?.length ?? 0}</Text>
            <Text>Источников: {project.sources?.length ?? 0}</Text>
            <View style={styles.sceneEditorPanel}>
              <Text style={styles.cardTitle}>Редактор сцен</Text>
              {project.scenes?.length ? (
                project.scenes.slice(0, 8).map((scene) => (
                  <View key={scene.id} style={styles.scenePickerRow}>
                    <Text style={styles.scenePickerText}>
                      #{scene.order} {scene.title}
                    </Text>
                    <Button title={scene.id === selectedSceneId ? 'Выбрана' : 'Править'} onPress={() => selectScene(scene)} />
                  </View>
                ))
              ) : (
                <Text style={styles.event}>Сцен пока нет</Text>
              )}
              <TextInput
                value={sceneTitle}
                onChangeText={setSceneTitle}
                style={styles.compactInput}
                placeholder="название сцены"
              />
              <TextInput
                value={sceneNarration}
                onChangeText={setSceneNarration}
                multiline
                style={[styles.compactInput, styles.sceneNarrationInput]}
                placeholder="текст диктора"
              />
              <TextInput
                value={sceneDuration}
                onChangeText={setSceneDuration}
                style={styles.compactInput}
                placeholder="длительность в секундах"
                keyboardType="numeric"
              />
              <View style={styles.buttonRow}>
                <Button title="Сохранить" onPress={handleSaveScene} disabled={loading || !selectedScene || sceneTitle.trim().length < 1} />
                <Button title="Добавить" onPress={handleAddScene} disabled={loading || sceneTitle.trim().length < 1} />
              </View>
              <View style={styles.buttonRow}>
                <Button title="Удалить" onPress={handleDeleteScene} disabled={loading || !selectedScene} />
                <Button title="Пересобрать кадр" onPress={handleRegenerateSceneSlide} disabled={loading || !selectedScene} />
              </View>
              <View style={styles.buttonRow}>
                <Button title="Выше" onPress={() => handleMoveScene(-1)} disabled={loading || !canMoveSceneUp} />
                <Button title="Ниже" onPress={() => handleMoveScene(1)} disabled={loading || !canMoveSceneDown} />
              </View>
            </View>
            {manifest ? (
              <View style={styles.manifestBox}>
                <Text style={styles.manifestTitle}>Манифест: {manifest.readiness.publish_ready ? 'готов к публикации' : 'не готов'}</Text>
                <Text>Артефакты: {manifest.counts.ready_artifacts}/{manifest.counts.expected_artifacts}</Text>
                <Text>Визуалы: {manifest.counts.scenes_with_visuals}/{manifest.counts.scenes}</Text>
                <Text>Голос: {manifest.counts.scenes_with_audio}/{manifest.counts.scenes}</Text>
                {manifest.missing_artifacts.length ? (
                  <Text style={styles.warning}>Не хватает: {manifest.missing_artifacts.join(', ')}</Text>
                ) : null}
              </View>
            ) : null}
            {project.result?.final_video_url ? (
              <Text style={styles.link}>Видео: {project.result.final_video_url}</Text>
            ) : null}
            {project.result?.thumbnail_url ? (
              <Text style={styles.link}>Обложка: {project.result.thumbnail_url}</Text>
            ) : null}
            {project.result?.quality_report_url ? (
              <Text style={styles.link}>Отчет качества: {project.result.quality_report_url}</Text>
            ) : null}
            {project.result?.avatar_manifest_url ? (
              <Text style={styles.link}>Манифест аватара: {project.result.avatar_manifest_url}</Text>
            ) : null}
            {project.result?.visual_assets_manifest_url ? (
              <Text style={styles.link}>Манифест визуалов: {project.result.visual_assets_manifest_url}</Text>
            ) : null}
            {project.result?.export_package_url ? (
              <Text style={styles.link}>Пакет экспорта: {project.result.export_package_url}</Text>
            ) : null}
            {project.scenes?.slice(0, 5).map((scene) => (
              <Text key={scene.id} style={styles.scene}>
                #{scene.order} {scene.title} · {scene.visual_type}{scene.avatar_video_status ? ` · аватар: ${scene.avatar_video_status}` : ''}
              </Text>
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
  usagePanel: { backgroundColor: '#1f2a19', borderRadius: 8, padding: 14, gap: 8 },
  auditPanel: { backgroundColor: '#132b2f', borderRadius: 8, padding: 14, gap: 10 },
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
  auditItem: { backgroundColor: '#ecfeff', borderRadius: 8, padding: 10 },
  auditAction: { color: '#0f172a', fontWeight: '800' },
  auditMeta: { color: '#475569', marginTop: 2, fontSize: 12 },
  usageText: { color: '#ecfccb', fontWeight: '700' },
  usageMeta: { color: '#d9f99d', fontSize: 12 },
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
