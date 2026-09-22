"""Embedded BrowserSkill autoplay expression."""

PLAYBACK_RATE_TOKEN = "__COURSE_PLAYBACK_RATE__"

AUTOPLAY_EXPRESSION = r"""
(async () => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();

  // Open every catalog group/section so lazily loaded resource items enter the DOM.
  const collapsedHeaders = Array.from(
    document.querySelectorAll('.fish-collapse-header[role="button"]')
  ).filter((header) => header.getAttribute('aria-expanded') !== 'true');

  for (const header of collapsedHeaders) {
    header.click();
  }

  const catalogSections = Array.from(
    document.querySelectorAll('[class*="course-catalog-item-2_"]')
  ).filter((section, index, all) => all.indexOf(section) === index);

  const seenResources = new Set();
  const resources = [];
  for (const section of catalogSections) {
    for (const item of section.querySelectorAll('.resource-item')) {
      if (!seenResources.has(item)) {
        seenResources.add(item);
        resources.push(item);
      }
    }
  }

  const statusOf = (item) => (item?.querySelector('[title]')?.getAttribute('title') || '').trim();
  const isCompleted = (item) => /已学完|已完成播放|播放完成|已完成/.test(statusOf(item));
  const findNextIncomplete = (start) => {
    for (let index = Math.max(0, start); index < resources.length; index += 1) {
      if (!isCompleted(resources[index])) return { item: resources[index], index };
    }
    return null;
  };

  const active = document.querySelector('.resource-item-active');
  const video = document.querySelector('video');
  const activeIndex = active ? resources.indexOf(active) : -1;
  const nextIncomplete = activeIndex >= 0 ? findNextIncomplete(activeIndex + 1) : null;
  const nextResource = nextIncomplete?.item || null;

  const base = {
    lesson: textOf(active),
    title: document.title,
    url: location.href,
    resourceIndex: activeIndex >= 0 ? activeIndex + 1 : 0,
    resourceCount: resources.length,
    openedCatalogSections: collapsedHeaders.length,
    hidden: document.hidden,
    visibility: document.visibilityState,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight
  };

  if (active && isCompleted(active)) {
    if (nextIncomplete) {
      nextIncomplete.item.click();
      return {
        ...base,
        action: 'skip-completed',
        lesson: textOf(active),
        nextLesson: textOf(nextIncomplete.item),
        nextResourceIndex: nextIncomplete.index + 1
      };
    }
    return { ...base, action: 'complete' };
  }

  const modal = Array.from(document.querySelectorAll('.fish-modal-wrap')).find(
    (item) => !!(item.offsetWidth || item.offsetHeight || item.getClientRects().length)
  );
  const modalContent = modal?.querySelector('.fish-modal-confirm-content')?.textContent?.trim() || '';
  const knownCompletionNotice = '须学习完课程的视频才可获得该课程视频的学时';
  let dismissedModal = false;

  if (modal && modalContent === knownCompletionNotice) {
    modal.querySelector('.fish-modal-confirm-btns button')?.click();
    dismissedModal = true;
  }

  if (!video) {
    return { ...base, action: 'wait-video', paused: null, currentTime: null, duration: null, dismissedModal };
  }

  const desiredPlaybackRate = Number('__COURSE_PLAYBACK_RATE__');
  if (Number.isFinite(desiredPlaybackRate) && video.playbackRate !== desiredPlaybackRate) {
    video.playbackRate = desiredPlaybackRate;
  }

  const state = {
    ...base,
    paused: video.paused,
    ended: video.ended,
    currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration: Number.isFinite(video.duration) ? video.duration : 0,
    playbackRate: video.playbackRate,
    readyState: video.readyState
  };

  const nearEnd = video.ended || (
    Number.isFinite(video.duration) &&
    video.duration > 0 &&
    video.currentTime >= video.duration - 0.35
  );

  if (nearEnd && active) {
    if (nextResource) {
      const nextIndex = resources.indexOf(nextResource);
      const nextText = textOf(nextResource);

      // Defensive fallback if the site re-rendered or collapsed an ancestor.
      let ancestor = nextResource.parentElement;
      while (ancestor) {
        if (ancestor.classList?.contains('fish-collapse-item')) {
          const header = ancestor.querySelector(':scope > .fish-collapse-header');
          if (header && header.getAttribute('aria-expanded') !== 'true') {
            header.click();
          }
        }
        ancestor = ancestor.parentElement;
      }

      setTimeout(() => {
        const sections = Array.from(
          document.querySelectorAll('[class*="course-catalog-item-2_"]')
        ).filter((section, index, all) => all.indexOf(section) === index);

        const currentResources = [];
        const seen = new Set();
        for (const section of sections) {
          for (const item of section.querySelectorAll('.resource-item')) {
            if (!seen.has(item)) {
              seen.add(item);
              currentResources.push(item);
            }
          }
        }

        currentResources[nextIndex]?.click();
      }, 120);

      return {
        ...state,
        action: 'next-resource',
        nextLesson: nextText,
        nextResourceIndex: nextIndex + 1,
        dismissedModal
      };
    }

    if (collapsedHeaders.length > 0) {
      return { ...state, action: 'loading-catalog', dismissedModal };
    }

    return { ...state, action: 'complete', dismissedModal };
  }

  if (video.paused && video.readyState >= 2) {
    let playError = null;
    try {
      await video.play();
    } catch (error) {
      playError = { name: error?.name || 'Error', message: error?.message || String(error) };
    }

    await new Promise((resolve) => setTimeout(resolve, 300));

    return {
      ...state,
      paused: video.paused,
      currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
      playError,
      action: video.paused ? 'needs-user-gesture' : 'resume',
      dismissedModal
    };
  }

  return { ...state, action: video.paused ? 'wait-player' : 'playing', dismissedModal };
})()
"""


def render_expression(playback_rate: float = 1.0) -> str:
    return AUTOPLAY_EXPRESSION.replace(PLAYBACK_RATE_TOKEN, str(playback_rate))

NEXT_VIDEO_EXPRESSION = r"""
(() => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();

  const collapsedHeaders = Array.from(
    document.querySelectorAll('.fish-collapse-header[role="button"]')
  ).filter((header) => header.getAttribute('aria-expanded') !== 'true');
  for (const header of collapsedHeaders) header.click();

  const sections = Array.from(
    document.querySelectorAll('[class*="course-catalog-item-2_"]')
  ).filter((section, index, all) => all.indexOf(section) === index);

  const resources = [];
  const seen = new Set();
  for (const section of sections) {
    for (const item of section.querySelectorAll('.resource-item')) {
      if (!seen.has(item)) {
        seen.add(item);
        resources.push(item);
      }
    }
  }

  const statusOf = (item) => (item?.querySelector('[title]')?.getAttribute('title') || '').trim();
  const isCompleted = (item) => /已学完|已完成播放|播放完成|已完成/.test(statusOf(item));
  const active = document.querySelector('.resource-item-active');
  const index = active ? resources.indexOf(active) : -1;
  if (index < 0) {
    return { ok: false, reason: 'no-active', count: resources.length };
  }

  let targetIndex = -1;
  for (let candidate = index + 1; candidate < resources.length; candidate += 1) {
    if (!isCompleted(resources[candidate])) {
      targetIndex = candidate;
      break;
    }
  }
  if (targetIndex < 0) {
    return { ok: false, reason: 'at-end', from: textOf(active), index: index + 1, count: resources.length };
  }

  const from = textOf(active);
  const to = textOf(resources[targetIndex]);

  setTimeout(() => {
    const currentSections = Array.from(
      document.querySelectorAll('[class*="course-catalog-item-2_"]')
    ).filter((section, sectionIndex, all) => all.indexOf(section) === sectionIndex);
    const currentResources = [];
    const currentSeen = new Set();
    for (const section of currentSections) {
      for (const item of section.querySelectorAll('.resource-item')) {
        if (!currentSeen.has(item)) {
          currentSeen.add(item);
          currentResources.push(item);
        }
      }
    }
    currentResources[targetIndex]?.click();
  }, 120);

  return {
    ok: true,
    from,
    to,
    index: index + 1,
    nextIndex: targetIndex + 1,
    skippedCompleted: targetIndex > index + 1,
    count: resources.length,
    openedCatalogSections: collapsedHeaders.length
  };
})()
"""

PREVIOUS_VIDEO_EXPRESSION = r"""
(() => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();

  const collapsedHeaders = Array.from(
    document.querySelectorAll('.fish-collapse-header[role="button"]')
  ).filter((header) => header.getAttribute('aria-expanded') !== 'true');
  for (const header of collapsedHeaders) header.click();

  const sections = Array.from(
    document.querySelectorAll('[class*="course-catalog-item-2_"]')
  ).filter((section, index, all) => all.indexOf(section) === index);

  const resources = [];
  const seen = new Set();
  for (const section of sections) {
    for (const item of section.querySelectorAll('.resource-item')) {
      if (!seen.has(item)) {
        seen.add(item);
        resources.push(item);
      }
    }
  }

  const active = document.querySelector('.resource-item-active');
  const index = active ? resources.indexOf(active) : -1;
  if (index < 0) {
    return { ok: false, reason: 'no-active', count: resources.length };
  }
  if (index <= 0) {
    return { ok: false, reason: 'at-start', from: textOf(active), index: index + 1, count: resources.length };
  }

  const from = textOf(active);
  const to = textOf(resources[index - 1]);

  setTimeout(() => {
    const currentSections = Array.from(
      document.querySelectorAll('[class*="course-catalog-item-2_"]')
    ).filter((section, sectionIndex, all) => all.indexOf(section) === sectionIndex);
    const currentResources = [];
    const currentSeen = new Set();
    for (const section of currentSections) {
      for (const item of section.querySelectorAll('.resource-item')) {
        if (!currentSeen.has(item)) {
          currentSeen.add(item);
          currentResources.push(item);
        }
      }
    }
    currentResources[index - 1]?.click();
  }, 120);

  return {
    ok: true,
    from,
    to,
    index: index + 1,
    previousIndex: index,
    count: resources.length,
    openedCatalogSections: collapsedHeaders.length
  };
})()
"""

PLAYBACK_TOGGLE_EXPRESSION = r"""
(async () => {
  const video = document.querySelector('video');
  if (!video) return { ok: false, reason: 'no-video' };
  if (video.paused) {
    try {
      await video.play();
    } catch (error) {
      return { ok: false, reason: 'blocked', error: error?.name || 'Error', paused: video.paused };
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
    return { ok: !video.paused, reason: video.paused ? 'blocked' : 'playing', paused: video.paused };
  }
  video.pause();
  return { ok: true, reason: 'paused', paused: true };
})()
"""


PLAYBACK_RECOVERY_EXPRESSION = r"""
(async () => {
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
      style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
  };

  const videos = Array.from(document.querySelectorAll('video'));
  const video = videos.find(visible) || videos.find((item) => !item.paused) || videos[0];
  if (!video) {
    return { ok: false, reason: 'no-video', videoCount: videos.length };
  }

  const before = Number.isFinite(video.currentTime) ? video.currentTime : 0;
  let playError = null;
  if (video.paused) {
    try {
      await video.play();
    } catch (error) {
      playError = { name: error?.name || 'Error', message: error?.message || String(error) };
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 450));

  return {
    ok: !video.paused,
    reason: video.paused ? 'still-paused' : 'playing',
    videoCount: videos.length,
    before,
    currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration: Number.isFinite(video.duration) ? video.duration : 0,
    readyState: video.readyState,
    networkState: video.networkState,
    paused: video.paused,
    ended: video.ended,
    playbackRate: video.playbackRate,
    error: video.error ? { code: video.error.code, message: video.error.message } : null,
    playError
  };
})()
"""

RESUME_VIDEO_EXPRESSION = r"""
(async () => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  let targetIndex = Math.max(0, Number('__RESUME_INDEX__') - 1);
  const savedTime = Math.max(0, Number('__RESUME_TIME__') || 0);

  const collapsedHeaders = Array.from(
    document.querySelectorAll('.fish-collapse-header[role="button"]')
  ).filter((header) => header.getAttribute('aria-expanded') !== 'true');
  for (const header of collapsedHeaders) header.click();

  const collectResources = () => {
    const sections = Array.from(
      document.querySelectorAll('[class*="course-catalog-item-2_"]')
    ).filter((section, index, all) => all.indexOf(section) === index);
    const resources = [];
    const seen = new Set();
    for (const section of sections) {
      for (const item of section.querySelectorAll('.resource-item')) {
        if (!seen.has(item)) {
          seen.add(item);
          resources.push(item);
        }
      }
    }
    return resources;
  };

  let resources = collectResources();
  let active = document.querySelector('.resource-item-active');
  let currentIndex = active ? resources.indexOf(active) : -1;

  const statusOf = (item) => (item?.querySelector('[title]')?.getAttribute('title') || '').trim();
  const isCompleted = (item) => /已学完|已完成播放|播放完成|已完成/.test(statusOf(item));
  const findNextIncomplete = (start) => {
    for (let index = Math.max(0, start); index < resources.length; index += 1) {
      if (!isCompleted(resources[index])) return { item: resources[index], index };
    }
    return null;
  };

  if (currentIndex >= 0 && isCompleted(resources[currentIndex])) {
    const next = findNextIncomplete(currentIndex + 1);
    if (!next) {
      return { ok: true, reason: 'all-completed', currentIndex: currentIndex + 1, count: resources.length, changed: false };
    }
    targetIndex = next.index;
    resources[targetIndex].click();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    resources = collectResources();
    currentIndex = targetIndex;
  }

  if (isCompleted(resources[targetIndex])) {
    const next = findNextIncomplete(targetIndex + 1);
    if (!next) {
      return { ok: true, reason: 'all-completed', targetIndex: targetIndex + 1, count: resources.length, changed: false };
    }
    targetIndex = next.index;
  }

  if (targetIndex >= resources.length) {
    return { ok: false, reason: 'not-found', targetIndex: targetIndex + 1, count: resources.length };
  }

  if (currentIndex > targetIndex) {
    return {
      ok: true,
      reason: 'platform-ahead',
      targetIndex: targetIndex + 1,
      currentIndex: currentIndex + 1,
      lesson: textOf(resources[currentIndex]),
      count: resources.length,
      changed: false
    };
  }

  if (currentIndex !== targetIndex) {
    resources[targetIndex]?.click();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    resources = collectResources();
  }

  let video = null;
  for (let attempt = 0; attempt < 25; attempt += 1) {
    video = document.querySelector('video');
    if (video && video.readyState >= 1 && Number.isFinite(video.duration)) break;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }

  if (!video) {
    return { ok: false, reason: 'wait-video', targetIndex: targetIndex + 1 };
  }

  const duration = Number.isFinite(video.duration) ? video.duration : 0;
  let targetTime = savedTime;
  if (duration > 0) {
    targetTime = Math.min(targetTime, duration);
    if (savedTime >= duration - 3) targetTime = 0;
  }

  if (targetTime > 0 && video.currentTime < targetTime - 1) {
    try { video.currentTime = targetTime; } catch (_) {}
  }

  return {
    ok: true,
    targetIndex: targetIndex + 1,
    lesson: textOf(resources[targetIndex]),
    savedTime,
    targetTime,
    currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration,
    changed: currentIndex !== targetIndex
  };
})()
"""


def render_resume_expression(resource_index: int, current_time: float) -> str:
    return (
        RESUME_VIDEO_EXPRESSION
        .replace("__RESUME_INDEX__", str(max(1, int(resource_index or 1))))
        .replace("__RESUME_TIME__", str(max(0.0, float(current_time or 0))))
    )
