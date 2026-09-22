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

  const active = document.querySelector('.resource-item-active');
  const video = document.querySelector('video');
  const activeIndex = active ? resources.indexOf(active) : -1;
  const nextResource = activeIndex >= 0 ? resources[activeIndex + 1] : null;

  const base = {
    lesson: textOf(active),
    title: document.title,
    url: location.href,
    resourceIndex: activeIndex >= 0 ? activeIndex + 1 : 0,
    resourceCount: resources.length,
    openedCatalogSections: collapsedHeaders.length
  };

  const modal = Array.from(document.querySelectorAll('.fish-modal-wrap')).find(
    (item) => !!(item.offsetWidth || item.offsetHeight || item.getClientRects().length)
  );
  const modalContent = modal?.querySelector('.fish-modal-confirm-content')?.textContent?.trim() || '';
  const knownCompletionNotice = '须学习完课程的视频才可获得该课程视频的学时';

  if (modal && modalContent === knownCompletionNotice) {
    modal.querySelector('.fish-modal-confirm-btns button')?.click();
    return { ...base, action: 'dismissed-modal', modalText: modalContent };
  }

  if (!video) {
    return { ...base, action: 'wait-video', paused: null, currentTime: null, duration: null };
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
    video.currentTime >= video.duration - 1.25
  );

  if (nearEnd && active) {
    if (nextResource) {
      const nextIndex = activeIndex + 1;
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
      }, 900);

      return {
        ...state,
        action: 'next-resource',
        nextLesson: nextText,
        nextResourceIndex: nextIndex + 1
      };
    }

    if (collapsedHeaders.length > 0) {
      return { ...state, action: 'loading-catalog' };
    }

    return { ...state, action: 'complete' };
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
      action: video.paused ? 'needs-user-gesture' : 'resume'
    };
  }

  return { ...state, action: video.paused ? 'wait-player' : 'playing' };
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

  const active = document.querySelector('.resource-item-active');
  const index = active ? resources.indexOf(active) : -1;
  if (index < 0) {
    return { ok: false, reason: 'no-active', count: resources.length };
  }
  if (index + 1 >= resources.length) {
    return { ok: false, reason: 'at-end', from: textOf(active), index: index + 1, count: resources.length };
  }

  const from = textOf(active);
  const to = textOf(resources[index + 1]);

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
    currentResources[index + 1]?.click();
  }, 120);

  return {
    ok: true,
    from,
    to,
    index: index + 1,
    nextIndex: index + 2,
    count: resources.length,
    openedCatalogSections: collapsedHeaders.length
  };
})()
"""
