/* Teach the assistant by voice (/teach): one big mic. The coordinator says a question and its answer (or what
   to change, or "undo the last change"); the draft is shown as a card while it is read back, and it is saved,
   translated and searchable straight away only after a spoken or tapped "yes". Talks to /kb/*. */
(function () {
  'use strict';
  var BW = window.BW, $ = BW.$, t = BW.t, C = BW.coord;

  var KIND_ICON = { 'new': 'plus', edit: 'pencil', undo: 'undo' };
  var ACT_ICON = { create: 'plus', edit: 'pencil', undo: 'undo' };
  var state = { history: null, count: null, canUndo: false, loading: false };

  function langLabel(code) { return BW.i18n.languages[code] ? BW.i18n.languages[code].name : code; }
  function catName(c) { var s = t('cat.' + c); return s === 'cat.' + c ? c : s; }

  /* ---------- recent changes ---------- */
  function loadHistory() {
    state.loading = true;
    if (!state.history) $('#histList').innerHTML = '<p class="sub empty-line">' + BW.esc(t('queue.loading')) + '</p>';
    return C.capi('/kb/history?lang=' + BW.i18n.lang, { timeout: 15000 }).then(function (h) {
      state.loading = false;
      state.history = h.changes; state.count = h.count; state.canUndo = h.can_undo;
      renderHistory();
    }, function (e) {
      state.loading = false;
      if (e.kind === 'http' && e.status === 401) return;
      $('#histList').innerHTML = '<div class="inline-msg" role="alert">' + BW.icon('wifi-off') + '<div>' + BW.esc(t('teach.history_fail')) + '</div></div>';
    });
  }

  function renderHistory() {
    $('#kbCount').textContent = state.count == null ? '' : t('teach.count', { n: state.count });
    $('#undoBtn').disabled = !state.canUndo;
    var list = $('#histList'), items = state.history;
    if (!items) return;
    if (!items.length) {
      list.innerHTML = '<div class="card empty"><span class="tile">' + BW.icon('book') + '</span><p>' + BW.esc(t('teach.history_empty')) + '</p></div>';
      return;
    }
    list.innerHTML = '<ul class="hist">' + items.map(function (c) {
      var h = '<li class="hist-item' + (c.undone ? ' undone' : '') + '"><span class="tile">' + BW.icon(ACT_ICON[c.action] || 'pencil') + '</span><div class="hist-main">';
      h += '<div class="hist-top"><strong>' + BW.esc(t('teach.act_' + c.action)) + '</strong><span class="time">' + BW.esc(C.ago(c.created_at)) + '</span></div>';
      if (c.question) h += '<p class="hist-q">' + BW.esc(c.question) + '</p>';
      var tags = '';
      if (c.undone) tags += C.chip('chip-sample', 'undo', t('teach.undone_tag'));
      if (c.from_ref) tags += C.chip('', 'inbox', t('teach.from_ref', { ref: c.from_ref }));
      if (tags) h += '<div class="chip-row">' + tags + '</div>';
      return h + '</div></li>';
    }).join('') + '</ul>';
  }

  /* ---------- teach: listen -> draft (read back) -> yes / no / change ---------- */
  function listenTeach() {
    C.listen({
      title: t('teach.title'), prompt: t('teach.listen_prompt'), hint: t('teach.listen_hint'),
      // A question and its answer take longer to say than a caregiver's question, with pauses between.
      rec: { maxMs: 60000, silenceMs: 3500, giveUpMs: 10000 },
      onAudio: function (blob) { makeDraft({ audio: blob }, t('teach.thinking')); },
      again: listenTeach
    });
  }

  function makeDraft(form, thinkingText) {
    if (!C.sheetOpen()) C.openSheet(t('teach.title'));
    C.thinking(thinkingText);
    form.lang = BW.i18n.lang;
    C.capi('/kb/draft', { form: form, timeout: 90000 }).then(function (d) {
      if (d.kind === 'new' || d.kind === 'edit' || d.kind === 'undo') { showTeachDraft(d); return; }
      C.errorSaid(d, d.kind === 'nothing' ? 'info' : 'ear', d.kind === 'nothing' ? null : listenTeach);  // unclear / nothing to undo
    }, function (e) {
      if (e.kind === 'http' && e.status === 401) return;
      var body = e.body || {};
      if (e.kind === 'http' && body.text) { C.errorSaid(body, 'alert', body.error === 'no_reply' ? null : listenTeach); return; }
      C.errorFor(C.errCode(e), form.from_ref ? function () { makeDraft(form, thinkingText); } : listenTeach);
    });
  }

  function part(label, icon, text, cls) {
    return '<div class="draft-part"><span class="label">' + BW.icon(icon) + BW.esc(label) + '</span><p class="' + (cls || '') + '">' + BW.esc(text || '') + '</p></div>';
  }

  function draftBody(d) {
    var h = '<div class="chip-row"><span class="kind-tag">' + BW.icon(KIND_ICON[d.kind]) + BW.esc(t('teach.kind_' + d.kind)) + '</span>';
    if (d.category) h += C.chip('', 'book', catName(d.category));
    if (d.from_ref) h += C.chip('', 'inbox', t('teach.from_ref', { ref: d.from_ref }));
    h += '</div>';
    if (d.kind === 'undo') {
      h += '<p class="sub">' + BW.esc(t(d.undo_action === 'create' ? 'teach.undo_was_new' : 'teach.undo_was_edit')) + '</p>';
      h += part(t('teach.q_label'), 'help', d.question, 'draft-q');
      if (d.undo_action === 'edit' && d.before_answer) {
        h += '<div class="caption"><span class="label">' + BW.icon('replay') + BW.esc(t('teach.a_label')) + '</span><p>' + BW.esc(d.before_answer) + '</p></div>';
      }
      return h;
    }
    if (d.kind === 'edit') {
      h += '<div class="caption before"><span class="label">' + BW.icon('clock') + BW.esc(t('teach.before')) + '</span>';
      if ((d.changed || []).indexOf('question') >= 0) h += '<p class="strong">' + BW.esc(d.before_question || '') + '</p>';
      h += '<p>' + BW.esc(d.before_answer || '') + '</p></div>';
      h += '<span class="label after-label">' + BW.icon('pencil') + BW.esc(t('teach.after')) + '</span>';
    }
    h += part(t('teach.q_label'), 'help', d.question, 'draft-q');
    h += part(t('teach.a_label'), 'shield', d.answer, 'draft-a');
    if (d.phrasings && d.phrasings.length) {
      h += '<div class="draft-part"><span class="label">' + BW.icon('globe') + BW.esc(t('teach.phrasings')) + '</span><ul class="phrasings">' +
        d.phrasings.map(function (p) { return '<li>' + BW.esc(p) + '</li>'; }).join('') + '</ul></div>';
    }
    if (d.to_coordinator) {
      h += '<div class="inline-msg">' + BW.icon('alert') + '<div>' + BW.esc(t('teach.to_coord_note')) + '</div></div>';
    }
    return h;
  }

  function showTeachDraft(d) {
    C.showDraft({
      chip: t('teach.check'), bodyHtml: draftBody(d), audioUrl: d.audio_url,
      approveLabel: t(d.kind === 'undo' ? 'teach.approve_undo' : 'teach.approve'),
      busyText: d.kind === 'undo' ? t('think.title') : t('teach.saving'),
      confirmHint: t('teach.confirm_hint'),
      doneTitle: t(d.kind === 'undo' ? 'teach.undone_title' : 'teach.saved_title'),
      send: function (form) {
        form.draft_id = d.draft_id;
        return C.capi('/kb/confirm', { form: form, timeout: 120000 });
      },
      again: listenTeach,
      onYes: function (r) { if (r.count != null) state.count = r.count; loadHistory(); }
    });
  }

  /* ---------- the view ---------- */
  C.register('teach', {
    path: '/teach', section: '#t-main', heading: '#h-teach', docKey: 'teach.doc', subKey: 'teach.sub',
    bind: function () {
      $('#teachMic').addEventListener('click', listenTeach);
      $('#undoBtn').addEventListener('click', function () {
        BW.unlockAudio();
        makeDraft({ action: 'undo' }, t('think.title'));
      });
    },
    show: function (args) {
      loadHistory();
      if (args.from) {   // "Make this an FAQ" from the dashboard
        var ref = args.from;
        C.clearArgs();
        makeDraft({ from_ref: ref }, t('teach.faq_thinking', { ref: ref }));
      }
    },
    signedOut: function () { state.history = null; },
    lang: function () { loadHistory(); }
  });
})();
