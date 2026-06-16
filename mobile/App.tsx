import React, { useState } from 'react';
import { ActivityIndicator, Button, SafeAreaView, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { cancelJob, createProject, delay, getJob, getProject, retryJob, startProjectJob } from './src/api';
import type { Project, ProjectJob } from './src/types';

export default function App() {
  const [topic, setTopic] = useState('5 AI-сервисов для создания видео в 2026 году');
  const [useOfficialSources, setUseOfficialSources] = useState(true);
  const [useLlmScript, setUseLlmScript] = useState(false);
  const [useTtsVoice, setUseTtsVoice] = useState(false);
  const [burnSubtitles, setBurnSubtitles] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [job, setJob] = useState<ProjectJob | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    setJob(null);
    try {
      const created = await createProject({
        topic,
        useOfficialSources,
        useLlmScript,
        useTtsVoice,
        burnSubtitles,
      });
      setProject(created);

      const queuedJob = await startProjectJob(created.id, 'generate_all');
      setJob(queuedJob);
      await pollJob(created.id, queuedJob);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
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
      await pollJob(project.id, retried);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retry failed');
    } finally {
      setLoading(false);
    }
  }

  const progress = job?.progress ?? (loading ? 2 : 0);
  const canCancel = job?.status === 'queued' || job?.status === 'running';
  const canRetry = job?.status === 'failed' || job?.status === 'cancelled';

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="auto" />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>AI Video Studio MVP v0.4</Text>
        <Text style={styles.subtitle}>Тема → job queue → сценарий → источники → голос → слайды → MP4</Text>

        <Text style={styles.label}>Тема ролика</Text>
        <TextInput
          value={topic}
          onChangeText={setTopic}
          multiline
          style={styles.input}
          placeholder="Введите тему YouTube-ролика"
        />

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
            <Text>Script: {project.script_provider ?? '—'}</Text>
            <Text>Voice: {project.voice_provider ?? '—'}</Text>
            <Text>Scenes: {project.scenes?.length ?? 0}</Text>
            <Text>Sources: {project.sources?.length ?? 0}</Text>
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
  card: { backgroundColor: 'white', padding: 18, borderRadius: 18, gap: 8, marginTop: 18 },
  cardTitle: { fontSize: 18, fontWeight: '800', color: '#111827' },
  link: { color: '#2457c5' },
});
