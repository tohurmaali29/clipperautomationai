// app.js
const selected = {
    clip: null,
    recommendations: [],
    currentUrl: '',
    currentSourceType: 'youtube',
    currentLocalPath: '',
    currentClipPath: '',
    sourceDuration: 0,
    recommendedClip: null,
    timelineMax: 0,
    exportAspect: '9:16',
    exportDuration: 30,
    selectedClips: {},
    generatedClips: [],
    selectedGeneratedClipPath: '',
    selectedGeneratedClipPaths: [],
    heatmapCandidates: [],
    subtitleEnabled: true,
    subtitleFont: 'Arial Black',
    subtitleColor: '#FFFFFF',
    subtitleOutlineColor: '#000000',
    subtitlePosition: 'middle',
    subtitleSize: 'medium',
    isGenerating: false,
    activeClipKey: ''
};

let previewSeekTimeout = null;
const trackedSeekVideos = new WeakSet();
let draggedSubtitleRow = null;
let slowProcessTimer = null;
const HISTORY_STORAGE_KEY = 'ai_video_clipper_history_v1';

document.addEventListener('DOMContentLoaded', () => {
    const statusDiv = document.getElementById('status');
    const statusTitle = document.getElementById('status-title');

    const analyzeBtn = document.getElementById('analyze-btn');
    const generateClipButtons = document.querySelectorAll('#generate-clip-btn');
    const exportAspectButtons = document.querySelectorAll('.export-aspect-btn');
    const exportDurationButtons = document.querySelectorAll('.export-duration-btn');
    const exportDurationInput = document.getElementById('export-duration-input');
    const urlInput = document.getElementById('url');
    const transcriptBadge = document.getElementById('transcript-badge');
    const analysisBadge = document.getElementById('analysis-badge');
    const modeBadge = document.getElementById('mode-badge');
    const heatmapBadge = document.getElementById('heatmap-badge');
    const processingPanel = document.getElementById('processing-panel');
    const processingMessage = document.getElementById('processing-message');
    const resultsShell = document.getElementById('results-shell');
    const controlsSection = document.getElementById('controls-section');
    const exportSection = document.getElementById('export-section');
    const sourcePreview = document.getElementById('source-preview');
    const clipPreview = document.getElementById('clip-preview');
    const workspacePlaceholder = document.getElementById('workspace-placeholder');
    const trimStartInput = document.getElementById('trim-start-input');
    const trimEndInput = document.getElementById('trim-end-input');
    const generateManualBtn = document.getElementById('generate-manual-btn');
    const analyzeUploadBtn = document.getElementById('analyze-upload-btn');
    const localFileInput = document.getElementById('local-file');
    const backToEditorBtn = document.getElementById('back-to-editor-btn');
    const clearHistoryBtn = document.getElementById('clear-history-btn');
    const navToggle = document.getElementById('nav-toggle');
    const navOverlay = document.getElementById('nav-overlay');
    const navMenu = document.getElementById('studio-nav-menu');
    const navHome = document.getElementById('nav-home');
    const navWorkspace = document.getElementById('nav-workspace');
    const navHistory = document.getElementById('nav-history');

    const closeMobileNav = () => {
        if (!navToggle || !navMenu) {
            return;
        }
        navToggle.classList.remove('is-open');
        navMenu.classList.remove('is-open');
        navOverlay?.classList.remove('is-open');
        navToggle.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('nav-drawer-open');
    };

    navToggle?.addEventListener('click', () => {
        if (!navMenu) {
            return;
        }
        const isOpen = navMenu.classList.toggle('is-open');
        navToggle.classList.toggle('is-open', isOpen);
        navOverlay?.classList.toggle('is-open', isOpen);
        navToggle.setAttribute('aria-expanded', String(isOpen));
        document.body.classList.toggle('nav-drawer-open', isOpen);
    });

    navOverlay?.addEventListener('click', closeMobileNav);
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeMobileNav();
        }
    });

    exportAspectButtons.forEach(button => {
        button.addEventListener('click', () => {
            exportAspectButtons.forEach(btn => btn.classList.remove('is-active'));
            button.classList.add('is-active');
            selected.exportAspect = button.dataset.aspect;
            statusDiv.textContent = `Export ratio set to ${selected.exportAspect}.`;
            if (statusTitle) statusTitle.textContent = 'Export ratio updated';
        });
    });

    exportDurationButtons.forEach(button => {
        button.addEventListener('click', () => {
            exportDurationButtons.forEach(btn => btn.classList.remove('is-active'));
            button.classList.add('is-active');
            if (button.dataset.duration === 'custom') {
                exportDurationInput?.classList.remove('hidden');
                const customValue = Number(exportDurationInput?.value || selected.exportDuration || 30);
                selected.exportDuration = Math.max(5, customValue);
                refreshExportDurationPreview();
            } else {
                exportDurationInput?.classList.add('hidden');
                selected.exportDuration = Math.max(5, Number(button.dataset.duration || 30));
                refreshExportDurationPreview();
            }
        });
    });

    exportDurationInput?.addEventListener('input', () => {
        const customValue = Number(exportDurationInput.value || 30);
        selected.exportDuration = Math.max(5, customValue);
        refreshExportDurationPreview();
    });

    analyzeBtn.addEventListener('click', async () => {
        const url = urlInput.value.trim();
        const mode = 'viral';
        const duration = 30;

        if (!url) {
            statusDiv.textContent = 'Please enter a valid YouTube URL first.';
            if (statusTitle) statusTitle.textContent = 'Input required';
            focusPrimaryFeedback();
            return;
        }

        statusDiv.textContent = 'Analyzing transcript and preparing AI insights...';
        if (statusTitle) statusTitle.textContent = 'Analyzing your video...';
        selected.currentUrl = url;
        selected.currentSourceType = 'youtube';
        selected.currentLocalPath = '';
        selected.currentClipPath = '';
        selected.sourceDuration = 0;
        selected.selectedClips = {};
        selected.generatedClips = [];
        selected.selectedGeneratedClipPath = '';
        selected.selectedGeneratedClipPaths = [];
        selected.clip = null;
        selected.recommendedClip = null;
        selected.heatmapCandidates = [];
        selected.activeClipKey = '';
        resetGeneratedClips();
        hideGeneratedPage();
        setProcessingState(true, 'Getting transcript, extracting timing, and preparing AI insights.');
        setProcessingProgress(14, 'Getting transcript, extracting timing, and preparing AI insights.');
        setBadge(transcriptBadge, 'Transcript Loading', false);
        setBadge(analysisBadge, 'AI Loading', false);
        setBadge(modeBadge, 'Processing', false);
        setBadge(heatmapBadge, 'Heatmap Loading', false);

        try {
            const response = await fetch('/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, mode, duration })
            });
            const data = await response.json();

            if (!response.ok) {
                const detail = data.detail || data.error || 'Analyze failed';
                statusDiv.textContent = `Error: ${detail} If YouTube access is blocked, try Analyze Local with your own file.`;
                if (statusTitle) statusTitle.textContent = 'Analyze failed';
                setBadge(transcriptBadge, 'Transcript Failed', false);
                setBadge(analysisBadge, 'AI Waiting', false);
                setBadge(modeBadge, 'Stopped', false);
                setBadge(heatmapBadge, 'Heatmap Skipped', false);
                focusPrimaryFeedback();
                return;
            }

            setProcessingState(false);
            revealResults();
            showSourcePreview(url);
            selected.recommendations = data.clips || [];
            selected.sourceDuration = Number(data.metadata?.source_duration || data.pipeline?.transcript?.source_duration || 0);
            selected.heatmapCandidates = data.pipeline?.transcript?.heatmap_candidates || [];
            displayRecommendations(selected.recommendations);
            updatePipelineStatus(data.pipeline, data.metadata);
            setupTrimEditor(selected.recommendations, selected.sourceDuration);
            updateWorkspaceTimeline(null);
            statusDiv.textContent = buildStatusMessage(data.metadata);
            if (statusTitle) statusTitle.textContent = 'Analysis complete';
        } catch (error) {
            setProcessingState(false);
            statusDiv.textContent = `Error: ${error.message}`;
            if (statusTitle) statusTitle.textContent = 'Analyze error';
            setBadge(modeBadge, 'Error', false);
            focusPrimaryFeedback();
        }
    });

    analyzeUploadBtn?.addEventListener('click', async () => {
        const file = localFileInput?.files?.[0];
        if (!file) {
            statusDiv.textContent = 'Please choose a local video or audio file first.';
            if (statusTitle) statusTitle.textContent = 'Input required';
            focusPrimaryFeedback();
            return;
        }

        selected.currentUrl = '';
        selected.currentSourceType = 'local';
        selected.currentLocalPath = '';
        selected.currentClipPath = '';
        selected.sourceDuration = 0;
        selected.selectedClips = {};
        selected.generatedClips = [];
        selected.selectedGeneratedClipPath = '';
        selected.selectedGeneratedClipPaths = [];
        selected.clip = null;
        selected.recommendedClip = null;
        selected.heatmapCandidates = [];
        selected.activeClipKey = '';
        resetGeneratedClips();
        hideGeneratedPage();
        setProcessingState(true, 'Uploading local file, transcribing with Whisper, and preparing AI insights.');
        setProcessingProgress(14, 'Uploading local file, transcribing with Whisper, and preparing AI insights.');
        setBadge(transcriptBadge, 'Transcript Loading', false);
        setBadge(analysisBadge, 'AI Loading', false);
        setBadge(modeBadge, 'Processing', false);
        setBadge(heatmapBadge, 'Heatmap Off', false);

        const formData = new FormData();
        formData.append('file', file);
        formData.append('mode', 'viral');
        formData.append('duration', '30');

        try {
            const response = await fetch('/analyze-upload', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (!response.ok) {
                const detail = data.detail || data.error || 'Analyze upload failed';
                statusDiv.textContent = `Error: ${detail}`;
                if (statusTitle) statusTitle.textContent = 'Analyze failed';
                setBadge(transcriptBadge, 'Transcript Failed', false);
                setBadge(analysisBadge, 'AI Waiting', false);
                setBadge(modeBadge, 'Stopped', false);
                setBadge(heatmapBadge, 'Heatmap Off', false);
                setProcessingState(false);
                focusPrimaryFeedback();
                return;
            }

            selected.currentLocalPath = data.metadata?.local_path || '';
            selected.sourceDuration = Number(data.metadata?.source_duration || data.pipeline?.transcript?.source_duration || 0);
            setProcessingState(false);
            revealResults();
            showLocalSourcePreview(selected.currentLocalPath, 0);
            selected.recommendations = data.clips || [];
            selected.heatmapCandidates = [];
            displayRecommendations(selected.recommendations);
            updatePipelineStatus(data.pipeline, data.metadata);
            setupTrimEditor(selected.recommendations, selected.sourceDuration);
            updateWorkspaceTimeline(null);
            statusDiv.textContent = 'Local video analyzed successfully. Select a clip to continue.';
            if (statusTitle) statusTitle.textContent = 'Analysis complete';
        } catch (error) {
            setProcessingState(false);
            statusDiv.textContent = `Error: ${error.message}`;
            if (statusTitle) statusTitle.textContent = 'Analyze error';
            setBadge(modeBadge, 'Error', false);
            focusPrimaryFeedback();
        }
    });

    generateClipButtons.forEach(button => {
        button.addEventListener('click', async () => {
            const clipsToGenerate = collectSelectedClips();
            await generateClips(clipsToGenerate, 'Select at least one clip recommendation before generating.');
        });
    });

    generateManualBtn?.addEventListener('click', async () => {
        if (!selected.clip) {
            statusDiv.textContent = 'Select or adjust a clip in the trim editor first.';
            focusPrimaryFeedback();
            return;
        }
        const manualClip = {
            ...selected.clip,
            title: selected.clip.title || 'Manual Trim Clip',
            headline: selected.clip.headline || selected.clip.title || 'Manual Trim Clip',
        };
        await generateClips([manualClip], 'Adjust the trim first before generating from manual range.');
    });

    backToEditorBtn?.addEventListener('click', () => {
        hideGeneratedPage();
        hideHistoryPage();
        revealResults();
        document.getElementById('results-shell')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    navHome?.addEventListener('click', () => {
        closeMobileNav();
        hideGeneratedPage();
        hideHistoryPage();
        hideResults();
        document.getElementById('home-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    navWorkspace?.addEventListener('click', () => {
        closeMobileNav();
        hideGeneratedPage();
        hideHistoryPage();
        revealResults();
        document.getElementById('results-shell')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    navHistory?.addEventListener('click', () => {
        closeMobileNav();
        hideGeneratedPage();
        hideResults();
        showHistoryPage();
        document.getElementById('history-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    clearHistoryBtn?.addEventListener('click', () => {
        localStorage.removeItem(HISTORY_STORAGE_KEY);
        renderHistory();
        statusDiv.textContent = 'History has been cleared from this browser.';
        if (statusTitle) statusTitle.textContent = 'History cleared';
        focusPrimaryFeedback();
    });

    // Download button handler
    document.getElementById('download-btn')?.addEventListener('click', () => {
        const paths = selected.selectedGeneratedClipPaths?.length
            ? selected.selectedGeneratedClipPaths
            : [document.getElementById('download-btn').dataset.clipPath || selected.selectedGeneratedClipPath].filter(Boolean);
        paths.forEach((clipPath, index) => {
            const filename = extractFilename(clipPath);
            if (filename) {
                window.setTimeout(() => triggerDownload(filename), index * 220);
            }
        });
        statusDiv.textContent = paths.length > 1 ? `${paths.length} clip(s) are downloading.` : 'The clip is downloading.';
        if (statusTitle) statusTitle.textContent = 'Download started';
        focusPrimaryFeedback();
    });

    // Preview button handler
    document.getElementById('preview-btn')?.addEventListener('click', () => {
        if (selected.currentClipPath) {
            hideGeneratedPage();
            revealResults();
            showGeneratedClipPreview(selected.currentClipPath);
            document.getElementById('workspace-frame')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }

        if (selected.currentUrl) {
            showSourcePreview(selected.currentUrl);
            document.getElementById('workspace-frame')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }

        if (selected.currentLocalPath) {
            showLocalSourcePreview(selected.currentLocalPath, selected.clip?.start || 0);
            document.getElementById('workspace-frame')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    });

    if (workspacePlaceholder && sourcePreview && clipPreview) {
        showWorkspacePlaceholder();
    }

    attachSeekPlaybackBehavior(clipPreview);

    trimStartInput?.addEventListener('input', () => {
        syncManualTrim('start');
    });

    trimEndInput?.addEventListener('input', () => {
        syncManualTrim('end');
    });

    setProcessingState(false);
    hideGeneratedPage();
    hideHistoryPage();
    hideResults();
    renderHistory();
    bindHistoryActions();
    updateGenerateButtons();
});

function displayRecommendations(clips) {
    const container = document.getElementById('recommendations');
    container.innerHTML = '';

    if (!clips.length) {
        container.innerHTML = '<div class="rounded-[24px] border border-slate-800 bg-slate-900/80 p-5 text-slate-400">No clip recommendations found. Try another video.</div>';
        return;
    }

    clips.forEach((clip) => {
        const clipKey = getClipKey(clip);
        const exportPreviewClip = applyExportDurationToClip(clip);
        const isSelected = Boolean(selected.selectedClips[clipKey]);
        const isActive = selected.activeClipKey === clipKey;
        const card = document.createElement('button');
        card.type = 'button';
        card.className = `recommendation-card w-full rounded-[24px] border border-slate-800 bg-slate-900/80 p-5 text-left transition hover:border-sky-400 hover:bg-slate-900 ${isActive ? 'is-active' : ''}`;
        card.innerHTML = `
            <div class="flex items-center justify-between gap-4">
                <div>
                    <h3 class="text-lg font-semibold text-white">${clip.title}</h3>
                    <p class="mt-2 text-sm text-slate-400">${softenClipSummary(clip.summary || clip.reason || clip.title)}</p>
                    <p class="mt-2 text-xs uppercase tracking-[0.16em] text-slate-500">${clip.reason}</p>
                </div>
                <span class="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">Score ${clip.score}</span>
            </div>
            <div class="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-400">
                <span>${formatSeconds(exportPreviewClip.start)} - ${formatSeconds(exportPreviewClip.end)}</span>
                <span class="recommendation-select-chip rounded-full bg-slate-800 px-3 py-1">Select</span>
            </div>
        `;

        card.addEventListener('click', () => {
            const existing = selected.selectedClips[clipKey];
            selected.activeClipKey = clipKey;
            selected.recommendedClip = { ...clip };
            selected.clip = applyExportDurationToClip(selected.recommendedClip);
            applyClipSelection(selected.clip);
            if (existing) {
                delete selected.selectedClips[clipKey];
            } else {
                selected.selectedClips[clipKey] = { ...clip };
            }
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = `${Object.keys(selected.selectedClips).length} clip selected.`;
            updateGenerateButtons();
            if (!Object.keys(selected.selectedClips).length) {
                updateWorkspaceTimeline(selected.clip || null);
            }
            displayRecommendations(selected.recommendations);
        });

        setRecommendationCardState(card, isSelected);
        container.appendChild(card);
    });
}

function updatePipelineStatus(pipeline, metadata) {
    const transcriptIsReal = ['youtube', 'yt_dlp', 'whisper'].includes(pipeline?.transcript?.source);
    const analysisIsReal = !pipeline?.analysis?.used_fallback && metadata?.analysis_source !== 'mock';
    const demoMode = Boolean(metadata?.demo_mode);
    const transcriptCacheHit = Boolean(pipeline?.transcript?.cache_hit);
    const analysisCacheHit = Boolean(pipeline?.analysis?.cache_hit);
    const heatmapCount = Number(metadata?.heatmap_candidates_used || 0);

    setBadge(
        document.getElementById('transcript-badge'),
        transcriptIsReal ? (transcriptCacheHit ? 'Transcript Cached' : 'Transcript Live') : 'Transcript Mock',
        transcriptIsReal
    );
    setBadge(
        document.getElementById('analysis-badge'),
        analysisIsReal ? (analysisCacheHit ? 'AI Cached' : 'AI Live') : 'AI Fallback',
        analysisIsReal
    );
    setBadge(
        document.getElementById('mode-badge'),
        demoMode ? 'Demo Mode' : 'Live Mode',
        !demoMode
    );
    setBadge(
        document.getElementById('heatmap-badge'),
        heatmapCount > 0 ? `Heatmap ${heatmapCount}` : 'Heatmap Off',
        heatmapCount > 0
    );

    const heatmapSummary = document.getElementById('heatmap-summary');
    if (heatmapSummary) {
        heatmapSummary.textContent = heatmapCount > 0
            ? `AI used ${heatmapCount} heatmap peak candidates before final scoring.`
            : 'Heatmap is not available for this video, so the AI analyzed the transcript normally.';
    }
}

function buildStatusMessage(metadata) {
    if (!metadata) {
        return 'Analysis complete. Select a clip card to prepare export.';
    }

    const transcriptCacheLabel = metadata.cache?.transcript ? 'cached' : 'fresh';
    const analysisCacheLabel = metadata.cache?.analysis ? 'cached' : 'fresh';

    if (metadata.demo_mode) {
        return `Analysis complete in demo mode. Transcript: ${metadata.transcript_source} (${transcriptCacheLabel}), AI: ${metadata.analysis_source} (${analysisCacheLabel}), heatmap peaks: ${metadata.heatmap_candidates_used || 0}.`;
    }

    return `Analysis complete in live mode. Transcript: ${metadata.transcript_source} (${transcriptCacheLabel}), AI: ${metadata.analysis_source} (${analysisCacheLabel}), heatmap peaks: ${metadata.heatmap_candidates_used || 0}.`;
}

function setProcessingProgress(percent = 10, message = '') {
    const bar = document.getElementById('processing-bar');
    const label = document.getElementById('processing-progress-label');
    const processingMessage = document.getElementById('processing-message');
    const safePercent = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
    if (bar) {
        bar.style.width = `${safePercent}%`;
        bar.dataset.progress = String(safePercent);
    }
    if (label) {
        label.textContent = `${safePercent}%`;
    }
    if (processingMessage && message) {
        processingMessage.textContent = message;
    }

    const processingHint = document.getElementById('processing-hint');
    if (processingHint && selected.sourceDuration >= 900) {
        processingHint.classList.remove('hidden');
    }
}

function buildSubtitleStylePayload() {
    return {
        font: 'Arial Black',
        color: '#FFFFFF',
        outline_color: '#000000',
        bold: true,
        position: 'middle',
        size_preset: 'medium'
    };
}

function applyExportDurationToClip(clip) {
    const requestedDuration = Math.max(5, Number(selected.exportDuration || 30));
    const sourceLimit = Number(selected.sourceDuration || selected.timelineMax || 0);
    const start = Math.max(0, Number(clip?.start || 0));
    const boundedEnd = sourceLimit > 0
        ? Math.min(sourceLimit, start + requestedDuration)
        : (start + requestedDuration);

    return {
        ...clip,
        end: Math.max(start + 1, boundedEnd),
        end_time: formatSeconds(Math.max(start + 1, boundedEnd)),
    };
}

function refreshExportDurationPreview() {
    if (!selected.recommendations?.length) {
        return;
    }

    displayRecommendations(selected.recommendations);

    if (selected.recommendedClip) {
        selected.clip = applyExportDurationToClip(selected.recommendedClip);
        setTrimInputs(selected.clip.start, selected.clip.end);
        updateWorkspaceTimeline(selected.clip);
    }

    const statusDiv = document.getElementById('status');
    const statusTitle = document.getElementById('status-title');
    if (statusTitle) {
        statusTitle.textContent = 'Export duration updated';
    }
    if (statusDiv) {
        statusDiv.textContent = `Selected clips will export with ${selected.exportDuration}s duration unless you use manual trim.`;
    }
}

function setBadge(element, label, isPositive) {
    if (!element) {
        return;
    }

    element.textContent = label;
    element.classList.remove('bg-emerald-600/15', 'text-emerald-200', 'bg-amber-500/15', 'text-amber-200', 'bg-slate-900/80', 'text-slate-400');
    if (isPositive) {
        element.classList.add('bg-emerald-600/15', 'text-emerald-200');
    } else {
        element.classList.add('bg-amber-500/15', 'text-amber-200');
    }
}

function showDownloadSection(clip, clipPath) {
    const downloadSection = document.getElementById('download-section');
    const clipTitle = document.getElementById('clip-title');
    const clipDetails = document.getElementById('clip-details');
    const downloadBtn = document.getElementById('download-btn');

    if (downloadSection && clipTitle && clipDetails && downloadBtn) {
        clipTitle.textContent = clip.title || 'Generated Clip';
        clipDetails.textContent = `${softenClipSummary(clip.summary || clip.reason || clip.title)} (${clip.start_time} - ${clip.end_time})`;
        downloadBtn.dataset.clipPath = clipPath;
        downloadSection.classList.remove('hidden');
        const selectedCount = selected.selectedGeneratedClipPaths?.length || 0;
        downloadBtn.textContent = selectedCount > 1 ? `Download ${selectedCount} Clip` : 'Download MP4';
    }
}

function focusPrimaryFeedback() {
    const processingPanel = document.getElementById('processing-panel');
    const statusShell = document.getElementById('status-shell');
    const generatedSection = document.getElementById('download-section');
    const historySection = document.getElementById('history-section');

    if (processingPanel && !processingPanel.classList.contains('hidden')) {
        processingPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }
    if (generatedSection && !generatedSection.classList.contains('hidden')) {
        generatedSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }
    if (historySection && !historySection.classList.contains('hidden')) {
        historySection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }
    statusShell?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateGenerateButtons() {
    const selectedCount = Object.keys(selected.selectedClips || {}).length;
    const generateBtn = document.getElementById('generate-clip-btn');
    const manualBtn = document.getElementById('generate-manual-btn');
    if (generateBtn) {
        generateBtn.textContent = selectedCount > 0 ? `Generate ${selectedCount} Clip` : 'Generate Clip';
    }
    if (manualBtn) {
        manualBtn.textContent = 'Generate From Manual Trim';
    }
}

function setProcessingState(isProcessing, message = '') {
    const statusShell = document.getElementById('status-shell');
    const processingRing = statusShell?.querySelector('.processing-ring');
    if (isProcessing) {
        document.getElementById('processing-panel')?.classList.add('hidden');
        statusShell?.classList.add('is-processing');
        processingRing?.classList.add('is-active');
        setStatusProgress(12);
        const statusDiv = document.getElementById('status');
        const statusTitle = document.getElementById('status-title');
        if (statusDiv && message) {
            statusDiv.textContent = message;
        }
        if (statusTitle) {
            statusTitle.textContent = 'Analyzing your video...';
        }
        focusPrimaryFeedback();
        if (slowProcessTimer) {
            clearTimeout(slowProcessTimer);
        }
        slowProcessTimer = window.setTimeout(() => {
            const statusDiv = document.getElementById('status');
            const statusTitle = document.getElementById('status-title');
            if (statusDiv) {
                statusDiv.textContent = 'This process may take a few minutes, especially for longer videos or subtitle rendering.';
            }
            if (statusTitle) {
                statusTitle.textContent = 'Process is still running...';
            }
        }, 9000);
    } else {
        if (slowProcessTimer) {
            clearTimeout(slowProcessTimer);
            slowProcessTimer = null;
        }
        statusShell?.classList.remove('is-processing');
        processingRing?.classList.remove('is-active');
        setStatusProgress(0);
        document.getElementById('processing-panel')?.classList.add('hidden');
    }
}

function revealResults() {
    document.getElementById('home-section')?.classList.add('hidden');
    document.getElementById('status-shell')?.classList.remove('hidden');
    document.getElementById('processing-panel')?.classList.add('hidden');
    document.getElementById('results-shell')?.classList.remove('hidden');
    document.getElementById('controls-section')?.classList.remove('hidden');
    document.getElementById('export-section')?.classList.remove('hidden');
}

function hideResults() {
    document.getElementById('home-section')?.classList.remove('hidden');
    document.getElementById('status-shell')?.classList.remove('hidden');
    document.getElementById('processing-panel')?.classList.add('hidden');
    document.getElementById('results-shell')?.classList.add('hidden');
    document.getElementById('controls-section')?.classList.add('hidden');
    document.getElementById('export-section')?.classList.add('hidden');
}

function showGeneratedPage() {
    document.getElementById('home-section')?.classList.add('hidden');
    document.getElementById('status-shell')?.classList.add('hidden');
    document.getElementById('processing-panel')?.classList.add('hidden');
    document.getElementById('results-shell')?.classList.add('hidden');
    document.getElementById('controls-section')?.classList.add('hidden');
    document.getElementById('export-section')?.classList.add('hidden');
    hideHistoryPage();
    const section = document.getElementById('download-section');
    section?.classList.remove('hidden');
    section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function hideGeneratedPage() {
    document.getElementById('download-section')?.classList.add('hidden');
    document.getElementById('status-shell')?.classList.remove('hidden');
}

function showHistoryPage() {
    document.getElementById('home-section')?.classList.add('hidden');
    document.getElementById('status-shell')?.classList.add('hidden');
    document.getElementById('processing-panel')?.classList.add('hidden');
    document.getElementById('results-shell')?.classList.add('hidden');
    document.getElementById('controls-section')?.classList.add('hidden');
    document.getElementById('export-section')?.classList.add('hidden');
    hideGeneratedPage();
    document.getElementById('history-section')?.classList.remove('hidden');
}

function hideHistoryPage() {
    document.getElementById('history-section')?.classList.add('hidden');
    document.getElementById('status-shell')?.classList.remove('hidden');
}

function triggerDownload(filename) {
    const link = document.createElement('a');
    link.href = `/download/${filename}`;
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function initGeneratedPreviewPlayer(cardElement, videoEl) {
    if (!cardElement || !videoEl) {
        return;
    }
    const playBtn = cardElement.querySelector('[data-role="play"]');
    const timeLabel = cardElement.querySelector('[data-role="time"]');
    const seekInput = cardElement.querySelector('[data-role="seek"]');
    if (!(seekInput instanceof HTMLInputElement)) {
        return;
    }

    let isDragging = false;
    let resumeAfterDrag = false;

    const updateUi = () => {
        const duration = Number.isFinite(videoEl.duration) ? videoEl.duration : 0;
        const current = Number.isFinite(videoEl.currentTime) ? videoEl.currentTime : 0;
        if (!isDragging) {
            const ratio = duration > 0 ? current / duration : 0;
            seekInput.value = String(Math.round(ratio * 1000));
        }
        if (timeLabel) {
            timeLabel.textContent = `${formatSeconds(current)} / ${formatSeconds(duration)}`;
        }
        if (playBtn) {
            playBtn.textContent = videoEl.paused ? 'Play' : 'Pause';
        }
    };

    const applySeek = () => {
        const duration = Number.isFinite(videoEl.duration) ? videoEl.duration : 0;
        if (duration <= 0) {
            return;
        }
        videoEl.currentTime = Math.max(0, Math.min(duration, (Number(seekInput.value) / 1000) * duration));
    };

    playBtn?.addEventListener('click', () => {
        if (videoEl.paused) {
            videoEl.play().catch(() => {});
        } else {
            videoEl.pause();
        }
        updateUi();
    });

    seekInput.addEventListener('pointerdown', () => {
        isDragging = true;
        resumeAfterDrag = !videoEl.paused;
        if (resumeAfterDrag) {
            videoEl.pause();
        }
    });
    seekInput.addEventListener('input', () => {
        applySeek();
        updateUi();
    });
    const finishSeek = () => {
        if (!isDragging) {
            return;
        }
        isDragging = false;
        applySeek();
        if (resumeAfterDrag) {
            videoEl.play().catch(() => {});
        }
        resumeAfterDrag = false;
        updateUi();
    };
    seekInput.addEventListener('change', finishSeek);
    seekInput.addEventListener('pointerup', finishSeek);
    seekInput.addEventListener('touchend', finishSeek);
    videoEl.addEventListener('loadedmetadata', updateUi);
    videoEl.addEventListener('timeupdate', updateUi);
    videoEl.addEventListener('play', updateUi);
    videoEl.addEventListener('pause', updateUi);
    updateUi();
}

function showWorkspacePlaceholder() {
    const sourcePreview = document.getElementById('source-preview');
    const clipPreview = document.getElementById('clip-preview');
    const workspacePlaceholder = document.getElementById('workspace-placeholder');

    if (sourcePreview) {
        sourcePreview.classList.add('hidden');
        sourcePreview.removeAttribute('src');
    }

    if (clipPreview) {
        clipPreview.pause();
        clipPreview.classList.add('hidden');
        clipPreview.removeAttribute('src');
        clipPreview.load();
    }

    workspacePlaceholder?.classList.remove('hidden');
}

function showSourcePreview(url, startSeconds = 0) {
    const videoId = extractVideoId(url);
    const sourcePreview = document.getElementById('source-preview');
    const clipPreview = document.getElementById('clip-preview');
    const workspacePlaceholder = document.getElementById('workspace-placeholder');

    if (!videoId || !sourcePreview || !clipPreview || !workspacePlaceholder) {
        showWorkspacePlaceholder();
        return;
    }

    clipPreview.pause();
    clipPreview.classList.add('hidden');
    clipPreview.removeAttribute('src');
    clipPreview.load();

    const startParam = Math.max(0, Math.floor(Number(startSeconds) || 0));
    sourcePreview.src = `https://www.youtube.com/embed/${videoId}?rel=0&start=${startParam}&autoplay=0&controls=1&playsinline=1`;
    sourcePreview.classList.remove('hidden');
    workspacePlaceholder.classList.add('hidden');
}

function showLocalSourcePreview(filePath, startSeconds = 0) {
    const filename = extractFilename(filePath);
    const sourcePreview = document.getElementById('source-preview');
    const clipPreview = document.getElementById('clip-preview');
    const workspacePlaceholder = document.getElementById('workspace-placeholder');

    if (!filename || !sourcePreview || !clipPreview || !workspacePlaceholder) {
        showWorkspacePlaceholder();
        return;
    }

    sourcePreview.classList.add('hidden');
    sourcePreview.removeAttribute('src');
    const nextSource = `/download/${filename}`;
    const currentSource = clipPreview.getAttribute('src') || '';
    clipPreview.classList.remove('hidden');
    workspacePlaceholder.classList.add('hidden');
    const applySeek = () => {
        clipPreview.currentTime = Math.max(0, Number(startSeconds) || 0);
        clipPreview.play().catch(() => {});
    };
    if (!currentSource || !currentSource.endsWith(`/${filename}`)) {
        clipPreview.src = nextSource;
        clipPreview.load();
        clipPreview.onloadedmetadata = () => {
            applySeek();
            clipPreview.onloadedmetadata = null;
        };
    } else if (Number.isFinite(clipPreview.duration) && clipPreview.duration > 0) {
        applySeek();
    } else {
        clipPreview.onloadedmetadata = () => {
            applySeek();
            clipPreview.onloadedmetadata = null;
        };
    }
}

function scheduleSourcePreviewSeek(url, startSeconds = 0) {
    if (!url && !selected.currentLocalPath) {
        return;
    }

    if (previewSeekTimeout) {
        clearTimeout(previewSeekTimeout);
    }

    previewSeekTimeout = window.setTimeout(() => {
        if (selected.currentSourceType === 'local' && selected.currentLocalPath) {
            showLocalSourcePreview(selected.currentLocalPath, startSeconds);
        } else {
            showSourcePreview(url, startSeconds);
        }
        previewSeekTimeout = null;
    }, 260);
}

function showGeneratedClipPreview(filePath) {
    const filename = extractFilename(filePath);
    const sourcePreview = document.getElementById('source-preview');
    const clipPreview = document.getElementById('clip-preview');
    const workspacePlaceholder = document.getElementById('workspace-placeholder');

    if (!filename || !clipPreview || !sourcePreview || !workspacePlaceholder) {
        return;
    }

    sourcePreview.classList.add('hidden');
    sourcePreview.removeAttribute('src');

    clipPreview.src = `/download/${filename}`;
    clipPreview.classList.remove('hidden');
    workspacePlaceholder.classList.add('hidden');
    attachSeekPlaybackBehavior(clipPreview);
    clipPreview.load();
}

function updateWorkspaceTimeline(clip) {
    const startLabel = document.getElementById('workspace-start-label');
    const endLabel = document.getElementById('workspace-end-label');
    const progressBar = document.getElementById('workspace-progress');

    if (!startLabel || !endLabel || !progressBar) {
        return;
    }

    if (!clip) {
        startLabel.textContent = '00:00';
        endLabel.textContent = '00:00';
        progressBar.style.width = '0%';
        updateTrimSelectionVisual(0, 0, 0);
        return;
    }

    startLabel.textContent = clip.start_time || '00:00';
    endLabel.textContent = clip.end_time || '00:00';

    const timelineMax = Math.max(selected.timelineMax || 0, Number(clip.end || 0), 1);
    const clipLength = Math.max(1, Number(clip.end || 0) - Number(clip.start || 0));
    const widthPercent = Math.max(8, Math.min(100, (clipLength / timelineMax) * 100));
    progressBar.style.width = `${widthPercent}%`;
    updateTrimSelectionVisual(Number(clip.start || 0), Number(clip.end || 0), timelineMax);
}

function hideVideoPreview() {
    const sourcePreview = document.getElementById('source-preview');
    const clipPreview = document.getElementById('clip-preview');
    const workspacePlaceholder = document.getElementById('workspace-placeholder');

    if (sourcePreview) {
        sourcePreview.classList.add('hidden');
        sourcePreview.removeAttribute('src');
    }

    if (clipPreview) {
        clipPreview.pause();
        clipPreview.classList.add('hidden');
        clipPreview.removeAttribute('src');
        clipPreview.load();
    }

    if (workspacePlaceholder) {
        workspacePlaceholder.classList.remove('hidden');
    }
}

function extractVideoId(url) {
    const patterns = [
        /(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})/,
        /(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})/
    ];

    for (const pattern of patterns) {
        const match = url.match(pattern);
        if (match) {
            return match[1];
        }
    }

    return '';
}

function extractFilename(filePath) {
    if (!filePath) {
        return '';
    }

    const normalized = String(filePath).replace(/\\/g, '/');
    return normalized.split('/').pop() || '';
}

function applyClipSelection(clip) {
    selected.currentClipPath = '';
    setTrimInputs(clip.start, clip.end);
    updateWorkspaceTimeline(clip);
    if (selected.currentSourceType === 'local' && selected.currentLocalPath) {
        showLocalSourcePreview(selected.currentLocalPath, clip.start);
    } else {
        showSourcePreview(selected.currentUrl, clip.start);
    }
}

function setupTrimEditor(clips, sourceDuration = 0) {
    const maxEnd = Math.max(...clips.map(clip => Number(clip.end || 0)), 0);
    const fullDuration = Number(sourceDuration || selected.sourceDuration || 0);
    selected.timelineMax = Math.max(1, Math.ceil(fullDuration || maxEnd));
    selected.sourceDuration = Math.max(0, fullDuration || maxEnd || 0);

    const trimStartInput = document.getElementById('trim-start-input');
    const trimEndInput = document.getElementById('trim-end-input');
    const scaleStart = document.getElementById('trim-scale-start');
    const scaleEnd = document.getElementById('trim-scale-end');

    if (!trimStartInput || !trimEndInput || !scaleStart || !scaleEnd) {
        return;
    }

    trimStartInput.max = String(selected.timelineMax);
    trimEndInput.max = String(selected.timelineMax);
    scaleStart.textContent = '00:00';
    scaleEnd.textContent = formatSeconds(selected.timelineMax);

    renderTrimMarkers(clips, selected.timelineMax);
    renderHeatmapMarkers(selected.heatmapCandidates, selected.timelineMax);

    if (clips.length) {
        const firstClip = clips[0];
        selected.activeClipKey = getClipKey(firstClip);
        selected.selectedClips = {};
        selected.recommendedClip = { ...firstClip };
        selected.clip = applyExportDurationToClip(selected.recommendedClip);
        setTrimInputs(selected.clip.start, selected.clip.end);
        updateWorkspaceTimeline(selected.clip);
        displayRecommendations(clips);
    } else {
        setTrimInputs(0, 0);
    }
    updateGenerateButtons();
}

function setTrimInputs(start, end) {
    const trimStartInput = document.getElementById('trim-start-input');
    const trimEndInput = document.getElementById('trim-end-input');

    if (!trimStartInput || !trimEndInput) {
        return;
    }

    trimStartInput.value = String(Math.max(0, Math.floor(Number(start) || 0)));
    trimEndInput.value = String(Math.max(0, Math.ceil(Number(end) || 0)));
    syncManualTrim();
}

function syncManualTrim(changedField = '') {
    const trimStartInput = document.getElementById('trim-start-input');
    const trimEndInput = document.getElementById('trim-end-input');

    if (!trimStartInput || !trimEndInput) {
        return;
    }

    let start = Number(trimStartInput.value || 0);
    let end = Number(trimEndInput.value || 0);

    if (changedField === 'start' && start >= end) {
        end = start + 1;
        trimEndInput.value = String(Math.min(end, selected.timelineMax || end));
    } else if (changedField === 'end' && end <= start) {
        start = Math.max(0, end - 1);
        trimStartInput.value = String(start);
    } else if (end <= start) {
        end = start + 1;
        trimEndInput.value = String(Math.min(end, selected.timelineMax || end));
    }

    start = Number(trimStartInput.value || start);
    end = Number(trimEndInput.value || end);

    const baseClip = selected.recommendedClip || selected.clip || {};
    selected.clip = {
        ...baseClip,
        start,
        end,
        start_time: formatSeconds(start),
        end_time: formatSeconds(end)
    };

    const clipKey = getClipKey(baseClip);
    if (clipKey) {
        if (selected.selectedClips[clipKey]) {
            selected.selectedClips[clipKey] = { ...selected.clip };
        }
        selected.recommendedClip = { ...selected.clip };
        selected.activeClipKey = clipKey;
    }

    document.getElementById('trim-start-readout').textContent = formatSeconds(start);
    document.getElementById('trim-end-readout').textContent = formatSeconds(end);
    document.getElementById('trim-duration-readout').textContent = formatSeconds(Math.max(0, end - start));

    updateWorkspaceTimeline(selected.clip);
    scheduleSourcePreviewSeek(selected.currentUrl, start);
    updateGenerateButtons();
}

function renderTrimMarkers(clips, timelineMax) {
    const markerLayer = document.getElementById('trim-marker-layer');
    if (!markerLayer) {
        return;
    }

    markerLayer.innerHTML = '';
    clips.forEach((clip, index) => {
        const clipKey = getClipKey(clip);
        const marker = document.createElement('button');
        marker.type = 'button';
        marker.className = 'trim-marker';
        marker.title = `${clip.title} (${clip.start_time} - ${clip.end_time})`;

        const startPercent = (Number(clip.start || 0) / timelineMax) * 100;
        const widthPercent = Math.max(4, ((Number(clip.end || 0) - Number(clip.start || 0)) / timelineMax) * 100);
        marker.style.left = `${startPercent}%`;
        marker.style.width = `${widthPercent}%`;
        marker.style.top = `${30 + (index % 2) * 26}px`;

        marker.addEventListener('click', () => {
            selected.activeClipKey = clipKey;
            selected.recommendedClip = { ...clip };
            selected.clip = { ...clip };
            displayRecommendations(selected.recommendations);
            applyClipSelection(selected.clip);
            document.getElementById('status').textContent = `${Object.keys(selected.selectedClips).length} clip selected. Active clip: ${clip.title}`;
        });

        markerLayer.appendChild(marker);
    });
}

function renderHeatmapMarkers(candidates, timelineMax) {
    const heatmapLayer = document.getElementById('trim-heatmap-layer');
    if (!heatmapLayer) {
        return;
    }

    heatmapLayer.innerHTML = '';
    if (!Array.isArray(candidates) || !candidates.length || !timelineMax) {
        return;
    }

    candidates.forEach(candidate => {
        const start = Number(candidate.start || 0);
        const end = Number(candidate.end || start);
        const peak = Number(candidate.peak_time || (start + end) / 2 || 0);

        const window = document.createElement('div');
        window.className = 'trim-heatmap-window';
        window.style.left = `${(start / timelineMax) * 100}%`;
        window.style.width = `${Math.max(2, ((end - start) / timelineMax) * 100)}%`;
        heatmapLayer.appendChild(window);

        const peakMarker = document.createElement('div');
        peakMarker.className = 'trim-heatmap-peak';
        peakMarker.style.left = `${(peak / timelineMax) * 100}%`;
        peakMarker.title = `Heatmap peak ${formatSeconds(peak)}`;
        heatmapLayer.appendChild(peakMarker);
    });
}

function updateTrimSelectionVisual(start, end, timelineMax) {
    const selectionBar = document.getElementById('trim-selection-bar');
    const selectionStart = document.getElementById('trim-selection-start');
    const selectionEnd = document.getElementById('trim-selection-end');

    if (!selectionBar || !selectionStart || !selectionEnd || !timelineMax) {
        return;
    }

    const safeStart = Math.max(0, Number(start) || 0);
    const safeEnd = Math.max(safeStart, Number(end) || 0);
    const left = (safeStart / timelineMax) * 100;
    const width = Math.max(1, ((safeEnd - safeStart) / timelineMax) * 100);

    selectionBar.style.left = `${left}%`;
    selectionBar.style.width = `${width}%`;
    selectionStart.style.left = `${left}%`;
    selectionEnd.style.left = `${Math.min(100, left + width)}%`;
}

function formatSeconds(value) {
    const totalSeconds = Math.max(0, Math.floor(Number(value) || 0));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
        const remainingMinutes = minutes % 60;
        return `${String(hours).padStart(2, '0')}:${String(remainingMinutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function getClipKey(clip) {
    if (!clip) {
        return '';
    }
    return clip.clip_id || `${Number(clip.start || 0)}-${Number(clip.end || 0)}-${clip.title || clip.headline || ''}`;
}

function setRecommendationCardState(card, isSelected) {
    const chip = card.querySelector('.recommendation-select-chip');
    card.classList.toggle('border-sky-400', isSelected);
    card.classList.toggle('bg-slate-800', isSelected);
    if (chip) {
        chip.textContent = isSelected ? 'Selected' : 'Select';
        chip.classList.toggle('bg-sky-500/20', isSelected);
    }
}

function collectSelectedClips() {
    const selectedEntries = Object.values(selected.selectedClips || {});
    if (selectedEntries.length) {
        return dedupeClips(selectedEntries).map(applyExportDurationToClip);
    }
    return [];
}

function resetGeneratedClips() {
    const generatedGrid = document.getElementById('generated-clips-grid');
    const downloadSection = document.getElementById('download-section');
    const clipTitle = document.getElementById('clip-title');
    const clipDetails = document.getElementById('clip-details');
    const downloadBtn = document.getElementById('download-btn');

    if (generatedGrid) {
        generatedGrid.innerHTML = '';
    }
    if (downloadSection) {
        downloadSection.classList.add('hidden');
    }
    if (clipTitle) {
        clipTitle.textContent = 'No clip selected';
    }
    if (clipDetails) {
        clipDetails.textContent = 'Generate clips, then select a result card to preview or download.';
    }
    if (downloadBtn) {
        downloadBtn.dataset.clipPath = '';
        downloadBtn.textContent = 'Download MP4';
    }
    selected.selectedGeneratedClipPaths = [];
}

function renderGeneratedClips(generatedClips) {
    const generatedGrid = document.getElementById('generated-clips-grid');
    if (!generatedGrid) {
        return;
    }

    generatedGrid.innerHTML = '';

    generatedClips.forEach((clip, index) => {
        const card = document.createElement('article');
        const isSelected = index === 0;
        card.className = `generated-clip-card rounded-[28px] border p-4 ${isSelected ? 'border-sky-400 bg-slate-900' : 'border-slate-800 bg-slate-950/80'}`;
        card.setAttribute('data-clip-path', clip.clip_path);
        const filename = extractFilename(clip.clip_path);
        const editorId = `subtitle-editor-${index}`;
        const aspectRatio = getAspectRatioValue(clip.export_aspect || selected.exportAspect);
        const rowId = `subtitle-rows-${index}`;
        card.innerHTML = `
            <div class="generated-preview-shell rounded-[22px] bg-black" style="aspect-ratio:${aspectRatio};">
                <video class="generated-preview-video" controls playsinline preload="auto" src="/download/${filename}"></video>
            </div>
            <div class="generated-card-copy mt-4">
                <p class="generated-card-kicker">AI Viral Score ${clip.score ?? clip.viral_score ?? 0}/100</p>
            </div>
            <div class="mt-3 flex items-start justify-between gap-3">
                <div>
                    <h3 class="generated-card-title text-sm font-semibold text-white">${clip.title}</h3>
                    <p class="mt-1 text-sm text-slate-400">${softenClipSummary(clip.summary || clip.reason || clip.title)}</p>
                    <p class="mt-2 text-sm text-slate-500">${clip.start_time} - ${clip.end_time}</p>
                </div>
                <span class="generated-card-size rounded-full border border-slate-700 px-3 py-1 text-xs uppercase tracking-[0.16em] text-slate-300">${clip.file_size_mb?.toFixed?.(2) || clip.file_size_mb} MB</span>
            </div>
            <div class="generated-card-actions mt-4">
                <button type="button" class="generated-select-btn secondary-button px-4 py-2 text-sm">Select</button>
                <button type="button" class="generated-edit-btn secondary-button px-4 py-2 text-sm">Edit</button>
                <button type="button" class="generated-download-btn analyze-button px-4 py-2 text-sm">Download</button>
            </div>
            <div class="generated-editor mt-4 rounded-[20px] border border-slate-800 bg-slate-950/80 p-4 hidden">
                <div class="flex flex-wrap gap-2">
                    <button type="button" class="generated-subtitle-toggle settings-pill text-xs ${clip.subtitles_enabled === false ? '' : 'is-active'}" data-enabled="true">With Subtitle</button>
                    <button type="button" class="generated-subtitle-toggle settings-pill text-xs ${clip.subtitles_enabled === false ? 'is-active' : ''}" data-enabled="false">No Subtitle</button>
                </div>
                <div class="mt-3 flex flex-wrap gap-2">
                    ${['Arial Black', 'Impact', 'Trebuchet MS'].map(font => `
                        <button type="button" class="generated-font-btn settings-pill text-xs ${(clip.subtitle_style?.font || 'Arial Black') === font ? 'is-active' : ''}" data-font="${font}">${getPrettyFontLabel(font)}</button>
                    `).join('')}
                </div>
                <div class="generated-editor-grid mt-3">
                    <label class="generated-editor-field">
                        <span>Language</span>
                        <select class="studio-select generated-language-select">
                            <option value="id" ${(clip.subtitle_lang || 'id') === 'id' ? 'selected' : ''}>Indonesian</option>
                            <option value="en" ${(clip.subtitle_lang || 'id') === 'en' ? 'selected' : ''}>English</option>
                        </select>
                    </label>
                    <label class="generated-editor-field">
                        <span>Position</span>
                        <select class="studio-select generated-position-select">
                            <option value="top" ${(clip.subtitle_style?.position || 'middle') === 'top' ? 'selected' : ''}>Top</option>
                            <option value="middle" ${(clip.subtitle_style?.position || 'middle') === 'middle' ? 'selected' : ''}>Middle</option>
                            <option value="bottom" ${(clip.subtitle_style?.position || 'middle') === 'bottom' ? 'selected' : ''}>Bottom</option>
                        </select>
                    </label>
                    <label class="generated-editor-field">
                        <span>Text Size</span>
                        <select class="studio-select generated-size-select">
                            <option value="small" ${(clip.subtitle_style?.size_preset || 'medium') === 'small' ? 'selected' : ''}>Small</option>
                            <option value="medium" ${(clip.subtitle_style?.size_preset || 'medium') === 'medium' ? 'selected' : ''}>Medium</option>
                            <option value="large" ${(clip.subtitle_style?.size_preset || 'medium') === 'large' ? 'selected' : ''}>Large</option>
                        </select>
                    </label>
                    <label class="generated-editor-field">
                        <span>Color</span>
                        <input type="color" class="subtitle-color-input generated-color-input" value="${clip.subtitle_style?.color || '#FFFFFF'}">
                    </label>
                    <label class="generated-editor-field">
                        <span>Border</span>
                        <input type="color" class="subtitle-color-input generated-outline-input" value="${clip.subtitle_style?.outline_color || '#000000'}">
                    </label>
                </div>
                <div class="generated-editor-field mt-3">
                    <span>Detected Subtitle Timeline</span>
                    <div class="generated-subtitle-toolbar">
                        <button type="button" class="generated-add-segment-btn secondary-button px-3 py-2 text-xs">Add Segment</button>
                    </div>
                    <div id="${editorId}" data-row-root="${rowId}" class="generated-subtitle-list">${buildSubtitleSegmentRows(clip.subtitle_segments)}</div>
                </div>
                <div class="mt-3 flex gap-3">
                    <button type="button" class="generated-apply-btn secondary-button px-4 py-2 text-sm">Apply Subtitle Edit</button>
                    <span class="generated-edit-status hidden rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-emerald-200">Subtitle Updated</span>
                </div>
            </div>
        `;

        const videoEl = card.querySelector('.generated-preview-video');
        const selectBtn = card.querySelector('.generated-select-btn');
        const editBtn = card.querySelector('.generated-edit-btn');
        const downloadBtn = card.querySelector('.generated-download-btn');
        const applyBtn = card.querySelector('.generated-apply-btn');
        const editStatus = card.querySelector('.generated-edit-status');
        const editorWrap = card.querySelector('.generated-editor');
        const addSegmentBtn = card.querySelector('.generated-add-segment-btn');
        const subtitleToggleButtons = card.querySelectorAll('.generated-subtitle-toggle');
        const fontButtons = card.querySelectorAll('.generated-font-btn');
        const languageSelect = card.querySelector('.generated-language-select');
        const positionSelect = card.querySelector('.generated-position-select');
        const sizeSelect = card.querySelector('.generated-size-select');
        const colorInput = card.querySelector('.generated-color-input');
        const outlineInput = card.querySelector('.generated-outline-input');
        const subtitleList = card.querySelector(`#${editorId}`);
        attachSeekPlaybackBehavior(videoEl);
        selectBtn?.addEventListener('click', () => toggleGeneratedClipSelection(card, clip));
        editBtn?.addEventListener('click', () => {
            editorWrap?.classList.toggle('hidden');
            editBtn.textContent = editorWrap?.classList.contains('hidden') ? 'Edit' : 'Hide Edit';
        });
        downloadBtn?.addEventListener('click', () => {
            const clipFilename = extractFilename(clip.clip_path);
            if (clipFilename) {
                window.open(`/download/${clipFilename}`, '_blank');
            }
        });
        subtitleToggleButtons.forEach(button => {
            button.addEventListener('click', () => {
                subtitleToggleButtons.forEach(btn => btn.classList.remove('is-active'));
                button.classList.add('is-active');
                clip.subtitles_enabled = button.dataset.enabled === 'true';
            });
        });
        fontButtons.forEach(button => {
            button.addEventListener('click', () => {
                fontButtons.forEach(btn => btn.classList.remove('is-active'));
                button.classList.add('is-active');
                clip.subtitle_style = {
                    ...(clip.subtitle_style || {}),
                    font: button.dataset.font,
                };
            });
        });
        positionSelect?.addEventListener('change', () => {
            clip.subtitle_style = {
                ...(clip.subtitle_style || {}),
                position: positionSelect.value,
            };
        });
        languageSelect?.addEventListener('change', () => {
            clip.subtitle_lang = languageSelect.value;
            clip.force_subtitle_retranscribe = true;
            clip.subtitle_segments_edited = false;
        });
        sizeSelect?.addEventListener('change', () => {
            clip.subtitle_style = {
                ...(clip.subtitle_style || {}),
                size_preset: sizeSelect.value,
            };
        });
        colorInput?.addEventListener('input', () => {
            clip.subtitle_style = {
                ...(clip.subtitle_style || {}),
                color: colorInput.value.toUpperCase(),
            };
        });
        outlineInput?.addEventListener('input', () => {
            clip.subtitle_style = {
                ...(clip.subtitle_style || {}),
                outline_color: outlineInput.value.toUpperCase(),
            };
        });
        applyBtn?.addEventListener('click', async () => {
            await applyGeneratedSubtitleEdit(clip, card, subtitleList, editStatus);
        });
        addSegmentBtn?.addEventListener('click', () => {
            appendSubtitleSegmentRow(subtitleList, clip);
            clip.subtitle_segments_edited = true;
        });
        subtitleList?.addEventListener('click', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }
            if (target.classList.contains('generated-move-up-btn')) {
                const row = target.closest('.generated-subtitle-row');
                const previous = row?.previousElementSibling;
                if (row instanceof HTMLElement && previous instanceof HTMLElement && previous.classList.contains('generated-subtitle-row')) {
                    previous.insertAdjacentElement('beforebegin', row);
                    clip.subtitle_segments_edited = true;
                }
                return;
            }
            if (target.classList.contains('generated-move-down-btn')) {
                const row = target.closest('.generated-subtitle-row');
                const next = row?.nextElementSibling;
                if (row instanceof HTMLElement && next instanceof HTMLElement && next.classList.contains('generated-subtitle-row')) {
                    next.insertAdjacentElement('afterend', row);
                    clip.subtitle_segments_edited = true;
                }
                return;
            }
            if (target.classList.contains('generated-remove-segment-btn')) {
                const row = target.closest('.generated-subtitle-row');
                row?.remove();
                clip.subtitle_segments_edited = true;
                if (!subtitleList.querySelector('.generated-subtitle-row')) {
                    subtitleList.innerHTML = '<div class="generated-subtitle-empty">No subtitle segments were detected for this clip yet.</div>';
                }
            }
        });
        subtitleList?.addEventListener('input', () => {
            clip.subtitle_segments_edited = true;
        });
        subtitleList?.addEventListener('dragstart', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }
            const handle = target.closest('.generated-drag-handle');
            if (!(handle instanceof HTMLElement)) {
                return;
            }
            const row = handle.closest('.generated-subtitle-row');
            if (!(row instanceof HTMLElement)) {
                return;
            }
            draggedSubtitleRow = row;
            row.classList.add('is-dragging');
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
            }
        });
        subtitleList?.addEventListener('dragend', () => {
            if (draggedSubtitleRow) {
                draggedSubtitleRow.classList.remove('is-dragging');
            }
            draggedSubtitleRow = null;
            subtitleList.querySelectorAll('.generated-subtitle-row').forEach(row => row.classList.remove('drop-before', 'drop-after'));
        });
        subtitleList?.addEventListener('dragover', (event) => {
            event.preventDefault();
            const target = event.target;
            if (!(target instanceof HTMLElement) || !draggedSubtitleRow) {
                return;
            }
            const listRect = subtitleList.getBoundingClientRect();
            const edgeThreshold = 48;
            if (event.clientY < listRect.top + edgeThreshold) {
                subtitleList.scrollTop -= 18;
            } else if (event.clientY > listRect.bottom - edgeThreshold) {
                subtitleList.scrollTop += 18;
            }
            const row = target.closest('.generated-subtitle-row');
            if (!(row instanceof HTMLElement) || row === draggedSubtitleRow) {
                return;
            }
            subtitleList.querySelectorAll('.generated-subtitle-row').forEach(item => item.classList.remove('drop-before', 'drop-after'));
            const rect = row.getBoundingClientRect();
            const insertAfter = event.clientY > rect.top + rect.height / 2;
            row.classList.add(insertAfter ? 'drop-after' : 'drop-before');
        });
        subtitleList?.addEventListener('drop', (event) => {
            event.preventDefault();
            const target = event.target;
            if (!(target instanceof HTMLElement) || !draggedSubtitleRow) {
                return;
            }
            const row = target.closest('.generated-subtitle-row');
            if (!(row instanceof HTMLElement) || row === draggedSubtitleRow) {
                return;
            }
            const rect = row.getBoundingClientRect();
            const insertAfter = event.clientY > rect.top + rect.height / 2;
            row.classList.remove('drop-before', 'drop-after');
            if (insertAfter) {
                row.insertAdjacentElement('afterend', draggedSubtitleRow);
            } else {
                row.insertAdjacentElement('beforebegin', draggedSubtitleRow);
            }
            clip.subtitle_segments_edited = true;
        });

        generatedGrid.appendChild(card);
    });

    if (generatedClips[0]) {
        selected.selectedGeneratedClipPaths = [generatedClips[0].clip_path];
        selectGeneratedClip(generatedGrid.firstElementChild, generatedClips[0]);
    }
    document.getElementById('download-section')?.classList.remove('hidden');
}

function selectGeneratedClip(cardElement, clip) {
    selected.selectedGeneratedClipPath = clip.clip_path;
    selected.currentClipPath = clip.clip_path;
    syncGeneratedCardSelectionStyles();
    showDownloadSection(clip, clip.clip_path);
}

function toggleGeneratedClipSelection(cardElement, clip) {
    const clipPath = clip.clip_path;
    const selectedSet = new Set(selected.selectedGeneratedClipPaths || []);
    if (selectedSet.has(clipPath)) {
        selectedSet.delete(clipPath);
    } else {
        selectedSet.add(clipPath);
    }
    selected.selectedGeneratedClipPaths = Array.from(selectedSet);
    if (!selected.selectedGeneratedClipPaths.length) {
        selected.selectedGeneratedClipPath = '';
    } else if (!selected.selectedGeneratedClipPaths.includes(selected.selectedGeneratedClipPath)) {
        selected.selectedGeneratedClipPath = selected.selectedGeneratedClipPaths[0];
    }
    selected.currentClipPath = clip.clip_path;
    syncGeneratedCardSelectionStyles();
    showDownloadSection(clip, clip.clip_path);
}

function syncGeneratedCardSelectionStyles() {
    const selectedSet = new Set(selected.selectedGeneratedClipPaths || []);
    document.querySelectorAll('.generated-clip-card').forEach(card => {
        const clipPath = card.getAttribute('data-clip-path') || '';
        const selectedButton = card.querySelector('.generated-select-btn');
        const isSelected = selectedSet.has(clipPath);
        card.classList.toggle('border-sky-400', isSelected);
        card.classList.toggle('bg-slate-900', isSelected);
        card.classList.toggle('border-slate-800', !isSelected);
        card.classList.toggle('bg-slate-950/80', !isSelected);
        if (selectedButton) {
            selectedButton.textContent = isSelected ? 'Selected' : 'Select';
            selectedButton.classList.toggle('is-active', isSelected);
        }
    });
}

async function generateClips(clipsToGenerate, emptyMessage) {
    const statusDiv = document.getElementById('status');
    const statusTitle = document.getElementById('status-title');
    const url = document.getElementById('url')?.value.trim();
    const normalizedClips = dedupeClips(clipsToGenerate);

    if (selected.isGenerating) {
        statusDiv.textContent = 'A render process is still running. Please wait until it finishes.';
        focusPrimaryFeedback();
        return;
    }

    if (selected.currentSourceType === 'youtube' && !url) {
        statusDiv.textContent = 'Please enter a YouTube URL first.';
        focusPrimaryFeedback();
        return;
    }

    if (selected.currentSourceType === 'local' && !selected.currentLocalPath) {
        statusDiv.textContent = 'Analyze a local file first before generating a clip.';
        focusPrimaryFeedback();
        return;
    }

    if (!normalizedClips.length) {
        statusDiv.textContent = emptyMessage;
        focusPrimaryFeedback();
        return;
    }

    selected.isGenerating = true;
    resetGeneratedClips();
    statusDiv.textContent = `Generating ${normalizedClips.length} clip(s) and subtitles...`;
    if (statusTitle) statusTitle.textContent = 'Analyzing your video...';
    setProcessingState(true, `Rendering ${normalizedClips.length} clip(s), applying canvas format, and hardcoding subtitles.`);
    setStatusProgress(8);

    try {
        const generatedResults = [];

        for (let index = 0; index < normalizedClips.length; index += 1) {
            const clip = normalizedClips[index];
            setProcessingProgress(
                Math.max(12, Math.round((index / normalizedClips.length) * 88)),
                `Rendering clip ${index + 1}/${normalizedClips.length}: ${clip.title}`
            );
            setStatusProgress(Math.max(12, Math.round(((index + 0.5) / normalizedClips.length) * 88)));
            statusDiv.textContent = `Rendering clip ${index + 1}/${normalizedClips.length}: ${clip.title}`;
            const response = await fetch('/generate-clip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: selected.currentSourceType === 'youtube' ? url : '',
                    clip,
                    subtitle_lang: clip.subtitle_lang || selected.subtitleLanguage || 'id',
                    subtitle_style: buildSubtitleStylePayload(),
                    subtitles_enabled: true,
                    export_aspect: selected.exportAspect,
                    local_path: selected.currentSourceType === 'local' ? selected.currentLocalPath : null,
                    source_type: selected.currentSourceType,
                    subtitle_segments_override: null
                })
            });
            const data = await response.json();

            if (!response.ok) {
                statusDiv.textContent = `Error: ${data.detail || data.error || 'Generate clip failed'}`;
                setProcessingState(false);
                focusPrimaryFeedback();
                return;
            }

            generatedResults.push({
                ...clip,
                clip_path: data.clip_path,
                file_size_mb: data.file_size_mb,
                subtitle_segments: data.subtitle_segments || [],
                subtitle_style: buildSubtitleStylePayload(),
                subtitle_lang: clip.subtitle_lang || selected.subtitleLanguage || 'id',
                subtitles_enabled: true,
                export_aspect: selected.exportAspect,
                source_type: selected.currentSourceType,
                local_path: selected.currentSourceType === 'local' ? selected.currentLocalPath : null,
                source_url: selected.currentSourceType === 'youtube' ? url : '',
                force_subtitle_retranscribe: false,
                subtitle_segments_edited: false
            });
        }

        selected.generatedClips = generatedResults;
        const firstGenerated = generatedResults[0];
        selected.currentClipPath = firstGenerated?.clip_path || '';
        selected.selectedGeneratedClipPath = firstGenerated?.clip_path || '';
        statusDiv.textContent = `${generatedResults.length} clip(s) generated successfully. Select a result card to preview or download.`;
        if (statusTitle) statusTitle.textContent = 'Render complete';
        persistHistoryEntry(generatedResults);
        renderHistory();
        renderGeneratedClips(generatedResults);
        showGeneratedClipPreview(selected.selectedGeneratedClipPath);
        showGeneratedPage();
        setStatusProgress(100);
        setProcessingState(false);
    } catch (error) {
        setProcessingState(false);
        statusDiv.textContent = `Error: ${error.message}`;
        if (statusTitle) statusTitle.textContent = 'Render error';
        setStatusProgress(0);
        focusPrimaryFeedback();
    } finally {
        selected.isGenerating = false;
    }
}

function dedupeClips(clips) {
    const deduped = new Map();
    (clips || []).forEach(clip => {
        deduped.set(getClipKey(clip), { ...clip });
    });
    return Array.from(deduped.values());
}

function getPrettyFontLabel(fontName) {
    return {
        'Arial Black': 'Bold Sans',
        'Impact': 'Impact',
        'Trebuchet MS': 'Clean Sans'
    }[fontName] || fontName;
}

function buildSubtitleSegmentRows(segments) {
    if (!Array.isArray(segments) || !segments.length) {
        return '<div class="generated-subtitle-empty">No subtitle segments were detected for this clip yet.</div>';
    }

    return segments.map((segment, index) => `
        <div class="generated-subtitle-row">
            <div class="generated-subtitle-topline">
                <button type="button" class="generated-drag-handle" draggable="true" title="Drag to reorder">::</button>
                <div class="generated-subtitle-time-editors">
                    <input type="text" class="studio-input generated-subtitle-time-input" data-role="start" value="${formatSeconds(segment.start)}">
                    <span class="generated-subtitle-time-sep">-</span>
                    <input type="text" class="studio-input generated-subtitle-time-input" data-role="end" value="${formatSeconds(segment.end)}">
                </div>
                <div class="generated-subtitle-actions">
                    <button type="button" class="generated-move-up-btn secondary-button px-3 py-2 text-xs" title="Move up">Up</button>
                    <button type="button" class="generated-move-down-btn secondary-button px-3 py-2 text-xs" title="Move down">Down</button>
                    <button type="button" class="generated-remove-segment-btn secondary-button px-3 py-2 text-xs">Remove</button>
                </div>
            </div>
            <input type="text" class="studio-input generated-subtitle-input" data-index="${index}" value="${escapeHtml(segment.text || '')}">
        </div>
    `).join('');
}

function normalizeHistoryClip(clip = {}) {
    const score = Number(clip.score ?? clip.viral_score ?? 0) || 0;
    const title = clip.title || clip.headline || 'Generated Clip';
    const summary = softenClipSummary(clip.summary || clip.reason || title);
    const subtitleSegments = Array.isArray(clip.subtitle_segments) && clip.subtitle_segments.length
        ? clip.subtitle_segments
        : (title ? [{
            start: 0,
            end: 1,
            text: String(title).split(' ').slice(0, 4).join(' ').toUpperCase()
        }] : []);

    return {
        ...clip,
        title,
        headline: clip.headline || title,
        summary,
        reason: clip.reason || summary,
        score,
        viral_score: Number(clip.viral_score ?? score) || score,
        subtitle_segments: subtitleSegments,
        subtitle_style: clip.subtitle_style || buildSubtitleStylePayload(),
        subtitle_lang: clip.subtitle_lang || 'id',
        subtitles_enabled: clip.subtitles_enabled !== false,
        export_aspect: clip.export_aspect || '9:16',
        file_size_mb: clip.file_size_mb ?? 0,
        start_time: clip.start_time || formatSeconds(clip.start || 0),
        end_time: clip.end_time || formatSeconds(clip.end || 0),
    };
}

function buildSubtitleSegmentsOverride(clip, subtitleList) {
    const rows = Array.from(subtitleList?.querySelectorAll('.generated-subtitle-row') || []);
    const parsedRows = rows.map((row, index) => {
        const textInput = row.querySelector('.generated-subtitle-input');
        const startInput = row.querySelector('.generated-subtitle-time-input[data-role="start"]');
        const endInput = row.querySelector('.generated-subtitle-time-input[data-role="end"]');
        return {
            index,
            text: String(textInput?.value || '').trim(),
            start: parseTimecode(startInput?.value),
            end: parseTimecode(endInput?.value),
        };
    }).filter(row => row.text);

    if (!parsedRows.length) {
        return [];
    }

    const clipDuration = Math.max(0.5, Number(clip.end || 0) - Number(clip.start || 0));
    const fallbackDuration = clipDuration / parsedRows.length;

    return parsedRows.map((row, index) => {
        const fallbackStart = Number((index * fallbackDuration).toFixed(3));
        const fallbackEnd = Number(Math.min(clipDuration, (index + 1) * fallbackDuration).toFixed(3));
        let start = Number.isFinite(row.start) ? row.start : fallbackStart;
        let end = Number.isFinite(row.end) ? row.end : fallbackEnd;
        start = Math.max(0, Math.min(start, clipDuration));
        end = Math.max(start + 0.08, Math.min(end, clipDuration));
        return {
            start: Number(start.toFixed(3)),
            end: Number(end.toFixed(3)),
            text: row.text,
        };
    });
}

function appendSubtitleSegmentRow(subtitleList, clip, afterRow = null) {
    if (!subtitleList) {
        return;
    }
    const emptyState = subtitleList.querySelector('.generated-subtitle-empty');
    if (emptyState) {
        emptyState.remove();
    }
    const rows = Array.from(subtitleList.querySelectorAll('.generated-subtitle-row'));
    const clipDuration = Math.max(0.5, Number(clip.end || 0) - Number(clip.start || 0));
    const targetRow = afterRow || rows.at(-1);
    const endInput = targetRow?.querySelector('.generated-subtitle-time-input[data-role="end"]');
    const nextRow = targetRow?.nextElementSibling?.classList?.contains('generated-subtitle-row') ? targetRow.nextElementSibling : null;
    const nextStartInput = nextRow?.querySelector('.generated-subtitle-time-input[data-role="start"]');
    const baseStart = endInput ? parseTimecode(endInput.value) : Math.max(0, clipDuration - 0.8);
    const nextStart = nextStartInput ? parseTimecode(nextStartInput.value) : NaN;
    const start = Number.isFinite(baseStart) ? Math.min(baseStart, Math.max(0, clipDuration - 0.1)) : Math.max(0, clipDuration - 0.8);
    const end = Number.isFinite(nextStart) && nextStart > start ? nextStart : Math.min(clipDuration, start + 0.8);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = buildSubtitleSegmentRows([{ start, end, text: '' }]).trim();
    const newRow = wrapper.firstElementChild;
    if (targetRow && targetRow.parentNode === subtitleList) {
        targetRow.insertAdjacentElement('afterend', newRow);
    } else {
        subtitleList.appendChild(newRow);
    }
}

async function applyGeneratedSubtitleEdit(clip, cardElement, subtitleTextarea, editStatus) {
    const statusDiv = document.getElementById('status');
    if (selected.isGenerating) {
        statusDiv.textContent = 'A render process is still running. Please wait until it finishes.';
        focusPrimaryFeedback();
        return;
    }

    selected.isGenerating = true;
    const applyButton = cardElement?.querySelector('.generated-apply-btn');
    if (applyButton) {
        applyButton.disabled = true;
        applyButton.textContent = 'Applying...';
    }
    editStatus?.classList.add('hidden');

    try {
        const shouldRetranscribe = clip.force_subtitle_retranscribe && !clip.subtitle_segments_edited;
        const overrideSegments = shouldRetranscribe ? null : buildSubtitleSegmentsOverride(clip, subtitleTextarea);
        const response = await fetch('/generate-clip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: clip.source_type === 'youtube' ? clip.source_url : '',
                clip: {
                    start: clip.start,
                    end: clip.end,
                    headline: clip.headline || clip.title,
                    viral_score: clip.viral_score || clip.score || 0,
                },
                subtitle_lang: clip.subtitle_lang || 'id',
                subtitle_style: clip.subtitle_style || buildSubtitleStylePayload(),
                subtitles_enabled: clip.subtitles_enabled !== false,
                export_aspect: clip.export_aspect || selected.exportAspect,
                local_path: clip.source_type === 'local' ? clip.local_path : null,
                source_type: clip.source_type || selected.currentSourceType,
                subtitle_segments_override: overrideSegments
            })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || data.error || 'Failed to apply subtitle edit');
        }

        clip.clip_path = data.clip_path;
        clip.file_size_mb = data.file_size_mb;
        clip.subtitle_segments = data.subtitle_segments || overrideSegments;
        clip.force_subtitle_retranscribe = false;
        clip.subtitle_segments_edited = false;
        const video = cardElement?.querySelector('video');
        const filename = extractFilename(clip.clip_path);
        if (video && filename) {
            video.src = `/download/${filename}`;
            video.load();
        }
        if (subtitleTextarea) {
            subtitleTextarea.innerHTML = buildSubtitleSegmentRows(clip.subtitle_segments);
        }
        statusDiv.textContent = `Subtitle for "${clip.title}" has been updated successfully.`;
        editStatus?.classList.remove('hidden');
        if (selected.selectedGeneratedClipPath === clip.clip_path || selected.currentClipPath === clip.clip_path) {
            showGeneratedClipPreview(clip.clip_path);
        }
        selectGeneratedClip(cardElement, clip);
    } catch (error) {
        statusDiv.textContent = `Error: ${error.message}`;
        focusPrimaryFeedback();
    } finally {
        selected.isGenerating = false;
        if (applyButton) {
            applyButton.disabled = false;
            applyButton.textContent = 'Apply Subtitle Edit';
        }
    }
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function parseTimecode(value) {
    const raw = String(value || '').trim();
    if (!raw) {
        return NaN;
    }
    const parts = raw.split(':').map(part => Number(part));
    if (parts.some(part => Number.isNaN(part))) {
        return NaN;
    }
    if (parts.length === 3) {
        return (parts[0] * 3600) + (parts[1] * 60) + parts[2];
    }
    if (parts.length === 2) {
        return (parts[0] * 60) + parts[1];
    }
    if (parts.length === 1) {
        return parts[0];
    }
    return NaN;
}

function setStatusProgress(percent = 0) {
    const shell = document.getElementById('status-progress-shell');
    const bar = document.getElementById('status-progress-bar');
    const label = document.getElementById('status-progress-label');
    if (!shell || !bar) {
        return;
    }
    const safePercent = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
    if (safePercent <= 0) {
        shell.classList.add('hidden');
        bar.style.width = '0%';
        if (label) {
            label.classList.add('hidden');
            label.textContent = '0%';
        }
        return;
    }
    shell.classList.remove('hidden');
    bar.style.width = `${safePercent}%`;
    if (label) {
        label.classList.remove('hidden');
        label.textContent = `${safePercent}%`;
    }
}

function getHistoryItems() {
    try {
        const parsed = JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || '[]');
        if (!Array.isArray(parsed)) {
            return [];
        }
        return parsed.map(item => ({
            ...item,
            clips: Array.isArray(item.clips) ? item.clips.map(normalizeHistoryClip) : [],
        }));
    } catch {
        return [];
    }
}

function persistHistoryEntry(generatedResults) {
    if (!Array.isArray(generatedResults) || !generatedResults.length) {
        return;
    }
    const sourceLabel = selected.currentUrl || selected.currentLocalPath || 'Untitled Source';
    const title = generatedResults[0]?.title || 'Generated Clips';
    const items = getHistoryItems();
    items.unshift({
        id: `${Date.now()}`,
        created_at: new Date().toISOString(),
        title,
        source: sourceLabel,
        clips: generatedResults.map(clip => ({
            title: clip.title,
            summary: softenClipSummary(clip.summary || clip.reason || clip.title),
            start_time: clip.start_time,
            end_time: clip.end_time,
            clip_path: clip.clip_path,
            file_size_mb: clip.file_size_mb,
            score: clip.score,
            subtitle_segments: clip.subtitle_segments || [],
            subtitle_style: clip.subtitle_style || buildSubtitleStylePayload(),
            subtitle_lang: clip.subtitle_lang || 'id',
            subtitles_enabled: clip.subtitles_enabled !== false,
            export_aspect: clip.export_aspect || selected.exportAspect,
            source_type: clip.source_type || selected.currentSourceType,
            local_path: clip.local_path || '',
            source_url: clip.source_url || '',
            headline: clip.headline || clip.title,
            reason: clip.reason || '',
            start: clip.start,
            end: clip.end,
        })),
    });
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items.slice(0, 20)));
}

function renderHistory() {
    const historyGrid = document.getElementById('history-grid');
    if (!historyGrid) {
        return;
    }
    const items = getHistoryItems();
    if (!items.length) {
        historyGrid.innerHTML = '<div class="rounded-[24px] border border-slate-800 bg-slate-950/70 p-5 text-slate-400">No generated clip history is stored in this browser yet.</div>';
        return;
    }
    historyGrid.innerHTML = items.map(item => `
        <article class="history-entry rounded-[24px] border border-slate-800 bg-slate-950/70 p-5">
            <div class="history-entry-head flex items-start justify-between gap-4">
                <div class="history-entry-meta">
                    <h3 class="text-lg font-semibold text-white">${escapeHtml(item.title)}</h3>
                    <p class="history-entry-source mt-2 text-sm text-slate-400">${escapeHtml(item.source)}</p>
                    <p class="mt-2 text-xs uppercase tracking-[0.14em] text-slate-500">${new Date(item.created_at).toLocaleString()}</p>
                </div>
                <span class="history-entry-count rounded-full border border-slate-700 px-3 py-1 text-xs uppercase tracking-[0.14em] text-slate-300">${item.clips.length} clip</span>
            </div>
            <div class="history-entry-list mt-4 space-y-3">
                ${item.clips.map(clip => `
                    <div class="history-clip-card rounded-[16px] border border-slate-800 bg-slate-900/70 p-4">
                        <div class="history-clip-head flex items-start justify-between gap-3">
                            <div class="history-clip-copy">
                                <p class="text-sm font-semibold text-white">${escapeHtml(clip.title)}</p>
                                <p class="history-clip-summary mt-1 text-sm text-slate-400">${escapeHtml(clip.summary)}</p>
                                <p class="mt-2 text-xs uppercase tracking-[0.12em] text-slate-500">${clip.start_time} - ${clip.end_time}</p>
                            </div>
                            <div class="history-clip-actions flex gap-2">
                                <button type="button" class="history-open-btn secondary-button px-3 py-2 text-xs" data-clip-path="${escapeHtml(clip.clip_path)}" data-history-id="${escapeHtml(item.id)}">Open</button>
                                <button type="button" class="history-download-btn analyze-button px-3 py-2 text-xs" data-clip-path="${escapeHtml(clip.clip_path)}">Download</button>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </article>
    `).join('');
}

function bindHistoryActions() {
    const historyGrid = document.getElementById('history-grid');
    if (!historyGrid || historyGrid.dataset.bound === 'true') {
        return;
    }
    historyGrid.dataset.bound = 'true';
    historyGrid.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const openBtn = target.closest('.history-open-btn');
        if (openBtn instanceof HTMLElement) {
            const clipPath = openBtn.dataset.clipPath || '';
            const historyId = openBtn.dataset.historyId || '';
            const historyItem = getHistoryItems().find(item => item.id === historyId);
            if (historyItem?.clips?.length) {
                selected.generatedClips = historyItem.clips.map(normalizeHistoryClip);
                renderGeneratedClips(selected.generatedClips);
                const targetCard = Array.from(document.querySelectorAll('.generated-clip-card'))
                    .find(card => card.getAttribute('data-clip-path') === clipPath);
                const targetClip = selected.generatedClips.find(clip => clip.clip_path === clipPath) || selected.generatedClips[0];
                if (targetCard && targetClip) {
                    selected.selectedGeneratedClipPaths = [targetClip.clip_path];
                    selectGeneratedClip(targetCard, targetClip);
                }
                showGeneratedPage();
            } else {
                hideHistoryPage();
                revealResults();
                showGeneratedClipPreview(clipPath);
                selected.currentClipPath = clipPath;
                document.getElementById('workspace-frame')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            const statusTitle = document.getElementById('status-title');
            const statusDiv = document.getElementById('status');
            if (statusTitle) statusTitle.textContent = 'History preview';
            if (statusDiv) statusDiv.textContent = 'The clip from history has been opened in the generated clips page.';
            return;
        }
        const downloadBtn = target.closest('.history-download-btn');
        if (downloadBtn instanceof HTMLElement) {
            const clipPath = downloadBtn.dataset.clipPath || '';
            const filename = extractFilename(clipPath);
            if (filename) {
                triggerDownload(filename);
            }
        }
    });
}

function softenClipSummary(summary) {
    const text = String(summary || '').trim();
    if (!text) {
        return 'Momen ini cukup menarik buat dipotong jadi short.';
    }
    const cleaned = text
        .replace(/^clip ini membahas\s+/i, '')
        .replace(/^membahas\s+/i, '')
        .replace(/^tentang\s+/i, '');
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function getAspectRatioValue(aspectLabel) {
    const normalized = String(aspectLabel || '').trim();
    const map = {
        '9:16': '9 / 16',
        '4:5': '4 / 5',
        '1:1': '1 / 1',
        '3:4': '3 / 4',
        '16:9': '16 / 9',
    };
    return map[normalized] || '9 / 16';
}

function attachSeekPlaybackBehavior(videoElement) {
    if (!videoElement || trackedSeekVideos.has(videoElement)) {
        return;
    }
    trackedSeekVideos.add(videoElement);
    videoElement.preload = 'auto';
    const resumePlayback = () => {
        if (videoElement.dataset.wasSeeking !== 'true') {
            return;
        }
        if (videoElement.dataset.wasPlayingBeforeSeek === 'true') {
            videoElement.play().catch(() => {});
        }
        videoElement.dataset.wasSeeking = 'false';
    };
    videoElement.addEventListener('seeking', () => {
        videoElement.dataset.wasSeeking = 'true';
        videoElement.dataset.wasPlayingBeforeSeek = (!videoElement.paused).toString();
    });
    videoElement.addEventListener('seeked', resumePlayback);
}
