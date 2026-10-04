"""Embedded BrowserSkill autoplay expression."""

PLAYBACK_RATE_TOKEN = "__COURSE_PLAYBACK_RATE__"

AUTOPLAY_EXPRESSION = r"""
(async () => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  const isVisible = (el) => {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
      style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
  };

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
  const firstIncomplete = activeIndex < 0 ? findNextIncomplete(0) : null;
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

  const speedWarning = Array.from(document.querySelectorAll('div,span,p')).some(
    (element) => isVisible(element) && textOf(element).includes('系统检测到倍速播放')
  );
  if (speedWarning) {
    if (video) {
      try { video.playbackRate = 1.0; } catch (_) {}
    }
    return {
      ...base,
      action: 'speed-warning',
      playbackRate: video?.playbackRate || 1.0,
      speedWarning: true
    };
  }

  if (activeIndex < 0 && firstIncomplete) {
    const selected = firstIncomplete.item;
    setTimeout(() => selected.click(), 120);
    return {
      ...base,
      action: 'select-resource',
      nextLesson: textOf(selected),
      nextResourceIndex: firstIncomplete.index + 1,
      dismissedModal: false
    };
  }

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



CDWORK_AUTOPLAY_EXPRESSION = r"""
(async () => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  const isVisible = (el) => {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
      style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
  };
  const statusOf = (item) => {
    const spans = Array.from(item?.querySelectorAll(':scope > span') || []);
    const status = spans.map(textOf).find((value) => /未完成|未尝试|已学完|已完成播放|播放完成|已完成/.test(value));
    return status || '';
  };
  const isCompleted = (item) => /已学完|已完成播放|播放完成|已完成/.test(statusOf(item));
  const titleOf = (item) => {
    const title = Array.from(item?.querySelectorAll(':scope > span') || [])
      .map(textOf)
      .find((value) => /^第\d+节/.test(value));
    return title || textOf(item);
  };
  const clickResource = (item) => {
    let parent = item?.parentElement;
    while (parent) {
      const style = getComputedStyle(parent);
      const previous = parent.previousElementSibling;
      if (style.display === 'none' && previous?.classList?.contains('ti')) {
        previous.click();
      }
      parent = parent.parentElement;
    }
    item?.click();
  };

  const headers = Array.from(document.querySelectorAll('.ti'));
  let openedCatalogSections = 0;
  for (const header of headers) {
    const body = header.nextElementSibling;
    if (body && getComputedStyle(body).display === 'none') {
      header.click();
      openedCatalogSections += 1;
    }
  }

  const resources = Array.from(document.querySelectorAll('.ci'));
  const findNextIncomplete = (start) => {
    for (let index = Math.max(0, start); index < resources.length; index += 1) {
      if (!isCompleted(resources[index])) return { item: resources[index], index };
    }
    return null;
  };
  const active = resources.find((item) => {
    const title = Array.from(item.querySelectorAll(':scope > span'))
      .find((span) => /^第\d+节/.test(textOf(span)));
    return title && getComputedStyle(title).color === 'rgb(0, 119, 199)';
  }) || null;
  const activeIndex = active ? resources.indexOf(active) : -1;
  const firstIncomplete = activeIndex < 0 ? findNextIncomplete(0) : null;
  const nextIncomplete = activeIndex >= 0 ? findNextIncomplete(activeIndex + 1) : null;
  const nextResource = nextIncomplete?.item || null;
  const video = document.querySelector('video.vjs-tech') || document.querySelector('video');

  const base = {
    site: 'cdwork',
    lesson: titleOf(active),
    title: document.title,
    url: location.href,
    resourceIndex: activeIndex >= 0 ? activeIndex + 1 : 0,
    resourceCount: resources.length,
    openedCatalogSections,
    hidden: document.hidden,
    visibility: document.visibilityState,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight
  };

  let dismissedModal = false;
  const continueModal = Array.from(document.querySelectorAll('div')).find(
    (element) => isVisible(element) && textOf(element).includes('是否继续上次播放') &&
      element.querySelectorAll('button').length > 0
  );
  if (continueModal) {
    const confirm = Array.from(continueModal.querySelectorAll('button')).find(
      (button) => textOf(button).replace(/[（(]\d+[）)]/g, '').trim() === '确定'
    );
    if (confirm) {
      confirm.click();
      dismissedModal = true;
    }
  }

  const speedWarning = Array.from(document.querySelectorAll('div,span,p')).some(
    (element) => isVisible(element) && textOf(element).includes('系统检测到倍速播放')
  );
  if (speedWarning) {
    if (video) {
      try { video.playbackRate = 1.0; } catch (_) {}
    }
    return {
      ...base,
      action: 'speed-warning',
      playbackRate: video?.playbackRate || 1.0,
      speedWarning: true
    };
  }

  if (activeIndex < 0 && firstIncomplete) {
    clickResource(firstIncomplete.item);
    return {
      ...base,
      action: 'select-resource',
      nextLesson: titleOf(firstIncomplete.item),
      nextResourceIndex: firstIncomplete.index + 1,
      dismissedModal
    };
  }

  if (active && isCompleted(active)) {
    if (nextIncomplete) {
      clickResource(nextIncomplete.item);
      return {
        ...base,
        action: 'skip-completed',
        lesson: titleOf(active),
        nextLesson: titleOf(nextIncomplete.item),
        nextResourceIndex: nextIncomplete.index + 1,
        dismissedModal
      };
    }
    return { ...base, action: 'complete', dismissedModal };
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
      clickResource(nextResource);
      return {
        ...state,
        action: 'next-resource',
        nextLesson: titleOf(nextResource),
        nextResourceIndex: resources.indexOf(nextResource) + 1,
        dismissedModal
      };
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

CDWORK_NEXT_VIDEO_EXPRESSION = r"""
(() => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  const statusOf = (item) => {
    const spans = Array.from(item?.querySelectorAll(':scope > span') || []);
    return spans.map(textOf).find((value) => /未完成|未尝试|已学完|已完成播放|播放完成|已完成/.test(value)) || '';
  };
  const isCompleted = (item) => /已学完|已完成播放|播放完成|已完成/.test(statusOf(item));
  const titleOf = (item) => Array.from(item?.querySelectorAll(':scope > span') || [])
    .map(textOf).find((value) => /^第\d+节/.test(value)) || textOf(item);
  const clickResource = (item) => item?.click();
  const headers = Array.from(document.querySelectorAll('.ti'));
  for (const header of headers) {
    const body = header.nextElementSibling;
    if (body && getComputedStyle(body).display === 'none') header.click();
  }
  const resources = Array.from(document.querySelectorAll('.ci'));
  const active = resources.find((item) => {
    const title = Array.from(item.querySelectorAll(':scope > span')).find((span) => /^第\d+节/.test(textOf(span)));
    return title && getComputedStyle(title).color === 'rgb(0, 119, 199)';
  }) || null;
  const index = active ? resources.indexOf(active) : -1;
  let targetIndex = index < 0 ? 0 : index + 1;
  while (targetIndex < resources.length && isCompleted(resources[targetIndex])) targetIndex += 1;
  if (targetIndex >= resources.length) {
    return { ok: false, reason: 'at-end', from: titleOf(active), index: index + 1, count: resources.length };
  }
  const target = resources[targetIndex];
  clickResource(target);
  return {
    ok: true,
    site: 'cdwork',
    from: titleOf(active),
    to: titleOf(target),
    index: index + 1,
    nextIndex: targetIndex + 1,
    skippedCompleted: targetIndex > index + 1,
    count: resources.length
  };
})()
"""

CDWORK_PREVIOUS_VIDEO_EXPRESSION = r"""
(() => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  const titleOf = (item) => Array.from(item?.querySelectorAll(':scope > span') || [])
    .map(textOf).find((value) => /^第\d+节/.test(value)) || textOf(item);
  const resources = Array.from(document.querySelectorAll('.ci'));
  const active = resources.find((item) => {
    const title = Array.from(item.querySelectorAll(':scope > span')).find((span) => /^第\d+节/.test(textOf(span)));
    return title && getComputedStyle(title).color === 'rgb(0, 119, 199)';
  }) || null;
  const index = active ? resources.indexOf(active) : -1;
  if (index < 0) return { ok: false, reason: 'no-active', count: resources.length };
  if (index <= 0) return { ok: false, reason: 'at-start', from: titleOf(active), index: index + 1, count: resources.length };
  const target = resources[index - 1];
  target.click();
  return { ok: true, site: 'cdwork', from: titleOf(active), to: titleOf(target), index: index + 1, previousIndex: index, count: resources.length };
})()
"""

CDWORK_RESUME_VIDEO_EXPRESSION = r"""
(async () => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  const titleOf = (item) => Array.from(item?.querySelectorAll(':scope > span') || [])
    .map(textOf).find((value) => /^第\d+节/.test(value)) || textOf(item);
  const statusOf = (item) => {
    const spans = Array.from(item?.querySelectorAll(':scope > span') || []);
    return spans.map(textOf).find((value) => /未完成|未尝试|已学完|已完成播放|播放完成|已完成/.test(value)) || '';
  };
  const isCompleted = (item) => /已学完|已完成播放|播放完成|已完成/.test(statusOf(item));
  const headers = Array.from(document.querySelectorAll('.ti'));
  for (const header of headers) {
    const body = header.nextElementSibling;
    if (body && getComputedStyle(body).display === 'none') header.click();
  }
  const resources = Array.from(document.querySelectorAll('.ci'));
  let targetIndex = Math.max(0, Number('__RESUME_INDEX__') - 1);
  const savedTime = Math.max(0, Number('__RESUME_TIME__') || 0);
  const active = resources.find((item) => {
    const title = Array.from(item.querySelectorAll(':scope > span')).find((span) => /^第\d+节/.test(textOf(span)));
    return title && getComputedStyle(title).color === 'rgb(0, 119, 199)';
  }) || null;
  let currentIndex = active ? resources.indexOf(active) : -1;

  if (targetIndex >= resources.length) {
    return { ok: false, reason: 'not-found', targetIndex: targetIndex + 1, count: resources.length };
  }
  if (isCompleted(resources[targetIndex])) {
    while (targetIndex < resources.length && isCompleted(resources[targetIndex])) targetIndex += 1;
    if (targetIndex >= resources.length) {
      return { ok: true, reason: 'all-completed', targetIndex, count: resources.length, changed: false };
    }
  }
  if (currentIndex > targetIndex) {
    return {
      ok: true,
      reason: 'platform-ahead',
      targetIndex: targetIndex + 1,
      currentIndex: currentIndex + 1,
      lesson: titleOf(resources[currentIndex]),
      count: resources.length,
      changed: false
    };
  }
  if (currentIndex !== targetIndex) {
    resources[targetIndex].click();
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }

  let video = null;
  for (let attempt = 0; attempt < 25; attempt += 1) {
    video = document.querySelector('video.vjs-tech') || document.querySelector('video');
    if (video && video.readyState >= 1 && Number.isFinite(video.duration)) break;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  if (!video) return { ok: false, reason: 'wait-video', targetIndex: targetIndex + 1 };
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
    site: 'cdwork',
    targetIndex: targetIndex + 1,
    lesson: titleOf(resources[targetIndex]),
    savedTime,
    targetTime,
    currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration,
    changed: currentIndex !== targetIndex
  };
})()
"""



WEBTRN_AUTOPLAY_EXPRESSION = r"""
(async () => {
  const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
  const host = location.hostname.toLowerCase();
  const path = location.pathname;

  if (host.includes('scszj.webtrn.cn') && path.includes('/cms/classDetailNew.htm')) {
    const courses = Array.from(document.querySelectorAll('li.class2Li')).map((row) => {
      const titleLink = row.querySelector('a.v2-title');
      const progressText = textOf(row.querySelector('em.color-theme')).replace('%', '');
      const progress = Number.isFinite(Number(progressText)) ? Number(progressText) : 0;
      return {
        title: textOf(titleLink),
        href: titleLink?.href || '',
        progress
      };
    }).filter((course) => course.href);
    const nextCourse = courses.find((course) => course.progress < 100);
    if (nextCourse) {
      setTimeout(() => { location.href = nextCourse.href; }, 150);
      return {
        site: 'webtrn-class',
        action: 'open-course',
        lesson: nextCourse.title,
        nextLesson: nextCourse.title,
        progressPct: nextCourse.progress,
        courseCount: courses.length
      };
    }
    return { site: 'webtrn-class', action: 'complete', courseCount: courses.length };
  }

  if (host.includes('scszj.webtrn.cn') && path.includes('/cms/classCourseDetailNew.htm')) {
    const button = document.querySelector('#audition') || document.querySelector('a.btn-theme');
    const onclick = button?.getAttribute('onclick') || '';
    const match = onclick.match(/'(https?:\/\/[^']*signLearn\.action[^']*)'/);
    const targetUrl = match?.[1]?.replace(/&amp;/g, '&') || '';
    if (targetUrl) {
      setTimeout(() => { location.href = targetUrl; }, 150);
      return { site: 'webtrn-course', action: 'open-player', lesson: textOf(document.querySelector('h1')), targetUrl };
    }
    return { site: 'webtrn-course', action: 'wait-player', lesson: textOf(document.querySelector('h1')) };
  }

  const outerFrame = document.querySelector('#mainContent');
  const outerDoc = outerFrame?.contentDocument || null;
  const innerFrame = outerDoc?.querySelector('#mainFrame') || null;
  const innerDoc = innerFrame?.contentDocument || null;
  const video = innerDoc?.querySelector('video') || null;
  const resources = Array.from(outerDoc?.querySelectorAll('.s_point[itemtype="video"]') || []);
  const currentId = innerFrame?.src ? new URL(innerFrame.src).searchParams.get('params.itemId') : null;
  const activeIndex = resources.findIndex((item) => item.id === `s_point_${currentId}`);
  const active = activeIndex >= 0 ? resources[activeIndex] : null;
  const isCompleted = (item) => item?.getAttribute('completestate') === '1';
  const findNextIncomplete = (start) => {
    for (let index = Math.max(0, start); index < resources.length; index += 1) {
      if (!isCompleted(resources[index])) return { item: resources[index], index };
    }
    return null;
  };
  const firstIncomplete = activeIndex < 0 ? findNextIncomplete(0) : null;
  const nextIncomplete = activeIndex >= 0 ? findNextIncomplete(activeIndex + 1) : null;
  const base = {
    site: 'webtrn-player',
    lesson: active?.title || '',
    title: document.title,
    url: location.href,
    resourceIndex: activeIndex >= 0 ? activeIndex + 1 : 0,
    resourceCount: resources.length,
    hidden: document.hidden,
    visibility: document.visibilityState,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight
  };

  if (activeIndex < 0 && firstIncomplete) {
    firstIncomplete.item.click();
    return { ...base, action: 'select-resource', nextLesson: firstIncomplete.item.title, nextResourceIndex: firstIncomplete.index + 1 };
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
    Number.isFinite(video.duration) && video.duration > 0 && video.currentTime >= video.duration - 0.35
  );
  if (nearEnd && nextIncomplete) {
    nextIncomplete.item.click();
    return { ...state, action: 'next-resource', nextLesson: nextIncomplete.item.title, nextResourceIndex: nextIncomplete.index + 1 };
  }
  if (nearEnd) {
    return { ...state, action: 'course-complete' };
  }
  if (video.paused && video.readyState >= 2) {
    const playButton = innerDoc.querySelector('#player_pause');
    if (playButton) playButton.click();
    await new Promise((resolve) => setTimeout(resolve, 300));
    return { ...state, paused: video.paused, action: video.paused ? 'needs-user-gesture' : 'resume' };
  }
  return { ...state, action: video.paused ? 'wait-player' : 'playing' };
})()
"""

WEBTRN_PLAYBACK_RECOVERY_EXPRESSION = r"""
(async () => {
  const outerDoc = document.querySelector('#mainContent')?.contentDocument || null;
  const innerDoc = outerDoc?.querySelector('#mainFrame')?.contentDocument || null;
  const video = innerDoc?.querySelector('video') || null;
  if (!video) return { ok: false, reason: 'no-video' };
  const before = Number.isFinite(video.currentTime) ? video.currentTime : 0;
  let playError = null;
  if (video.paused) {
    try {
      const button = innerDoc.querySelector('#player_pause');
      if (button) button.click();
      else await video.play();
    } catch (error) {
      playError = { name: error?.name || 'Error', message: error?.message || String(error) };
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 450));
  return {
    ok: !video.paused,
    reason: video.paused ? 'still-paused' : 'playing',
    before,
    currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration: Number.isFinite(video.duration) ? video.duration : 0,
    paused: video.paused,
    ended: video.ended,
    readyState: video.readyState,
    playbackRate: video.playbackRate,
    playError
  };
})()
"""

WEBTRN_PLAYBACK_TOGGLE_EXPRESSION = r"""
(async () => {
  const outerDoc = document.querySelector('#mainContent')?.contentDocument || null;
  const innerDoc = outerDoc?.querySelector('#mainFrame')?.contentDocument || null;
  const video = innerDoc?.querySelector('video') || null;
  if (!video) return { ok: false, reason: 'no-video' };
  const button = innerDoc.querySelector('#player_pause');
  if (video.paused) {
    if (button) button.click();
    else await video.play();
  } else {
    video.pause();
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  return { ok: true, paused: video.paused, currentTime: video.currentTime };
})()
"""

WEBTRN_NEXT_VIDEO_EXPRESSION = r"""
(() => {
  const outerDoc = document.querySelector('#mainContent')?.contentDocument || null;
  const innerFrame = outerDoc?.querySelector('#mainFrame') || null;
  const resources = Array.from(outerDoc?.querySelectorAll('.s_point[itemtype="video"]') || []);
  const currentId = innerFrame?.src ? new URL(innerFrame.src).searchParams.get('params.itemId') : null;
  const index = resources.findIndex((item) => item.id === `s_point_${currentId}`);
  let targetIndex = index < 0 ? 0 : index + 1;
  while (targetIndex < resources.length && resources[targetIndex].getAttribute('completestate') === '1') targetIndex += 1;
  if (targetIndex >= resources.length) return { ok: false, reason: 'at-end', from: resources[index]?.title || '', index: index + 1, count: resources.length };
  const target = resources[targetIndex];
  target.click();
  return { ok: true, site: 'webtrn', from: resources[index]?.title || '', to: target.title, index: index + 1, nextIndex: targetIndex + 1, skippedCompleted: targetIndex > index + 1, count: resources.length };
})()
"""

WEBTRN_PREVIOUS_VIDEO_EXPRESSION = r"""
(() => {
  const outerDoc = document.querySelector('#mainContent')?.contentDocument || null;
  const innerFrame = outerDoc?.querySelector('#mainFrame') || null;
  const resources = Array.from(outerDoc?.querySelectorAll('.s_point[itemtype="video"]') || []);
  const currentId = innerFrame?.src ? new URL(innerFrame.src).searchParams.get('params.itemId') : null;
  const index = resources.findIndex((item) => item.id === `s_point_${currentId}`);
  if (index < 0) return { ok: false, reason: 'no-active', count: resources.length };
  if (index <= 0) return { ok: false, reason: 'at-start', from: resources[index]?.title || '', index: index + 1, count: resources.length };
  const target = resources[index - 1];
  target.click();
  return { ok: true, site: 'webtrn', from: resources[index]?.title || '', to: target.title, index: index + 1, previousIndex: index, count: resources.length };
})()
"""

WEBTRN_RESUME_VIDEO_EXPRESSION = r"""
(async () => {
  const targetIndex = Math.max(0, Number('__RESUME_INDEX__') - 1);
  const savedTime = Math.max(0, Number('__RESUME_TIME__') || 0);
  const getOuter = () => document.querySelector('#mainContent')?.contentDocument || null;
  let outerDoc = getOuter();
  let resources = Array.from(outerDoc?.querySelectorAll('.s_point[itemtype="video"]') || []);
  if (!resources.length || targetIndex >= resources.length) return { ok: false, reason: 'not-found', targetIndex: targetIndex + 1, count: resources.length };
  const innerFrame = outerDoc.querySelector('#mainFrame');
  const currentId = innerFrame?.src ? new URL(innerFrame.src).searchParams.get('params.itemId') : null;
  const currentIndex = resources.findIndex((item) => item.id === `s_point_${currentId}`);
  if (currentIndex !== targetIndex) {
    resources[targetIndex].click();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    outerDoc = getOuter();
    resources = Array.from(outerDoc?.querySelectorAll('.s_point[itemtype="video"]') || []);
  }
  let video = null;
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const frame = getOuter()?.querySelector('#mainFrame');
    video = frame?.contentDocument?.querySelector('video') || null;
    if (video && video.readyState >= 1 && Number.isFinite(video.duration)) break;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  if (!video) return { ok: false, reason: 'wait-video', targetIndex: targetIndex + 1 };
  const duration = Number.isFinite(video.duration) ? video.duration : 0;
  let targetTime = savedTime;
  if (duration > 0) {
    targetTime = Math.min(targetTime, duration);
    if (savedTime >= duration - 3) targetTime = 0;
  }
  if (targetTime > 0 && video.currentTime < targetTime - 1) {
    try { video.currentTime = targetTime; } catch (_) {}
  }
  return { ok: true, site: 'webtrn', targetIndex: targetIndex + 1, lesson: resources[targetIndex]?.title || '', targetTime, currentTime: video.currentTime, duration, changed: currentIndex !== targetIndex };
})()
"""


def is_webtrn_course(course_url: str) -> bool:
    return "webtrn.cn" in str(course_url or "").lower()


def playback_recovery_expression(course_url: str) -> str:
    if is_webtrn_course(course_url):
        return WEBTRN_PLAYBACK_RECOVERY_EXPRESSION
    return PLAYBACK_RECOVERY_EXPRESSION


def playback_toggle_expression(course_url: str) -> str:
    if is_webtrn_course(course_url):
        return WEBTRN_PLAYBACK_TOGGLE_EXPRESSION
    return PLAYBACK_TOGGLE_EXPRESSION

def is_cdwork_course(course_url: str) -> bool:
    return "cdwork.cn" in str(course_url or "").lower()


def render_expression(playback_rate: float = 1.0, course_url: str = "") -> str:
    if is_webtrn_course(course_url):
        template = WEBTRN_AUTOPLAY_EXPRESSION
    elif is_cdwork_course(course_url):
        template = CDWORK_AUTOPLAY_EXPRESSION
    else:
        template = AUTOPLAY_EXPRESSION
    return template.replace(PLAYBACK_RATE_TOKEN, str(playback_rate))


def next_video_expression(course_url: str) -> str:
    if is_webtrn_course(course_url):
        return WEBTRN_NEXT_VIDEO_EXPRESSION
    if is_cdwork_course(course_url):
        return CDWORK_NEXT_VIDEO_EXPRESSION
    return NEXT_VIDEO_EXPRESSION


def previous_video_expression(course_url: str) -> str:
    if is_webtrn_course(course_url):
        return WEBTRN_PREVIOUS_VIDEO_EXPRESSION
    if is_cdwork_course(course_url):
        return CDWORK_PREVIOUS_VIDEO_EXPRESSION
    return PREVIOUS_VIDEO_EXPRESSION


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


def render_resume_expression(resource_index: int, current_time: float, course_url: str = "") -> str:
    if is_webtrn_course(course_url):
        template = WEBTRN_RESUME_VIDEO_EXPRESSION
    elif is_cdwork_course(course_url):
        template = CDWORK_RESUME_VIDEO_EXPRESSION
    else:
        template = RESUME_VIDEO_EXPRESSION
    return (
        template
        .replace("__RESUME_INDEX__", str(max(1, int(resource_index or 1))))
        .replace("__RESUME_TIME__", str(max(0.0, float(current_time or 0))))
    )
