/* Caregiver app: idle -> listening -> thinking -> answer | did-you-mean | coordinator hand-off | error,
   plus "Check my reply". Talks to the FastAPI backend (POST /ask, /intent, /simplify, /requests/...). */
(function () {
  'use strict';
  var BW = window.BW, $ = BW.$, t = BW.t;

  var SCREENS = ['s-idle', 's-listen', 's-answer', 's-fallback', 's-error', 's-check', 's-reply'];
  var SPOKEN_OFFLINE = ['error.network', 'error.mic_denied', 'error.no_mic', 'error.unsupported', 'error.insecure', 'error.no_speech'];
  var ERRORS = {
    mic_denied: { icon: 'mic-off', title: 'err.mic_denied.title', msg: 'error.mic_denied' },
    no_mic: { icon: 'mic-off', title: 'err.no_mic.title', msg: 'error.no_mic' },
    unsupported: { icon: 'mic-off', title: 'err.unsupported.title', msg: 'error.unsupported' },
    insecure: { icon: 'lock', title: 'err.insecure.title', msg: 'error.insecure' },
    no_speech: { icon: 'ear', title: 'err.no_speech.title', msg: 'error.no_speech' },
    asr_error: { icon: 'ear', title: 'err.asr.title', msg: 'error.asr' },
    network: { icon: 'wifi-off', title: 'err.network.title', msg: 'error.network' }
  };

  var state = {
    sessionId: sessionId(),
    mode: 'ask',          // what the open recording is for: ask | clarify | check
    recorder: null,
    last: null,           // last /ask response
    lastQuestion: null,   // {text} or {audio} that produced it, for retry
    retry: null,
    whatsapp: null        // generic coordinator chat link
  };

  function sessionId() {
    try {
      var id = sessionStorage.getItem('bw.session');
      if (!id) { id = 's-' + Math.random().toString(36).slice(2) + Date.now().toString(36); sessionStorage.setItem('bw.session', id); }
      return id;
    } catch (e) { return 's-' + Date.now().toString(36); }
  }

  /* ---------- screens ---------- */
  function show(id, focusId) {
    SCREENS.forEach(function (s) { document.getElementById(s).hidden = (s !== id); });
    var h = document.getElementById(focusId);
    if (h) h.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  function nowLabel() {
    var time = new Date().toLocaleTimeString(BW.i18n.languages[BW.i18n.lang].speech, { hour: 'numeric', minute: '2-digit' });
    return t('time.today', { time: time });
  }
  function setWa(el, url) {
    if (!el) return;
    el.hidden = !url;
    if (url) { el.href = url; el.title = t('wa.new_tab'); }
  }
  function goIdle() {
    stopRecording(true);
    BW.stopAudio();
    show('s-idle', 'h-idle');
  }

  /* ---------- recording ---------- */
  var wave = new BW.Wave($('#wave'));

  function startListening(mode) {
    BW.unlockAudio();
    BW.stopAudio();
    stopRecording(true);
    state.mode = mode || 'ask';
    var listen = $('#s-listen');
    listen.classList.remove('thinking');
    $('#statusText').textContent = t('listen.ready');
    listen.classList.add('warming');
    $('#h-listen').textContent = state.mode === 'check' ? t('check.listening') :
      state.mode === 'clarify' ? t('clarify.say') : t('listen.title');
    $('#listenHint').textContent = t('listen.hint');
    $('#transcriptLabel').textContent = t('listen.words');
    $('#transcript').innerHTML = '<span class="placeholder">' + BW.esc(t('listen.placeholder')) + '</span>';
    $('#listenBtns').hidden = false;
    $('#stopMic').disabled = false;
    wave.reset();
    show('s-listen', 'h-listen');

    var rec = new BW.Recorder({
      onLevel: function (rms) { wave.push(rms); },
      onAutoStop: finishListening
    });
    state.recorder = rec;
    rec.start().then(function () {
      // Only now is the mic live: switch to "Recording" and start the rings, so people know to speak.
      if (state.recorder !== rec) return;
      listen.classList.remove('warming');
      $('#statusText').textContent = t('listen.status');
      BW.announce(t('listen.status'));
    }, function (e) {
      state.recorder = null;
      showError(e && e.code ? e.code : 'unsupported', function () { startListening(state.mode); });
    });
  }

  function stopRecording(cancel) {
    var rec = state.recorder; state.recorder = null;
    if (!rec) return null;
    if (cancel) { rec.cancel(); return null; }
    return rec.stop();
  }

  function finishListening() {
    var mode = state.mode;
    var rec = stopRecording(false);
    if (!rec) return;
    if (!rec.heard || rec.seconds < 0.3) {
      showError('no_speech', function () { startListening(mode); });
      return;
    }
    if (mode === 'check') lookupCode({ audio: rec.blob });
    else if (mode === 'clarify') sendClarifyReply(rec.blob);
    else ask({ audio: rec.blob });
  }

  function showThinking(heard) {
    var listen = $('#s-listen');
    listen.classList.remove('warming');
    listen.classList.add('thinking');
    $('#statusText').textContent = t('think.status');
    $('#h-listen').textContent = t('think.title');
    $('#listenHint').textContent = t('think.hint');
    $('#listenBtns').hidden = true;
    $('#stopMic').disabled = true;
    if (heard) {
      $('#transcriptLabel').textContent = t('think.heard');
      $('#transcript').textContent = heard;
    }
    if (listen.hidden) show('s-listen', 'h-listen');
    BW.announce(t('think.title'));
  }

  /* ---------- asking ---------- */
  function ask(q) {
    state.lastQuestion = q;
    showThinking(q.text);
    BW.api('/ask', { form: { audio: q.audio, text: q.text, lang: BW.i18n.lang, session_id: state.sessionId }, timeout: 60000 })
      .then(handleAnswer, function (e) {
        showError(e.kind === 'network' ? 'network' : 'asr_error', function () { ask(q); }, null);
      });
  }

  function handleAnswer(d) {
    state.last = d;
    if (d.fallback && (d.fallback_reason === 'asr_error' || d.fallback_reason === 'no_speech')) {
      showError(d.fallback_reason, function () { startListening('ask'); }, d.audio_url);
    } else if (d.fallback) {
      showFallback(d);
    } else if (d.clarify) {
      showAnswer(d, true);
    } else {
      showAnswer(d, false);
    }
  }

  function chip(cls, icon, text) {
    return '<span class="chip ' + cls + '">' + BW.icon(icon) + BW.esc(text) + '</span>';
  }

  function showAnswer(d, clarify) {
    $('#ansQ').textContent = d.transcript || '';
    $('#ansTime').textContent = nowLabel();
    var chips = clarify ? chip('', 'help', t('clarify.chip')) : chip('', 'shield', t('answer.verified'));
    if (!clarify && d.sample) chips += chip('chip-sample', 'flask', t('answer.sample'));
    $('#ansChips').innerHTML = chips;
    $('#h-answer').textContent = d.answer || '';
    var cap = d.lang !== 'en' && d.answer_en && d.answer_en !== d.answer;
    $('#ansCaption').hidden = !cap;
    $('#ansCaptionText').textContent = cap ? d.answer_en : '';
    $('#ansActions').hidden = clarify;
    $('#clarifyActions').hidden = !clarify;
    $('#ansSampleNote').hidden = clarify || !d.sample;
    var hasSource = !clarify && d.source;
    $('#ansDivider').hidden = !hasSource;
    $('#ansSource').hidden = !hasSource;
    $('#ansSource span').textContent = hasSource ? t('answer.source', { source: d.source }) : '';
    $('#askTitle').textContent = clarify ? t('clarify.say') : t('answer.ask_title');
    $('#askSub').textContent = clarify ? t('clarify.say_sub') : t('answer.ask_sub');
    $('#askMicBtn').setAttribute('aria-label', clarify ? t('clarify.say') : t('answer.ask_title'));
    $('#simplerBtn').disabled = false;
    $('#simplerBtn').removeAttribute('aria-busy');
    setWa($('#ansWa'), d.whatsapp_url);
    $('#ansNoAudio').hidden = !!d.audio_url;
    show('s-answer', 'h-answer');
    BW.bindPlayer($('#ansPlayer'), d.audio_url, true);
  }

  function showFallback(d) {
    var urgent = d.fallback_reason === 'urgent';
    $('#fbQ').textContent = d.transcript || '';
    $('#fbTime').textContent = nowLabel();
    $('#fbChip').textContent = urgent ? t('fb.chip_care') : t('fb.chip_sent');
    $('#h-fb').textContent = !d.reference ? t('fb.title_unsent') : urgent ? t('fb.title_urgent') : t('fb.title');
    $('#fbMsg').textContent = d.answer || '';
    $('#fbRefBox').hidden = !d.reference;
    $('#fbRef').textContent = d.reference || '';
    $('#fbSent').hidden = !d.reference;
    $('#fbCheckBtn').hidden = !d.reference;
    var cap = d.lang !== 'en' && d.answer_en && d.answer_en !== d.answer;
    $('#fbCaption').hidden = !cap;
    $('#fbCaptionText').textContent = cap ? d.answer_en : '';
    setWa($('#fbWa'), d.whatsapp_url);
    $('#fbCoord').hidden = !d.whatsapp_url;
    if (d.reference) rememberCode(d.reference, d.transcript);
    show('s-fallback', 'h-fb');
    BW.bindPlayer($('#fbPlayer'), d.audio_url, true);
  }

  function showError(code, retry, audioUrl) {
    var e = ERRORS[code] || ERRORS.asr_error;
    state.retry = retry || function () { startListening('ask'); };
    $('#errIcon').innerHTML = BW.icon(e.icon);
    $('#h-err').textContent = t(e.title);
    $('#errMsg').textContent = t(e.msg);
    show('s-error', 'h-err');
    var player = $('#errPlayer');
    if (audioUrl) { BW.bindPlayer(player, audioUrl, true); return; }
    player.hidden = true;
    BW.spoken(e.msg).then(function (url) { if (url && !$('#s-error').hidden) BW.bindPlayer(player, url, true); });
  }

  /* ---------- did-you-mean: spoken yes / no, buttons as backup ---------- */
  function clarifyYes() {
    var q = state.last && state.last.clarify_question;
    if (q) ask({ text: q }); else startListening('ask');
  }
  function sendClarifyReply(blob) {
    showThinking();
    BW.api('/intent', { form: { audio: blob, lang: BW.i18n.lang }, timeout: 30000 }).then(function (r) {
      if (r.intent === 'yes') clarifyYes();
      else if (r.intent === 'no') startListening('ask');
      else if (r.transcript) ask({ text: r.transcript }); // they asked something new instead
      else showError('no_speech', function () { startListening('clarify'); });
    }, function (e) {
      showError(e.kind === 'network' ? 'network' : 'asr_error', function () { startListening('clarify'); });
    });
  }

  /* ---------- say it again / simpler ---------- */
  function sayAgain() { var p = $('#ansPlayer'); BW.playIn(p, p.dataset.url, true); }
  function saySimpler() {
    var d = state.last, btn = $('#simplerBtn');
    if (!d || !d.source_id) return;
    btn.disabled = true; btn.setAttribute('aria-busy', 'true');
    BW.api('/simplify', { form: { source_id: d.source_id, answer: $('#h-answer').textContent, lang: d.lang }, timeout: 30000 })
      .then(function (r) {
        btn.removeAttribute('aria-busy');
        $('#h-answer').textContent = r.answer;
        $('#ansChips').insertAdjacentHTML('beforeend', chip('chip-ok', 'feather', t('answer.simpler_chip')));
        $('#ansNoAudio').hidden = !!r.audio_url;
        BW.bindPlayer($('#ansPlayer'), r.audio_url, true);
        BW.announce(r.answer);
      }, function () {
        btn.disabled = false; btn.removeAttribute('aria-busy');
        BW.toast(t('answer.simpler_fail'));
      });
  }

  /* ---------- check my reply ---------- */
  function recentCodes() {
    try { return JSON.parse(BW.store('bw.codes') || '[]'); } catch (e) { return []; }
  }
  function rememberCode(ref, question) {
    var list = recentCodes().filter(function (c) { return c.ref !== ref; });
    list.unshift({ ref: ref, q: question || '', at: Date.now() });
    BW.store('bw.codes', JSON.stringify(list.slice(0, 6)));
  }
  function renderRecent() {
    var list = recentCodes(), box = $('#recentCodes');
    $('#recentNone').hidden = list.length > 0;
    box.innerHTML = list.map(function (c) {
      var when = new Date(c.at).toLocaleDateString(BW.i18n.languages[BW.i18n.lang].speech, { day: 'numeric', month: 'short' });
      return '<button type="button" class="code-btn" data-ref="' + BW.esc(c.ref) + '"><span><strong>' + BW.esc(c.ref) +
        '</strong><span>' + BW.esc(t('check.asked_on', { when: when })) + (c.q ? ': ' + BW.esc(c.q) : '') + '</span></span>' +
        '<span class="go">' + BW.icon('chev-right') + '</span></button>';
    }).join('');
  }
  function openCheck(msg) {
    BW.stopAudio();
    renderRecent();
    $('#checkMsg').hidden = !msg;
    if (msg) { $('#checkMsgTitle').textContent = msg.title; $('#checkMsgText').textContent = msg.text; }
    show('s-check', 'h-check');
  }
  function lookupCode(q) {
    showThinking(q.ref);
    var req = q.ref ? BW.api('/requests/' + encodeURIComponent(q.ref)).then(function (r) { return { found: true, request: r }; },
      function (e) { if (e.kind === 'http' && e.status === 404) return { found: false, heard: q.ref }; throw e; })
      : BW.api('/requests/lookup', { form: { audio: q.audio, lang: BW.i18n.lang }, timeout: 45000 });
    req.then(function (r) {
      if (r.found) { showReply(r.request); return; }
      openCheck({ title: t('check.not_found_title'), text: r.heard ? t('check.heard', { heard: r.heard }) : '' });
      BW.spoken('check.not_found').then(BW.playUrl);
    }, function (e) {
      showError(e.kind === 'network' ? 'network' : 'asr_error', function () { lookupCode(q); });
    });
  }
  function showReply(r) {
    rememberCode(r.reference, r.question_text);
    $('#repQ').textContent = r.question_text || '';
    $('#repRef').textContent = r.reference;
    var replied = !!r.reply_text;
    var c = $('#repChip');
    c.className = 'chip' + (replied ? ' chip-ok' : '');
    c.innerHTML = BW.icon(replied ? 'check' : 'inbox') + BW.esc(t(replied ? 'check.replied_chip' : 'check.open_chip'));
    $('#h-reply').textContent = replied ? r.reply_text : (r.status === 'closed' ? t('check.closed') : t('check.open', { ref: r.reference }));
    setWa($('#repWa'), r.whatsapp_url);
    show('s-reply', 'h-reply');
    var player = $('#repPlayer');
    if (replied) { BW.bindPlayer(player, r.reply_audio_url, true); return; }
    player.hidden = true;
    BW.spoken('check.open', { ref: r.reference }).then(function (url) { if (url && !$('#s-reply').hidden) BW.bindPlayer(player, url, true); });
  }

  /* ---------- wiring ---------- */
  function bind() {
    $('#micBtn').addEventListener('click', function () { startListening('ask'); });
    $('#askMicBtn').addEventListener('click', function () {
      startListening(state.last && state.last.clarify && !$('#clarifyActions').hidden ? 'clarify' : 'ask');
    });
    $('#repMicBtn').addEventListener('click', function () { startListening('ask'); });
    $('#fbAgainBtn').addEventListener('click', function () { startListening('ask'); });
    $('#doneBtn').addEventListener('click', finishListening);
    $('#stopMic').addEventListener('click', finishListening);
    $('#cancelBtn').addEventListener('click', goIdle);
    $('#homeBtn').addEventListener('click', goIdle);
    $('#againBtn').addEventListener('click', sayAgain);
    $('#simplerBtn').addEventListener('click', saySimpler);
    $('#yesBtn').addEventListener('click', function () { BW.unlockAudio(); clarifyYes(); });
    $('#noBtn').addEventListener('click', function () { startListening('ask'); });
    $('#retryBtn').addEventListener('click', function () { BW.unlockAudio(); if (state.retry) state.retry(); });
    $('#errBackBtn').addEventListener('click', goIdle);
    $('#checkBtn').addEventListener('click', function () { openCheck(); });
    $('#fbCheckBtn').addEventListener('click', function () { openCheck(); });
    $('#repOtherBtn').addEventListener('click', function () { openCheck(); });
    $('#checkMicBtn').addEventListener('click', function () { startListening('check'); });
    $('#repAgainBtn').addEventListener('click', function () { var p = $('#repPlayer'); BW.playIn(p, p.dataset.url, true); });
    $('#recentCodes').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-ref]'); if (!b) return;
      BW.unlockAudio(); lookupCode({ ref: b.dataset.ref });
    });
    $('#examples').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-ex]'); if (!b) return;
      BW.unlockAudio(); BW.stopAudio();
      ask({ text: t('ex.' + b.dataset.ex + '.q') });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.recorder) goIdle();
    });
  }

  function loadConfig() {
    BW.api('/config?lang=' + BW.i18n.lang, { timeout: 10000 }).then(function (c) {
      state.whatsapp = c.whatsapp_url;
      BW.$$('.wa-generic').forEach(function (a) { setWa(a, c.whatsapp_url); });
    }, function () {});
  }

  BW.loadStrings().then(function () {
    BW.applyStrings();
    BW.bindLangPicker($('#langSel'));
    bind();
    loadConfig();
    BW.prefetchSpoken(SPOKEN_OFFLINE);
    BW.onLangChange(function () { loadConfig(); BW.prefetchSpoken(SPOKEN_OFFLINE); if (!$('#s-check').hidden) renderRecent(); });
    if (location.hash === '#check') openCheck(); else show('s-idle');
  }, function () {
    document.body.insertAdjacentHTML('afterbegin', '<p class="inline-msg" role="alert" style="margin:16px">' +
      'Could not load the assistant. Please check your internet and reload the page.</p>');
  });
})();
