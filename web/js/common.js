/* Shared by every Blood Warriors page: translations, the voice recorder, the audio player, API calls,
   spoken UI messages and the toast. No framework, no build step. */
(function () {
  'use strict';

  // Browsers only allow the microphone on https, localhost or 127.0.0.1. 0.0.0.0 (what the server log
  // prints) is none of these, so open the same page on localhost instead.
  if (location.hostname === '0.0.0.0') {
    location.replace(location.protocol + '//localhost' + (location.port ? ':' + location.port : '') +
      location.pathname + location.search + location.hash);
    return;
  }

  var BW = window.BW = {};

  /* ---------- small helpers ---------- */
  BW.$ = function (sel, root) { return (root || document).querySelector(sel); };
  BW.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  BW.icon = function (name, extra) {
    return '<svg class="i' + (extra ? ' ' + extra : '') + '" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  };
  BW.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  BW.fmtTime = function (s) { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  BW.reducedMotion = function () { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; };
  function store(key, val) {
    try { if (val === undefined) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (e) { return null; }
  }
  BW.store = store;

  /* ---------- translations: one file, i18n/strings.json ---------- */
  var I18N = { strings: {}, languages: {}, lang: 'te', listeners: [] };
  BW.i18n = I18N;
  // Each page can keep its own language (the dashboard sets these before loadStrings).
  BW.langKey = 'bw.lang';
  BW.defaultLang = null;

  BW.loadStrings = function () {
    return fetch('/i18n/strings.json', { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error('strings ' + r.status);
      return r.json();
    }).then(function (data) {
      I18N.strings = data.strings; I18N.languages = data.languages;
      var saved = store(BW.langKey);
      I18N.lang = saved && data.languages[saved] ? saved :
        (BW.defaultLang && data.languages[BW.defaultLang] ? BW.defaultLang : Object.keys(data.languages)[0]);
      return data;
    });
  };

  BW.t = function (key, vars) {
    var entry = I18N.strings[key];
    var text = entry ? (entry[I18N.lang] || entry.en) : key;
    if (vars) Object.keys(vars).forEach(function (k) { text = text.split('{' + k + '}').join(vars[k]); });
    return text;
  };

  /* Fill every [data-i18n] (text), [data-i18n-aria] (aria-label) and [data-i18n-title] in root. */
  BW.applyStrings = function (root) {
    root = root || document;
    BW.$$('[data-i18n]', root).forEach(function (el) { el.textContent = BW.t(el.dataset.i18n); });
    BW.$$('[data-i18n-aria]', root).forEach(function (el) { el.setAttribute('aria-label', BW.t(el.dataset.i18nAria)); });
    BW.$$('[data-i18n-title]', root).forEach(function (el) { el.setAttribute('title', BW.t(el.dataset.i18nTitle)); });
    document.documentElement.lang = I18N.lang;
    var title = document.querySelector('title[data-i18n-doc]');
    if (title) document.title = BW.t(title.dataset.i18nDoc);
  };

  BW.setLang = function (lang) {
    if (!I18N.languages[lang]) return;
    I18N.lang = lang; store(BW.langKey, lang);
    BW.applyStrings();
    I18N.listeners.forEach(function (fn) { fn(lang); });
  };
  BW.onLangChange = function (fn) { I18N.listeners.push(fn); };

  /* Language picker in the header: globe icon + language name. */
  BW.bindLangPicker = function (select) {
    select.innerHTML = Object.keys(I18N.languages).map(function (code) {
      var l = I18N.languages[code];  // each language in its own script, so people find theirs at a glance
      return '<option value="' + code + '" lang="' + code + '">' + BW.esc(l.name) + '</option>';
    }).join('');
    select.value = I18N.lang;
    select.addEventListener('change', function () {
      BW.setLang(select.value);
      BW.toast(BW.t('lang.changed', { lang: I18N.languages[select.value].name }));
    });
  };

  /* ---------- toast + screen-reader announcements ---------- */
  var toastTimer = null;
  BW.toast = function (msg) {
    var el = BW.$('#toast'); if (!el) return;
    el.textContent = msg; el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('show'); }, 3200);
  };
  BW.announce = function (msg) {
    var el = BW.$('#sr-status'); if (!el) return;
    el.textContent = ''; setTimeout(function () { el.textContent = msg; }, 30);
  };

  /* ---------- API ---------- */
  function ApiError(kind, status, body) { this.kind = kind; this.status = status; this.body = body; }
  BW.ApiError = ApiError;

  BW.api = function (path, opts) {
    opts = opts || {};
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = ctrl && setTimeout(function () { ctrl.abort(); }, opts.timeout || 45000);
    var init = { method: opts.method || (opts.form ? 'POST' : 'GET'), headers: opts.headers || {} };
    if (opts.form) {
      var fd = new FormData();
      Object.keys(opts.form).forEach(function (k) {
        var v = opts.form[k];
        if (v == null) return;
        if (v instanceof Blob) fd.append(k, v, k === 'audio' ? 'speech.wav' : 'file');
        else fd.append(k, v);
      });
      init.body = fd;
    }
    if (opts.json) { init.body = JSON.stringify(opts.json); init.headers['Content-Type'] = 'application/json'; }
    if (ctrl) init.signal = ctrl.signal;
    return fetch(path, init).then(function (r) {
      clearTimeout(timer);
      return r.json().catch(function () { return null; }).then(function (body) {
        if (!r.ok) throw new ApiError('http', r.status, body);
        return body;
      });
    }, function (e) {
      clearTimeout(timer);
      throw new ApiError('network', 0, null);
    });
  };

  /* ---------- audio: one shared <audio> element ---------- */
  var audio = new Audio();
  audio.preload = 'auto';
  BW.audio = audio;
  var active = null; // {el, url}

  // iOS/Safari only let audio play after a tap; play a silent clip inside the tap so later answers autoplay.
  var SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=';
  BW.unlockAudio = function () {
    if (BW._unlocked) return;
    BW._unlocked = true;
    try { audio.src = SILENT; var p = audio.play(); if (p && p.catch) p.catch(function () {}); } catch (e) {}
  };

  function setIcon(el, playing) {
    var btn = el.querySelector('.play'); if (!btn) return;
    btn.querySelector('use').setAttribute('href', playing ? '#i-pause' : '#i-play');
    btn.setAttribute('aria-label', BW.t(playing ? 'a11y.pause' : 'a11y.play'));
  }
  function paint(el) {
    var bar = el.querySelector('.bar'), time = el.querySelector('.ptime');
    var dur = isFinite(audio.duration) ? audio.duration : 0;
    if (bar) bar.style.width = (dur ? (audio.currentTime / dur * 100) : 0) + '%';
    if (time) time.textContent = BW.fmtTime(audio.currentTime) + (dur ? ' / ' + BW.fmtTime(dur) : '');
  }
  audio.addEventListener('timeupdate', function () { if (active) paint(active.el); });
  audio.addEventListener('loadedmetadata', function () { if (active) paint(active.el); });
  audio.addEventListener('play', function () { if (active) setIcon(active.el, true); });
  audio.addEventListener('pause', function () { if (active) setIcon(active.el, false); });
  audio.addEventListener('ended', function () { if (active) { setIcon(active.el, false); paint(active.el); } });

  BW.stopAudio = function () {
    try { audio.pause(); } catch (e) {}
    if (active) setIcon(active.el, false);
  };

  /* Play url through a .player element (play button, progress bar, time). Returns a promise. */
  BW.playIn = function (el, url, fromStart) {
    if (!url) return Promise.resolve();
    if (!active || active.url !== url || active.el !== el) {
      if (active && active.el !== el) setIcon(active.el, false);
      active = { el: el, url: url };
      audio.src = url;
    } else if (fromStart) {
      audio.currentTime = 0;
    }
    var p = audio.play();
    return (p && p.catch) ? p.catch(function () { setIcon(el, false); }) : Promise.resolve();
  };

  /* Wire a .player element to an audio url. autoplay: start now (after a tap it is allowed). */
  BW.bindPlayer = function (el, url, autoplay) {
    if (!el) return;
    el.hidden = !url;
    var bar = el.querySelector('.bar'), time = el.querySelector('.ptime');
    if (bar) bar.style.width = '0';
    if (time) time.textContent = '0:00';
    setIcon(el, false);
    el.querySelector('.play').onclick = function () {
      if (active && active.el === el && active.url === url && !audio.paused) { audio.pause(); return; }
      BW.playIn(el, url);
    };
    el.dataset.url = url || '';
    if (url && autoplay) BW.playIn(el, url, true);
  };

  /* Play any url without a player element (spoken UI messages). */
  BW.playUrl = function (url) {
    if (!url) return;
    if (active) setIcon(active.el, false);
    active = null; audio.src = url;
    var p = audio.play(); if (p && p.catch) p.catch(function () {});
  };

  /* Spoken UI message from the translations file. Messages needed when the network is down are fetched
     ahead of time (prefetchSpoken) and kept as local blobs. */
  var spokenCache = {};
  BW.spoken = function (key, vars) {
    var lang = I18N.lang, ck = lang + ':' + key + ':' + JSON.stringify(vars || {});
    if (spokenCache[ck]) return Promise.resolve(spokenCache[ck]);
    var q = '/speak?key=' + encodeURIComponent(key) + '&lang=' + lang + (vars && vars.ref ? '&ref=' + encodeURIComponent(vars.ref) : '');
    return BW.api(q, { timeout: 15000 }).then(function (d) { spokenCache[ck] = d.audio_url; return d.audio_url; },
      function () { return null; });
  };
  BW.prefetchSpoken = function (keys) {
    keys.forEach(function (key) {
      var ck = I18N.lang + ':' + key + ':{}';
      if (spokenCache[ck] && spokenCache[ck].indexOf('blob:') === 0) return;
      BW.spoken(key).then(function (url) {
        if (!url) return;
        return fetch(url).then(function (r) { return r.blob(); }).then(function (b) {
          spokenCache[ck] = URL.createObjectURL(b);
        });
      }).catch(function () {});
    });
  };

  /* ---------- recorder: 16 kHz mono WAV, live level, stops by itself after you finish ---------- */
  function RecorderError(code) { this.code = code; }
  BW.RecorderError = RecorderError;

  BW.Recorder = function (opts) {
    this.opts = opts || {};
  };
  BW.Recorder.supported = function () {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
      (window.AudioContext || window.webkitAudioContext));
  };
  BW.Recorder.prototype.start = function () {
    var self = this, o = this.opts;
    if (window.isSecureContext === false) return Promise.reject(new RecorderError('insecure'));  // plain http, not localhost
    if (!BW.Recorder.supported()) return Promise.reject(new RecorderError('unsupported'));
    // Create and resume the AudioContext inside the tap: created later (after the permission prompt), Safari
    // and Chrome can leave it suspended, and a suspended context records only silence.
    var Ctx = window.AudioContext || window.webkitAudioContext;
    var ctx = new Ctx();
    var resumed = ctx.state === 'suspended' && ctx.resume ? ctx.resume() : Promise.resolve();
    // Noise suppression off: it softened word onsets and IndicConformer misheard the first word (measured on c02).
    return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: true, channelCount: 1 } })
      .catch(function (e) {
        try { ctx.close(); } catch (x) {}
        var name = e && e.name;
        if (name === 'NotAllowedError' || name === 'SecurityError') throw new RecorderError('mic_denied');
        if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'NotReadableError') throw new RecorderError('no_mic');
        throw new RecorderError('unsupported');
      })
      .then(function (stream) { return resumed.then(function () { return stream; }); })
      .then(function (stream) {
        if (ctx.state === 'suspended' && ctx.resume) ctx.resume();
        var src = ctx.createMediaStreamSource(stream);
        var analyser = ctx.createAnalyser(); analyser.fftSize = 1024;
        var proc = ctx.createScriptProcessor(4096, 1, 1);
        var chunks = [];
        proc.onaudioprocess = function (e) { if (!self.stopped) chunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
        src.connect(analyser); src.connect(proc); proc.connect(ctx.destination);
        self.stream = stream; self.ctx = ctx; self.src = src; self.proc = proc; self.analyser = analyser;
        self.chunks = chunks; self.heard = false; self.stopped = false; self.peak = 0;
        var started = performance.now(), lastVoice = started, buf = new Float32Array(analyser.fftSize);
        var maxMs = o.maxMs || 30000, silenceMs = o.silenceMs || 1800, giveUpMs = o.giveUpMs || 8000;
        (function tick() {
          if (self.stopped) return;
          analyser.getFloatTimeDomainData(buf);
          var sum = 0; for (var i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
          var rms = Math.sqrt(sum / buf.length), now = performance.now();
          self.peak = Math.max(self.peak, rms);
          if (rms > (o.speechLevel || 0.02)) { self.heard = true; lastVoice = now; }
          if (o.onLevel) o.onLevel(rms);
          var elapsed = now - started;
          if ((self.heard && now - lastVoice > silenceMs) || elapsed > maxMs || (!self.heard && elapsed > giveUpMs)) {
            if (o.onAutoStop) o.onAutoStop();
            return;
          }
          self.raf = requestAnimationFrame(tick);
        })();
      });
  };
  BW.Recorder.prototype._teardown = function () {
    this.stopped = true;
    cancelAnimationFrame(this.raf);
    try { this.src.disconnect(); this.proc.disconnect(); } catch (e) {}
    if (this.stream) this.stream.getTracks().forEach(function (t) { t.stop(); });
    if (this.ctx && this.ctx.state !== 'closed') this.ctx.close();
  };
  BW.Recorder.prototype.cancel = function () { if (!this.stopped && this.ctx) this._teardown(); };
  /* -> {blob: WAV 16 kHz mono, heard: bool, seconds} */
  BW.Recorder.prototype.stop = function () {
    if (this.stopped || !this.ctx) return null;
    var rate = this.ctx.sampleRate;
    this._teardown();
    var total = this.chunks.reduce(function (n, c) { return n + c.length; }, 0);
    var all = new Float32Array(total), off = 0;
    this.chunks.forEach(function (c) { all.set(c, off); off += c.length; });
    var pcm = downsample(all, rate, 16000);
    BW.lastRecording = { heard: this.heard, peak: this.peak, seconds: pcm.length / 16000, rate: rate }; // for debugging
    return { blob: encodeWav(pcm, 16000), heard: this.heard, seconds: pcm.length / 16000 };
  };

  function downsample(data, from, to) {
    if (from === to) return data;
    var ratio = from / to, n = Math.floor(data.length / ratio), out = new Float32Array(n);
    for (var i = 0; i < n; i++) {
      var start = Math.floor(i * ratio), end = Math.min(Math.floor((i + 1) * ratio), data.length), s = 0;
      for (var j = start; j < end; j++) s += data[j];
      out[i] = end > start ? s / (end - start) : 0;
    }
    return out;
  }
  function encodeWav(pcm, rate) {
    var buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
    function str(o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    str(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data');
    v.setUint32(40, pcm.length * 2, true);
    for (var i = 0; i < pcm.length; i++) {
      var s = Math.max(-1, Math.min(1, pcm[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return new Blob([buf], { type: 'audio/wav' });
  }

  /* Live waveform: bars follow the voice level (static when reduced motion is on). */
  BW.Wave = function (el) {
    this.bars = BW.$$('span', el); this.hist = this.bars.map(function () { return 0; });
  };
  BW.Wave.prototype.push = function (rms) {
    if (BW.reducedMotion()) return;
    this.hist.shift(); this.hist.push(Math.min(1, rms * 9));
    var bars = this.bars, hist = this.hist, mid = (bars.length - 1) / 2;
    bars.forEach(function (b, i) {
      // newest level in the centre, older ones fanning out, so it reads as a live voice
      var k = Math.round(Math.abs(i - mid)), level = hist[hist.length - 1 - k] || 0;
      b.style.transform = 'scaleY(' + Math.max(0.12, level).toFixed(3) + ')';
    });
  };
  BW.Wave.prototype.reset = function () {
    this.hist = this.hist.map(function () { return 0; });
    this.bars.forEach(function (b) { b.style.transform = ''; });
  };
})();
