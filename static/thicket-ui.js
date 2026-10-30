(function (root) {
  'use strict';

  function safeHttpUrl(value) {
    try {
      const parsed = new URL(value);
      return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : null;
    } catch (_) {
      return null;
    }
  }

  function host(value) {
    const safe = safeHttpUrl(value);
    return safe ? new URL(safe).hostname.replace(/^www\./, '') : 'source unavailable';
  }

  function samePage(left, right) {
    const first = safeHttpUrl(left);
    const second = safeHttpUrl(right);
    if (!first || !second) return false;
    const normalize = (value) => {
      const parsed = new URL(value);
      parsed.hash = '';
      parsed.pathname = parsed.pathname.replace(/\/$/, '') || '/';
      return parsed.href;
    };
    return normalize(first) === normalize(second);
  }

  function incomingType(entry) {
    if (entry.kind === 'withdrawal' || entry.status === 'gone') return 'WITHDRAWAL';
    if (entry.relation === 'link') return 'LINK';
    if (entry.mention_class === 'notice') return 'REPOST';
    if (entry.relation === 'stub') return 'STUB';
    if (entry.relation === 'transclusion') return 'TRANSCLUDE';
    if (entry.relation === 'fork') return 'FORK';
    if (entry.relation === 'source') return 'SOURCE';
    return 'WEBMENTION';
  }

  function incomingSite(entry) {
    const site = host(entry.source_origin || entry.source_page || entry.source);
    return entry.source_author
      ? String(entry.source_author).slice(0, 200) + ' · ' + site
      : site;
  }

  function combined(outgoing, incoming) {
    const rows = [];
    for (const entry of outgoing?.entries || [])
      rows.push({ direction: 'OUT', sortTime: entry.updated_at, entry });
    for (const entry of responses(incoming))
      rows.push({ direction: 'IN', sortTime: entry.at, entry });
    return rows.sort((left, right) => {
      const difference = Date.parse(right.sortTime) - Date.parse(left.sortTime);
      return Number.isNaN(difference) ? 0 : difference;
    });
  }

  function responses(incoming) {
    return (incoming?.activities || []).filter((entry) => entry.mention_class !== 'notice');
  }

  function notices(incoming) {
    return (incoming?.activities || []).filter((entry) => entry.mention_class === 'notice');
  }

  function noticeRows(incoming) {
    return notices(incoming)
      .map((entry) => ({ direction: 'IN', sortTime: entry.at, entry, notice: true }))
      .sort((left, right) => Date.parse(right.sortTime) - Date.parse(left.sortTime));
  }

  function incomingCaption(snapshot) {
    if (!snapshot || snapshot.availability === 'not_enabled')
      return 'Incoming synchronization is not enabled.';
    if (snapshot.availability === 'not_synchronized') return 'Not yet synchronized.';
    if (snapshot.availability === 'unavailable') return 'Synchronization unavailable.';
    const unread = Number(snapshot.unread_count) || 0;
    const activity = Number(snapshot.activity_count) || 0;
    if (snapshot.availability === 'stale')
      return activity
        ? unread + ' unread · last-known activity'
        : 'No recorded activity · synchronization stale';
    const notices = Number(snapshot.notice_count) || 0;
    const suffix = notices ? ' · ' + notices + (notices === 1 ? ' notice' : ' notices') : '';
    if (!activity) return notices ? notices + (notices === 1 ? ' notice' : ' notices') : 'No incoming mentions.';
    return (unread ? unread + ' unread' : 'No unread activity') + suffix;
  }

  root.BlyngerThicketUI = {
    safeHttpUrl,
    samePage,
    host,
    incomingType,
    incomingSite,
    combined,
    responses,
    notices,
    noticeRows,
    incomingCaption,
  };
})(typeof window === 'undefined' ? globalThis : window);
