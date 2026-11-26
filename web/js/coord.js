/* Coordinator pages: the shared shell for /dashboard (the queue) and /teach (teach by voice).
   One sign in (say the passcode, keypad as backup), the page views, and the voice sheet used everywhere:
   listen -> thinking -> read back -> spoken yes / no / change (buttons as backup) -> done.
   Talks to /coord/* and /kb/* (passcode cookie). */
(function () {
  'use strict';
  var BW = window.BW, $ = BW.$, t = BW.t;

  BW.langKey = 'bw.dash.lang';   // the coordinator's language, separate from the caregiver page
  BW.defaultLang = 'en';

  var ERRORS = {
    mic_denied: { icon: 'mic-off', msg: 'error.mic_denied' },
    no_mic: { icon: 'mic-off', msg: 'error.no_mic' },
    unsupported: { icon: 'mic-off', msg: 'error.unsupported' },
    insecure: { icon: 'lock', msg: 'error.insecure' },
    no_speech: { icon: 'ear', msg: 'error.no_speech' },
    asr_error: { icon: 'ear', msg: 'error.asr' },
    network: { icon: 'wifi-off', msg: 'error.network' },
    translate_error: { icon: 'globe', msg: 'reply.translate_fail' },
    teach_error: { icon: 'alert', msg: 'teach.error' },
    save_error: { icon: 'alert', msg: 'teach.save_fail' },
    failed: { icon: 'alert', msg: 'req.action_fail' }
  };
  var KNOWN = ['no_speech', 'asr_error', 'translate_error', 'teach_error', 'save_error'];
  var PIN_MAX = 8;

  var C = BW.coord = { ERRORS: ERRORS, views: {} };
  var state = {
    pin: '', recorder: null, onRecorded: null, retry: null, autoConfirm: null, lastFocus: null,
    signedIn: false, view: null, draft: null
  };
  var wave;

  /* ---------- helpers ---------- */
  C.speech = function () { return BW.i18n.languages[BW.i18n.lang].speech; };
  C.langName = function (code) { return t('langname.' + code); };
  C.ago = function (iso) {
    var mins = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return t('ago.now');
    if (mins < 60) return t('ago.min', { n: Math.floor(mins) });
    if (mins < 1440) return t('ago.hr', { n: Math.floor(mins / 60) });
    return t('ago.day', { n: Math.floor(mins / 1440) });
  };
  C.errCode = function (e) {
    if (!e || e.kind === 'network') return 'network';
    var detail = e.body && (e.body.detail || e.body.error);
    return KNOWN.indexOf(detail) >= 0 ? detail : 'failed';
  };
  C.signedIn = function () { return state.signedIn; };
  /* Every coordinator call: a 401 means the session ended, so go back to sign in. */
  C.capi = function (path, opts) {
    return BW.api(path, opts).catch(function (e) {
      if (e.kind === 'http' && e.status === 401 && path.indexOf('/coord/login') !== 0) { C.closeSheet(); showLogin(); }
      throw e;
    });
  };
  C.chip = function (cls, icon, text, lang) {
    return '<span class="chip ' + cls + '"' + (lang ? ' lang="' + lang + '"' : '') + '>' + BW.icon(icon) + BW.esc(text) + '</span>';
  };

  /* ---------- views: /dashboard and /teach share the page and the sign in ---------- */
  C.register = function (name, view) { C.views[name] = view; };
  function viewFromPath() {
    var names = Object.keys(C.views);
    for (var i = 0; i < names.length; i++) if (C.views[names[i]].path === location.pathname) return names[i];
    return names[0];
  }
  function params() {
    var out = {};
    new URLSearchParams(location.search).forEach(function (v, k) { out[k] = v; });
    return out;
  }
  C.go = function (name, args, opts) {
    opts = opts || {};
    var view = C.views[name]; if (!view) return;
    if (opts.push !== false) {
      var qs = args && Object.keys(args).length ? '?' + new URLSearchParams(args).toString() : '';
      if (location.pathname + location.search !== view.path + qs) history.pushState({ view: name }, '', view.path + qs);
    }
    var prev = state.view;
    state.view = name;
    applyViewChrome();
    if (!state.signedIn) return;
    Object.keys(C.views).forEach(function (n) { $(C.views[n].section).hidden = n !== name; });
    if (prev && prev !== name && C.views[prev].hide) C.views[prev].hide();
    if (!opts.quiet) $(view.heading).focus({ preventScroll: true });
    window.scrollTo(0, 0);
    view.show(args || {});
  };
  /* Without a URL change: drop ?from=... once it has been used, so a reload does not repeat it. */
  C.clearArgs = function () {
    var view = C.views[state.view];
    if (view && location.search) history.replaceState({ view: state.view }, '', view.path);
  };
  function applyViewChrome() {
    var view = C.views[state.view];
    // The keys move with the view, so a language change (applyStrings) keeps the right page name.
    document.querySelector('title').dataset.i18nDoc = view.docKey;
    document.title = t(view.docKey);
    $('#brandSub').dataset.i18n = view.subKey;
    $('#brandSub').textContent = t(view.subKey);
    BW.$$('#coordNav a').forEach(function (a) {
      if (a.dataset.view === state.view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }

  /* ---------- screens ---------- */
  function showLogin(msg) {
    state.signedIn = false;
    Object.keys(C.views).forEach(function (n) {
      $(C.views[n].section).hidden = true;
      if (C.views[n].signedOut) C.views[n].signedOut();
    });
    $('#d-login').hidden = false; $('#signoutBtn').hidden = true; $('#coordNav').hidden = true;
    state.pin = ''; renderPin();
    loginMessage(msg);
    $('#h-login').focus({ preventScroll: true });
  }
  function loginMessage(msg) {
    $('#loginMsg').hidden = !msg;
    $('#loginMsgText').textContent = msg || '';
  }
  function showMain() {
    state.signedIn = true;
    $('#d-login').hidden = true; $('#signoutBtn').hidden = false; $('#coordNav').hidden = false;
    C.go(state.view || viewFromPath(), params(), { push: false });
  }

  /* ---------- sign in ---------- */
  function renderPin() {
    var n = state.pin.length, dots = '';
    for (var i = 0; i < Math.max(4, n); i++) dots += '<span class="pin-dot' + (i < n ? ' on' : '') + '"></span>';
    $('#pinDots').innerHTML = dots + '<span class="sr-only">' + BW.esc(t('login.entered', { n: n })) + '</span>';
    $('#pinGo').disabled = n < 4;
  }
  function pressKey(k) {
    if (k === 'del') state.pin = state.pin.slice(0, -1);
    else if (k === 'go') { if (state.pin.length >= 4) loginWith({ code: state.pin }); return; }
    else if (state.pin.length < PIN_MAX) state.pin += k;
    renderPin();
  }
  function loginWith(form) {
    BW.unlockAudio();
    form.lang = BW.i18n.lang;
    if (form.audio) C.thinking(t('login.checking'));
    var btn = $('#pinGo'); btn.setAttribute('aria-busy', 'true');
    C.capi('/coord/login', { form: form, timeout: 45000 }).then(function (r) {
      btn.removeAttribute('aria-busy');
      C.closeSheet();
      if (r.audio_url) BW.playUrl(r.audio_url);
      BW.announce(r.text);
      showMain();
    }, function (e) {
      btn.removeAttribute('aria-busy');
      state.pin = ''; renderPin();
      var body = e.body || {};
      if (e.kind === 'http' && body.text) {
        if (body.audio_url) BW.playUrl(body.audio_url);
        if (form.audio && body.error !== 'login.locked' && body.error !== 'login.not_set') {
          C.error(body.text, 'lock', listenLogin);
        } else { C.closeSheet(); loginMessage(body.text); }
        return;
      }
      var code = C.errCode(e);
      if (form.audio) C.errorFor(code, listenLogin);
      else { loginMessage(t(ERRORS[code].msg)); BW.spoken(ERRORS[code].msg).then(BW.playUrl); }
    });
  }
  function listenLogin() {
    C.listen({ title: t('login.title'), prompt: t('login.say'), hint: t('login.sub'),
      onAudio: function (blob) { loginWith({ audio: blob }); }, again: listenLogin });
  }

  /* ---------- the voice sheet ---------- */
  C.stage = function (id) {
    ['st-listen', 'st-draft', 'st-done', 'st-error'].forEach(function (s) { $('#' + s).hidden = s !== id; });
  };
  /* quote: {label, text, lang} shown above the stages (the caregiver's question), or null. */
  C.openSheet = function (title, quote) {
    if ($('#sheet').hidden) state.lastFocus = document.activeElement;
    $('#sheetTitle').textContent = title;
    $('#sheetQ').hidden = !quote;
    if (quote) {
      $('#sheetQLabel').textContent = quote.label || t('req.asked');
      $('#sheetQText').textContent = quote.text || '';
      $('#sheetQText').lang = quote.lang || '';
    }
    $('#sheet').hidden = false;
    $('#app').setAttribute('inert', '');
    $('#sheetTitle').focus({ preventScroll: true });
  };
  C.closeSheet = function () {
    stopRecording(true);
    cancelAutoConfirm();
    if ($('#sheet').hidden) return;
    BW.stopAudio();
    $('#sheet').hidden = true;
    $('#app').removeAttribute('inert');
    state.draft = null;
    if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus({ preventScroll: true });
  };
  C.sheetOpen = function () { return !$('#sheet').hidden; };

  /* Listen in the sheet: {title, quote, prompt, hint, rec: Recorder options, onAudio(blob), again()}. */
  C.listen = function (o) {
    BW.unlockAudio(); BW.stopAudio(); stopRecording(true); cancelAutoConfirm();
    C.openSheet(o.title, o.quote);
    var st = $('#st-listen');
    C.stage('st-listen');
    st.classList.remove('thinking'); st.classList.add('warming');
    $('#sheetStatus').textContent = t('listen.ready');
    $('#sheetPrompt').textContent = o.prompt;
    $('#sheetHint').textContent = o.hint || '';
    $('#sheetListenBtns').hidden = false;
    $('#sheetMic').disabled = false;
    wave.reset();
    record(o.rec || {}, function (blob) {
      if (!blob) { C.errorFor('no_speech', o.again); return; }
      o.onAudio(blob);
    }, function (code) { C.errorFor(code, o.again); }, function () {
      if (state.recorder) { st.classList.remove('warming'); $('#sheetStatus').textContent = t('listen.status'); BW.announce(t('listen.status')); }
    });
  };

  /* Start the recorder; onDone(blob | null when nothing was heard), onFail(code), onLive(). */
  function record(opts, onDone, onFail, onLive) {
    var rec = new BW.Recorder({
      onLevel: function (rms) { wave.push(rms); },
      onAutoStop: finishRecording,
      giveUpMs: opts.giveUpMs, maxMs: opts.maxMs, silenceMs: opts.silenceMs
    });
    state.recorder = rec; state.onRecorded = onDone;
    rec.start().then(function () { if (state.recorder === rec && onLive) onLive(); }, function (e) {
      if (state.recorder !== rec) return;
      state.recorder = null;
      onFail(e && e.code && ERRORS[e.code] ? e.code : 'unsupported');
    });
  }
  function stopRecording(cancel) {
    var rec = state.recorder; state.recorder = null;
    if (!rec) return null;
    if (cancel) { rec.cancel(); return null; }
    return rec.stop();
  }
  function finishRecording() {
    var cb = state.onRecorded, r = stopRecording(false);
    if (!r || !cb) return;
    cb(r.heard && r.seconds >= 0.3 ? r.blob : null);
  }

  C.thinking = function (text) {
    var st = $('#st-listen');
    C.stage('st-listen');
    st.classList.remove('warming'); st.classList.add('thinking');
    $('#sheetStatus').textContent = t('think.status');
    $('#sheetPrompt').textContent = text;
    $('#sheetHint').textContent = '';
    $('#sheetListenBtns').hidden = true;
    $('#sheetMic').disabled = true;
    BW.announce(text);
  };

  C.error = function (text, icon, retry, spokenKey) {
    if ($('#sheet').hidden) C.openSheet(t('err.chip'));
    C.stage('st-error');
    state.retry = retry;
    $('#sheetRetry').hidden = !retry;
    $('#sheetErrIcon').innerHTML = BW.icon(icon || 'alert');
    $('#sheetErrText').textContent = text;
    (retry ? $('#sheetRetry') : $('#sheetErrCancel')).focus({ preventScroll: true });
    BW.announce(text);
    if (spokenKey) BW.spoken(spokenKey).then(function (url) { if (url && !$('#st-error').hidden) BW.playUrl(url); });
  };
  C.errorFor = function (code, retry) {
    var e = ERRORS[code] || ERRORS.failed;
    C.error(t(e.msg), e.icon, retry, e.msg);
  };
  /* A server message with its own text and audio (e.g. "I could not find a question and an answer"). */
  C.errorSaid = function (body, icon, retry) {
    C.error(body.text, icon, retry);
    if (body.audio_url) BW.playUrl(body.audio_url);
  };

  /* ---------- read back, then a spoken (or tapped) yes / no / change ----------
     o: {chip, bodyHtml, audioUrl, approveLabel, confirmHint, busyText, doneTitle, send(form) -> Promise(response),
         again(), onYes(r)} */
  C.showDraft = function (o) {
    state.draft = o;
    C.stage('st-draft');
    $('#draftChip').textContent = o.chip;
    $('#draftBody').innerHTML = o.bodyHtml;
    $('#approveLabel').textContent = o.approveLabel;
    confirmIdle();
    $('#approveBtn').disabled = false;
    $('#sheetTitle').focus({ preventScroll: true });
    BW.bindPlayer($('#draftPlayer'), o.audioUrl, true);
    // After the read back finishes, listen for the answer straight away (the buttons stay as backup).
    if (o.audioUrl) {
      var onEnd = function () {
        BW.audio.removeEventListener('ended', onEnd);
        state.autoConfirm = null;
        if (state.draft === o && !$('#st-draft').hidden && !state.recorder) listenConfirm(true);
      };
      state.autoConfirm = onEnd;
      BW.audio.addEventListener('ended', onEnd);
    }
  };
  function cancelAutoConfirm() {
    if (state.autoConfirm) { BW.audio.removeEventListener('ended', state.autoConfirm); state.autoConfirm = null; }
  }
  function confirmIdle(hint) {
    $('#confirmMic').classList.remove('rec');
    $('#confirmMic').setAttribute('aria-label', t('reply.confirm_say'));
    $('#confirmTitle').textContent = t('reply.confirm_say');
    $('#confirmHint').textContent = hint || (state.draft && state.draft.confirmHint) || t('reply.confirm_hint');
  }
  function listenConfirm(auto) {
    if (state.recorder) { finishRecording(); return; }   // second tap: done speaking
    cancelAutoConfirm();
    BW.unlockAudio(); BW.stopAudio();
    var mic = $('#confirmMic');
    mic.classList.add('rec');
    mic.setAttribute('aria-label', t('a11y.stop'));
    $('#confirmTitle').textContent = t('reply.listening_yes');
    record({ giveUpMs: 7000 }, function (blob) {
      if (!blob) { confirmIdle(); return; }           // nothing said: just leave the buttons
      sendDecision({ audio: blob });
    }, function (code) {
      confirmIdle();
      if (!auto) C.errorFor(code, function () { C.stage('st-draft'); });
    });
  }
  function sendDecision(form) {
    var dr = state.draft; if (!dr) return;
    stopRecording(true); cancelAutoConfirm(); BW.stopAudio();
    form.lang = BW.i18n.lang;
    $('#approveBtn').disabled = true;
    $('#approveBtn').setAttribute('aria-busy', 'true');
    $('#confirmTitle').textContent = form.decision === 'yes' ? (dr.busyText || t('reply.sending')) : t('think.title');
    $('#confirmMic').classList.remove('rec');
    dr.send(form).then(function (r) {
      $('#approveBtn').disabled = false; $('#approveBtn').removeAttribute('aria-busy');
      if (state.draft !== dr) return;
      if (r.decision === 'yes') {
        C.done(dr.doneTitle, r.text);
        if (r.audio_url) BW.playUrl(r.audio_url);
        if (dr.onYes) dr.onYes(r);
      } else if (r.decision === 'no') {
        C.closeSheet();
        BW.toast(r.text);
        if (r.audio_url) BW.playUrl(r.audio_url);
      } else if (r.decision === 'change') {
        dr.again();
      } else {
        confirmIdle(r.text);
        if (r.audio_url) BW.playUrl(r.audio_url);
      }
    }, function (e) {
      $('#approveBtn').disabled = false; $('#approveBtn').removeAttribute('aria-busy');
      if (e.kind === 'http' && e.status === 401) return;
      var body = e.body || {};
      if (e.kind === 'http' && body.text) {          // e.g. the draft is gone or something changed meanwhile
        C.errorSaid(body, 'info', dr.again);
        return;
      }
      confirmIdle();
      var code = C.errCode(e);
      BW.toast(t(ERRORS[code].msg));
      BW.spoken(ERRORS[code].msg).then(BW.playUrl);
    });
  }
  C.done = function (title, text) {
    C.stage('st-done');
    $('#doneTitle').textContent = title;
    $('#doneText').textContent = text;
    $('#doneBtn').focus({ preventScroll: true });
  };

  /* ---------- wiring ---------- */
  function bind() {
    wave = new BW.Wave($('#sheetWave'));
    $('#loginMic').addEventListener('click', function () { loginMessage(); listenLogin(); });
    $('#keypad').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-key]'); if (b) pressKey(b.dataset.key);
    });
    $('#pinGo').addEventListener('click', function () { pressKey('go'); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !$('#sheet').hidden) { C.closeSheet(); return; }
      if (!$('#d-login').hidden && $('#sheet').hidden) {   // physical keyboard works too, never required
        if (/^[0-9]$/.test(e.key)) pressKey(e.key);
        else if (e.key === 'Backspace') pressKey('del');
        else if (e.key === 'Enter' && document.activeElement === document.body) pressKey('go');
      }
    });
    $('#signoutBtn').addEventListener('click', function () {
      C.capi('/coord/logout', { method: 'POST' }).catch(function () {}).then(function () { showLogin(); });
    });
    $('#coordNav').addEventListener('click', function (e) {
      var a = e.target.closest('a[data-view]');
      if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;   // let "open in new tab" work
      e.preventDefault();
      if (a.dataset.view !== state.view) C.go(a.dataset.view);
    });
    window.addEventListener('popstate', function () {
      C.closeSheet();
      C.go(viewFromPath(), params(), { push: false });
    });
    $('#sheetMic').addEventListener('click', finishRecording);
    $('#sheetDone').addEventListener('click', finishRecording);
    $('#sheetCancel').addEventListener('click', C.closeSheet);
    $('#sheetClose').addEventListener('click', C.closeSheet);
    $('#sheetErrCancel').addEventListener('click', C.closeSheet);
    $('#sheetRetry').addEventListener('click', function () { BW.unlockAudio(); if (state.retry) state.retry(); });
    $('#confirmMic').addEventListener('click', function () { listenConfirm(false); });
    $('#approveBtn').addEventListener('click', function () { BW.unlockAudio(); sendDecision({ decision: 'yes' }); });
    $('#againBtn').addEventListener('click', function () { if (state.draft) state.draft.again(); });
    $('#draftCancel').addEventListener('click', function () { sendDecision({ decision: 'no' }); });
    $('#doneBtn').addEventListener('click', C.closeSheet);
    $('#sheet').addEventListener('click', function (e) { if (e.target === $('#sheet') && !state.recorder) C.closeSheet(); });
  }

  C.start = function () {
    BW.loadStrings().then(function () {
      BW.applyStrings();
      BW.bindLangPicker($('#langSel'));
      bind();
      Object.keys(C.views).forEach(function (n) { if (C.views[n].bind) C.views[n].bind(); });
      state.view = viewFromPath();
      applyViewChrome();
      renderPin();
      BW.prefetchSpoken(['error.network', 'error.mic_denied', 'error.no_speech']);
      BW.onLangChange(function () {
        renderPin();
        applyViewChrome();
        if (state.signedIn && C.views[state.view].lang) C.views[state.view].lang();
      });
      BW.api('/coord/me', { timeout: 10000 }).then(function (me) {
        if (me.signed_in) showMain();
        else showLogin(me.configured ? null : t('login.not_set'));
      }, function () { showLogin(t('error.network')); });
    }, function () {
      document.body.insertAdjacentHTML('afterbegin', '<p class="inline-msg" role="alert" style="margin:16px">' +
        'Could not load the coordinator page. Please check your internet and reload the page.</p>');
    });
  };
})();
