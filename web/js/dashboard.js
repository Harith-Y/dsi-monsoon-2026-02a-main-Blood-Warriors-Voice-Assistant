/* Coordinator dashboard (/dashboard): this week's numbers, the queue of questions the assistant handed off,
   voice replies that are read back and saved only after "yes", and "Make this an FAQ" (opens /teach).
   Sign in and the voice sheet live in coord.js. Talks to /coord/*. */
(function () {
  'use strict';
  var BW = window.BW, $ = BW.$, t = BW.t, C = BW.coord;

  var URGENCY_ICON = { high: 'alert', medium: 'clock', low: 'inbox' };
  var state = { status: 'open', requests: [], counts: {}, stats: null, poll: null };

  function duration(mins) {
    mins = Math.round(mins);
    if (mins < 60) return t('dur.min', { n: mins });
    if (mins < 1440) return t('dur.hr', { h: Math.floor(mins / 60), m: mins % 60 });
    return t('dur.day', { d: Math.floor(mins / 1440), h: Math.floor((mins % 1440) / 60) });
  }
  function langLabel(code) { return BW.i18n.languages[code] ? BW.i18n.languages[code].name : code; }

  /* ---------- this week ---------- */
  function renderStats() {
    var s = state.stats; if (!s) return;
    $('#weekSince').textContent = t('week.since', { date: new Date(s.since).toLocaleDateString(C.speech(), { day: 'numeric', month: 'short' }) });
    $('#stAnswered').textContent = s.answered;
    $('#stHanded').textContent = s.handed_off;
    $('#stReplied').textContent = t('week.replied', { n: s.replied });
    var avg = $('#stAvg');
    avg.textContent = s.avg_response_minutes == null ? t('week.avg_none') : duration(s.avg_response_minutes);
    avg.classList.toggle('stat-none', s.avg_response_minutes == null);
    var langs = Object.keys(s.languages || {});
    $('#stLangs').innerHTML = langs.length ? langs.map(function (l) {
      return '<span class="chip" lang="' + l + '">' + BW.esc(langLabel(l)) + '<strong>' + s.languages[l] + '</strong></span>';
    }).join('') : '<span class="stat-num stat-none">' + BW.esc(t('week.langs_none')) + '</span>';
  }

  /* ---------- queue ---------- */
  function refresh(quiet) {
    var btn = $('#refreshBtn');
    btn.setAttribute('aria-busy', 'true');
    if (!quiet && !state.requests.length) $('#reqList').innerHTML = '<p class="sub empty-line">' + BW.esc(t('queue.loading')) + '</p>';
    C.capi('/coord/stats', { timeout: 15000 }).then(function (s) { state.stats = s; renderStats(); }, function () {});
    return C.capi('/coord/requests?status=' + state.status, { timeout: 45000 }).then(function (r) {
      btn.removeAttribute('aria-busy');
      state.requests = r.requests; state.counts = r.counts;
      renderQueue();
    }, function (e) {
      btn.removeAttribute('aria-busy');
      if (e.kind === 'http' && e.status === 401) return;
      if (!quiet) $('#reqList').innerHTML = '<div class="inline-msg" role="alert">' + BW.icon('wifi-off') + '<div>' + BW.esc(t('queue.load_fail')) + '</div></div>';
    });
  }

  function renderTabs() {
    BW.$$('#tabs button').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.status === state.status));
    });
    ['open', 'replied', 'closed'].forEach(function (s) { $('#cnt-' + s).textContent = state.counts[s] || 0; });
  }

  function player(cls, label) {
    return '<div class="player ' + cls + '"><button type="button" class="play" aria-label="' + BW.esc(t('a11y.play')) + '">' +
      BW.icon('play', 'i-fill') + '</button><div class="player-mid"><span>' + BW.esc(label) +
      '</span><div class="progress"><div class="bar"></div></div></div><span class="ptime">0:00</span></div>';
  }
  function actBtn(cls, act, icon, label) {
    return '<button type="button" class="btn ' + cls + '" data-act="' + act + '">' + BW.icon(icon) + '<span>' + BW.esc(label) + '</span></button>';
  }

  function card(r) {
    var lang = BW.i18n.lang, summary = r.summary && (r.summary[lang] || r.summary.en);
    var h = '<article class="card req" data-ref="' + BW.esc(r.reference) + '">';
    h += '<div class="req-top"><span class="ref-tag">' + BW.esc(r.reference) + '</span>';
    if (r.urgency) h += C.chip('urg-' + r.urgency, URGENCY_ICON[r.urgency] || 'clock', t('urg.' + r.urgency));
    h += C.chip('chip-lang', 'globe', langLabel(r.language), r.language);
    h += '<span class="time">' + BW.esc(C.ago(r.created_at)) + '</span></div>';
    h += '<h3 class="req-summary' + (summary ? '' : ' pending') + '">' + BW.esc(summary || t('req.no_summary')) + '</h3>';
    if (r.reason && t('reason.' + r.reason) !== 'reason.' + r.reason) {
      h += '<p class="req-reason">' + BW.icon('info') + BW.esc(t('reason.' + r.reason)) + '</p>';
    }
    h += '<div class="q-quote"><span class="label">' + BW.icon('user') + BW.esc(t('req.asked')) + '</span><p lang="' + BW.esc(r.language) + '">' + BW.esc(r.question_text || '') + '</p></div>';
    if (r.question_audio_url) h += player('q-player', t(r.question_recorded ? 'req.listen' : 'req.listen_tts'));
    if (r.reply_text) {
      h += '<div class="reply-box"><span class="label">' + BW.icon('headset') + BW.esc(t('req.you_said')) + '</span><p>' + BW.esc(r.reply_source_text || '') + '</p>';
      if (r.reply_text !== r.reply_source_text) {
        h += '<span class="label">' + BW.icon('globe') + BW.esc(t('req.they_hear', { language: C.langName(r.language) })) + '</span><p lang="' + BW.esc(r.language) + '">' + BW.esc(r.reply_text) + '</p>';
      }
      if (r.replied_at) h += '<span class="time">' + BW.esc(t('req.replied_at', { when: C.ago(r.replied_at) })) + '</span>';
      h += '</div>';
      if (r.reply_audio_url) h += player('r-player', t('req.play_reply'));
    }
    h += '<div class="actions">';
    if (r.status !== 'closed') {
      h += actBtn('btn-primary', 'reply', 'mic', t(r.reply_text ? 'req.reply_change' : 'req.reply'));
      if (r.reply_text) h += actBtn('btn-outline', 'faq', 'book', t('req.faq'));
      h += actBtn('btn-soft', 'close', 'archive', t('req.close'));
    } else {
      if (r.reply_text) h += actBtn('btn-outline', 'faq', 'book', t('req.faq'));
      h += actBtn('btn-soft', 'reopen', 'replay', t('req.reopen'));
    }
    return h + '</div></article>';
  }

  function renderQueue() {
    renderTabs();
    var list = $('#reqList');
    if (!state.requests.length) {
      var icon = state.status === 'open' ? 'check' : state.status === 'replied' ? 'headset' : 'archive';
      list.innerHTML = '<div class="card empty"><span class="tile">' + BW.icon(icon) + '</span><p>' + BW.esc(t('queue.empty_' + state.status)) + '</p></div>';
      return;
    }
    list.innerHTML = state.requests.map(card).join('');
    state.requests.forEach(function (r) {
      var el = list.querySelector('[data-ref="' + r.reference + '"]');
      if (!el) return;
      var q = el.querySelector('.q-player'), rp = el.querySelector('.r-player');
      if (q) BW.bindPlayer(q, r.question_audio_url, false);
      if (rp) BW.bindPlayer(rp, r.reply_audio_url, false);
    });
  }

  function findRequest(ref) {
    return state.requests.filter(function (r) { return r.reference === ref; })[0];
  }

  function setStatus(ref, status) {
    C.capi('/coord/requests/' + encodeURIComponent(ref) + '/status', { form: { status: status } }).then(function () {
      BW.toast(t(status === 'closed' ? 'req.closed_toast' : 'req.reopened_toast', { ref: ref }));
      refresh(true);
    }, function () { BW.toast(t('req.action_fail')); });
  }

  /* ---------- reply: record -> draft (read back) -> yes / no / change ---------- */
  function listenReply(request) {
    C.listen({
      title: t('reply.title', { ref: request.reference }),
      quote: { text: request.question_text, lang: request.language },
      prompt: t('reply.say'),
      hint: t('reply.hint', { mine: C.langName(BW.i18n.lang), theirs: C.langName(request.language) }),
      onAudio: function (blob) { draftReply(request, { audio: blob }); },
      again: function () { listenReply(request); }
    });
  }

  function draftReply(request, form) {
    C.thinking(t('reply.thinking'));
    form.lang = BW.i18n.lang;
    C.capi('/coord/requests/' + encodeURIComponent(request.reference) + '/reply/draft', { form: form, timeout: 60000 })
      .then(function (d) { showReplyDraft(request, d); }, function (e) {
        if (e.kind === 'http' && e.status === 401) return;
        C.errorFor(C.errCode(e), function () { listenReply(request); });
      });
  }

  function showReplyDraft(request, d) {
    var translated = d.reply_text !== d.source_text;
    var body = '<div class="draft-part"><span class="label">' + BW.icon('headset') + BW.esc(t('req.you_said')) + '</span>' +
      '<p class="draft-source" id="draftSource">' + BW.esc(d.source_text) + '</p></div>';
    if (translated) {
      body += '<div class="caption" id="draftReplyBox"><span class="label">' + BW.icon('globe') +
        BW.esc(t('req.they_hear', { language: C.langName(d.reply_lang) })) + '</span>' +
        '<p id="draftReply" lang="' + BW.esc(d.reply_lang) + '">' + BW.esc(d.reply_text) + '</p></div>';
    }
    C.showDraft({
      chip: t('reply.check'), bodyHtml: body, audioUrl: d.audio_url, approveLabel: t('reply.approve'),
      doneTitle: t('reply.sent_title'),
      send: function (form) {
        form.source_text = d.source_text; form.reply_text = d.reply_text;
        return C.capi('/coord/requests/' + encodeURIComponent(request.reference) + '/reply/confirm', { form: form, timeout: 45000 });
      },
      again: function () { listenReply(request); },
      onYes: function () { refresh(true); }
    });
  }

  /* ---------- the view ---------- */
  C.register('queue', {
    path: '/dashboard', section: '#d-main', heading: '#h-week', docKey: 'dash.doc', subKey: 'dash.sub',
    bind: function () {
      $('#refreshBtn').addEventListener('click', function () { refresh(); });
      $('#tabs').addEventListener('click', function (e) {
        var b = e.target.closest('button[data-status]'); if (!b || b.dataset.status === state.status) return;
        state.status = b.dataset.status; state.requests = [];
        renderTabs(); refresh();
      });
      $('#reqList').addEventListener('click', function (e) {
        var b = e.target.closest('button[data-act]'); if (!b) return;
        var ref = b.closest('[data-ref]').dataset.ref, r = findRequest(ref);
        if (!r) return;
        if (b.dataset.act === 'reply') listenReply(r);
        else if (b.dataset.act === 'faq') { BW.unlockAudio(); C.go('teach', { from: ref }); }
        else if (b.dataset.act === 'close') setStatus(ref, 'closed');
        else if (b.dataset.act === 'reopen') setStatus(ref, 'open');
      });
    },
    show: function () {
      refresh();
      clearInterval(state.poll);
      state.poll = setInterval(function () {
        if (document.visibilityState === 'visible' && !C.sheetOpen()) refresh(true);
      }, 30000);
    },
    hide: function () { clearInterval(state.poll); },
    signedOut: function () { clearInterval(state.poll); },
    lang: function () { renderStats(); renderQueue(); }
  });
})();
