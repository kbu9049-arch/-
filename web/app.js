/* 성분 근거 찾기 — 프런트엔드
   서버 API 가 돌려준 값만 그리고, 클라이언트에서 수치를 새로 만들어 내지 않는다. */
'use strict';

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const esc = (v) => String(v ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const n = (v) => Number(v || 0).toLocaleString('ko-KR');

/* 이 앱은 두 가지 방식으로 배포된다.
     server   — FastAPI 가 /api/* 를 서빙 (실시간 조회·전체 논문 페이지네이션 가능)
     snapshot — 정적 호스팅. data/ 아래 색인과 상세 파일을 두고 브라우저가 API 를 흉내 낸다.
   화면 코드는 둘 다 완전히 동일하다. api() 아래에서만 갈린다. */
let SNAPSHOT = null;

// GitHub Pages 처럼 하위 경로(/저장소명/)에 올려도 동작하도록 현재 디렉터리 기준.
const BASE = location.pathname.replace(/[^/]*$/, '');
const resolve = (p) => BASE + String(p).replace(/^\//, '');

/* ── 모션 ─────────────────────────────────────────────────────────────────
   빠르게(140~620ms), 한 번만. 등장과 조작에만 쓰고 장식으로는 쓰지 않는다.
   prefers-reduced-motion 을 켠 사용자에게는 전부 즉시 완료 상태로 보인다. */
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* 등장 애니메이션은 기본으로 꺼져 있다(= 내용이 그냥 보인다).
   여기서 html.anim 을 붙여야 CSS 가 요소를 숨기기 시작한다. 스크립트가 죽거나
   관찰자를 못 쓰는 환경에서 내용이 영영 안 보이는 사고를 막기 위한 장치다. */
const CAN_ANIMATE = !REDUCED && 'IntersectionObserver' in window;
if (CAN_ANIMATE) document.documentElement.classList.add('anim');

/** 남아 있는 것을 전부 드러낸다. 관찰자가 놓쳤을 때의 안전망. */
function revealAll(root = document) {
  $$('.reveal:not(.in)', root).forEach((e) => e.classList.add('in'));
}

/** 스크롤에 들어오는 순서대로 차례차례 올라오게 한다. */
function reveal(root = document, stagger = 55) {
  const els = $$('.reveal:not(.in)', root);
  if (!CAN_ANIMATE) { revealAll(root); return; }
  let i = 0;
  const io = new IntersectionObserver((entries, obs) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      en.target.style.setProperty('--d', `${Math.min(i++, 7) * stagger}ms`);
      en.target.classList.add('in');
      obs.unobserve(en.target);
    }
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.04 });
  els.forEach((e) => io.observe(e));
  // 안전망: 3초 안에 화면에 들어오지 않은 것은 그냥 보여 준다.
  // 타이머는 하나만 두되 반드시 문서 전체를 훑는다. root 별로 걸면 나중 호출이
  // 앞선 호출의 타이머를 지워서 그쪽 요소가 숨은 채로 남는다.
  clearTimeout(reveal._t);
  reveal._t = setTimeout(() => revealAll(document), 3000);
}

/** 막대는 0에서 목표 너비까지 자란다. 길이 자체가 데이터라 눈이 따라가기 쉽다. */
function growBars(root = document) {
  const bars = $$('.bar.grow', root);
  if (!bars.length) return;
  const paint = () => bars.forEach((b, i) => {
    b.style.transitionDelay = REDUCED ? '0ms' : `${Math.min(i, 9) * 55}ms`;
    b.style.width = b.dataset.w || 'auto';
    b.classList.remove('grow');
    b.classList.add('grown');   // 다 자란 뒤 빛이 한 번 훑고 지나가게 한다
  });
  if (REDUCED) paint();
  else requestAnimationFrame(() => requestAnimationFrame(paint));
}

/** 표제 숫자만 세어 올린다. 등폭 숫자라 세는 동안에도 자리가 흔들리지 않는다. */
function countUp(el) {
  const target = Number(el.dataset.count || 0);
  if (REDUCED || target <= 0) { el.textContent = n(target); return; }
  const dur = 720;
  const t0 = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    el.textContent = n(Math.round(target * (1 - Math.pow(1 - p, 3))));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/** 선택된 탭 아래로 밑줄이 미끄러진다. */
function moveUnderline() {
  const u = $('.tab-underline');
  const on = $('.tab[aria-selected="true"]');
  if (!u || !on) return;
  u.style.width = `${on.offsetWidth}px`;
  u.style.transform = `translateX(${on.offsetLeft}px)`;
}
addEventListener('resize', moveUnderline);
addEventListener('beforeprint', () => revealAll());

/* 스크롤이 시작되면 상단 바에 경계선이 생긴다. 맨 위에서는 배경과 이어져 보인다. */
(function navOnScroll() {
  const nav = $('#nav');
  if (!nav) return;
  let ticking = false;
  const sync = () => {
    nav.classList.toggle('scrolled', window.scrollY > 8);
    ticking = false;
  };
  addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(sync); }
  }, { passive: true });
  sync();
})();

async function api(path) {
  if (SNAPSHOT) return snapshotRoute(path);
  const res = await fetch(resolve(path), { headers: { Accept: 'application/json' } });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && body.detail;
    const msg = (detail && (detail.message || detail)) || `요청 실패 (${res.status})`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status;
    err.code = detail && detail.error;
    throw err;
  }
  return body;
}

/* ── 정적 스냅샷 모드 ──────────────────────────────────────────────────────
   색인(index.json)만 먼저 받고, 성분·지표 상세는 열 때 그 파일 하나만 받아온다.
   전부를 한 파일에 담던 때는 성분당 상위 40건밖에 못 실어서, "뼈 건강 (233)"
   을 골라도 그 40건 안에 든 몇 건만 나왔다. 지금은 논문을 전부 싣는다. */
const SNAP_CACHE = new Map();

async function snapDetail(kind, id) {
  const key = `${kind}/${id}`;
  if (SNAP_CACHE.has(key)) return SNAP_CACHE.get(key);
  const res = await fetch(resolve(`data/${key}.json`));
  if (!res.ok) throw new Error(`자료를 찾지 못했습니다 (${esc(id)})`);
  const data = await res.json();
  SNAP_CACHE.set(key, data);
  return data;
}

const snorm = (v) => String(v ?? '').normalize('NFKC').trim().toLowerCase();

/** server/queries.py 의 Reference._find 와 같은 점수 규칙. */
function findIn(index, q, limit) {
  q = snorm(q);
  if (!q) return [];
  const qc = q.replace(/ /g, '');
  const scores = new Map();
  for (const [label, key, weight] of index) {
    let score;
    if (label === q) score = 100 * weight;
    else if (label.startsWith(q)) score = 60 * weight;
    else if (label.includes(q)) score = 30 * weight;
    else if (q.length >= 3 && label.replace(/ /g, '').includes(qc)) score = 20 * weight;
    else continue;
    if (!scores.has(key) || scores.get(key) < score) scores.set(key, score);
  }
  return [...scores.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit);
}

async function snapshotRoute(path) {
  const [rawPath, rawQuery] = path.split('?');
  const p = new URLSearchParams(rawQuery || '');
  const S = SNAPSHOT;
  const seg = rawPath.replace(/^\/api\//, '').split('/').map(decodeURIComponent);

  if (seg[0] === 'meta') {
    return {
      corpus_ready: (S.corpus.papers || 0) > 0,
      corpus: S.corpus,
      ...S.meta,          // categories / study_types / subjects / directions / plain …
      live_lookup: false,
      snapshot: true,
      generated_at: S.generated_at,
    };
  }

  if (seg[0] === 'outcomes') {
    if (seg.length === 1) return { items: S.outcomes };
    return snapDetail('o', seg[1]);
  }

  if (seg[0] === 'ingredients') {
    if (seg.length === 1) return snapshotIngredientList(p);
    const d = await snapDetail('i', seg[1]);
    if (seg[2] === 'papers') return snapshotPapers(d, p);
    return d;
  }

  if (seg[0] === 'search') return snapshotSearch(p.get('q') || '');

  if (seg[0] === 'live') {
    return {
      available: false,
      term: p.get('term') || '',
      reason: '지금 방식으로는 바로 찾아보기를 쓸 수 없습니다. '
            + '서버를 띄워서 실행하면 이 기능이 켜집니다.',
    };
  }
  throw new Error(`정적 배포에서 지원하지 않는 경로: ${rawPath}`);
}

function snapshotIngredientList(p) {
  const q = p.get('q') || '';
  const cat = p.get('category') || '';
  const limit = Number(p.get('limit') || 60);
  const offset = Number(p.get('offset') || 0);

  let items = SNAPSHOT.ingredients;
  let order = null;
  if (q) {
    const ranked = findIn(SNAPSHOT.search_index.ingredients, q, 400);
    order = new Map(ranked.map(([id], i) => [id, i]));
    items = ranked.map(([id]) => items.find((it) => it.id === id)).filter(Boolean);
  }
  if (cat) items = items.filter((it) => it.category === cat);

  items = items.slice();
  if (order) {
    items.sort((a, b) => (order.get(a.id) - order.get(b.id)) || (b.stats.total - a.stats.total));
  } else {
    // 동점은 id(ASCII)로. 서버(queries.ingredient_list)와 같은 순서를 내야 한다.
    items.sort((a, b) => (b.stats.human - a.stats.human)
      || (b.stats.total - a.stats.total) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  }
  return { total: items.length, items: items.slice(offset, offset + limit) };
}

function snapshotPapers(detail, p) {
  const outcome = p.get('outcome') || '';
  const subject = p.get('subject') || '';
  const study = p.get('study_type') || '';
  const direction = p.get('direction') || '';
  const page = Number(p.get('page') || 1);
  const pageSize = Number(p.get('page_size') || 20);

  let items = (detail.papers || []).filter((x) => {
    if (outcome && !(x.outcome_ids || []).includes(outcome)) return false;
    if (subject && x.subject !== subject) return false;
    if (study && x.study_type !== study) return false;
    // 지표를 지정하면 그 지표의 방향으로 걸러야 하지만, 스냅샷에는 대표 지표의
    // 방향만 담겨 있다. 그래서 대표 지표와 일치할 때만 방향 필터를 적용한다.
    if (direction && x.direction !== direction) return false;
    return true;
  });
  const total = items.length;
  const start = Math.max(0, (page - 1) * pageSize);
  return {
    total, page, page_size: pageSize,
    items: items.slice(start, start + pageSize),
    truncated: !!detail.papers_truncated,
  };
}

function snapshotSearch(q) {
  const S = SNAPSHOT;
  const res = { query: q, ingredients: [], outcomes: [], fulltext: [], mode: 'empty' };
  if (!q.trim()) return res;

  for (const [id, score] of findIn(S.search_index.ingredients, q, 10)) {
    const it = S.ingredients.find((x) => x.id === id);
    if (it) res.ingredients.push({ ...it, score });
  }
  for (const [id, score] of findIn(S.search_index.outcomes, q, 5)) {
    const o = S.outcomes.find((x) => x.id === id);
    if (o) res.outcomes.push({ ...o, score });
  }
  if (res.ingredients.length
      && (!res.outcomes.length || res.ingredients[0].score >= res.outcomes[0].score)) {
    res.mode = 'ingredient';
  } else if (res.outcomes.length) {
    res.mode = 'outcome';
  } else {
    res.mode = 'fulltext';
  }
  return res;
}

const state = {
  meta: null,
  category: '',
  query: '',
  offset: 0,
  pageSize: 40,
  items: [],
  total: 0,
  outcomes: [],
  papers: { outcome: '', subject: '', study_type: '', direction: '', page: 1 },
};

/* ── 밝기 전환 ───────────────────────────────────────────────────────────── */
(function theme() {
  const saved = (() => { try { return localStorage.getItem('theme'); } catch { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  $('#theme-toggle').addEventListener('click', () => {
    const root = document.documentElement;
    const now = root.dataset.theme
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = now === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch { /* 저장 불가해도 동작에는 지장 없음 */ }
  });
})();

/* ── 공통 조각 ───────────────────────────────────────────────────────────── */
function directionBar(o, maxHuman) {
  const total = o.human_significant + o.human_null + o.human_unclear;
  const width = maxHuman > 0 ? Math.max(3, Math.round((o.human / maxHuman) * 100)) : 3;
  const seg = (cls, v, label) => (v > 0
    ? `<i class="seg ${cls}" style="flex:${v}" title="${esc(label)} ${n(v)}건"></i>` : '');
  const few = o.human > 0 && o.human < 3 ? ' few' : '';
  return `
    <div class="orow${few}" data-fam="${esc(o.family || '')}">
      <div class="oname">
        <button class="obtn" data-outcome="${esc(o.outcome_id || o.id)}"
                title="이 항목의 논문만 보기">${esc(o.label_ko)}</button>
        ${o.human > 0 && o.human < 3 ? '<span class="few-tag">연구 적음</span>' : ''}
      </div>
      <div class="bar grow" data-w="${width}%">
        ${total ? seg('sig', o.human_significant, '차이 있었음')
                + seg('null', o.human_null, '차이 없었음')
                + seg('unclear', o.human_unclear, '알 수 없음')
                : '<i class="seg unclear" style="flex:1"></i>'}
      </div>
      <div class="onum">사람 ${n(o.human)} · 전체 ${n(o.total)}</div>
    </div>`;
}

const LEGEND = `
  <div class="legend">
    <span><i class="sw sig"></i>차이 있었음</span>
    <span><i class="sw null"></i>차이 없었음</span>
    <span><i class="sw unclear"></i>알 수 없음</span>
  </div>`;

function paperItem(p, { showEvidence = true } = {}) {
  const link = p.url
    ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>`
    : esc(p.title);
  const src = [p.journal, p.pmid ? `PMID ${p.pmid}` : '',
               p.cited_by ? `인용 ${n(p.cited_by)}회` : '']
    .filter(Boolean).map(esc).join(' · ');
  return `
    <div class="paper reveal" data-dir="${esc(p.direction || '')}">
      <div class="pmeta">
        <span>${esc(p.study_type_ko)}</span>
        ${p.year ? `<span>${esc(p.year)}년</span>` : ''}
        <span>${esc(p.subject_ko)}</span>
        ${p.direction ? `<span class="dirtag ${esc(p.direction)}">${esc(p.direction_ko)}</span>` : ''}
        ${p.retracted ? '<span class="retracted">취소된 논문</span>' : ''}
      </div>
      <div class="ptitle">${link}</div>
      ${src ? `<div class="psrc">${src}</div>` : ''}
      ${showEvidence && p.evidence
        ? `<div class="evidence"><span class="kicker">이렇게 나눈 이유 — 논문에 적힌 문장 (영어 원문)</span>${esc(p.evidence)}</div>`
        : ''}
    </div>`;
}

/* ── 상단 배너·통계 ──────────────────────────────────────────────────────── */
function renderAlerts() {
  const c = state.meta.corpus || {};
  const box = $('#alerts');
  const out = [];

  if (!state.meta.corpus_ready || !c.papers) {
    out.push(`<div class="banner warn"><span class="bt">⚠ 아직 논문을 모으지 않았습니다</span>
      보여드릴 자료가 없습니다. 저장소에서
      <code>python -m ingest.build all --target 100000</code> 을 실행해 논문을
      모으면 이 화면이 실제 자료로 채워집니다.
      <b>모으기 전에는 어떤 숫자도 지어내지 않습니다.</b></div>`);
  }
  if (c.fixture_papers > 0) {
    out.push(`<div class="banner alert"><span class="bt">⚠ 시험용 가짜 자료가 섞여 있습니다 —
      건강 정보로 읽지 마세요</span>
      지금 여기에 진짜 논문이 아닌 시험용 자료가 <b>${n(c.fixture_papers)}건</b>
      들어 있습니다(전체 ${n(c.papers)}건 중). 프로그램 점검용이라 실제 근거와
      아무 상관이 없습니다. <code>data/evidence.db</code> 를 지우고 다시 모으세요.</div>`);
  }
  box.innerHTML = out.join('');
}

function renderCorpusStats() {
  const c = state.meta.corpus || {};
  // 여섯 개를 늘어놓으면 어느 것도 눈에 안 들어온다. 네 개로 줄인다.
  const tiles = [
    [n(c.papers), '모은 논문', 'metabolic'],
    [n(c.human_papers), '사람에게 한 연구', 'mind'],
    [n(c.systematic_papers), '여러 연구 종합', 'breath'],
    [`${n(c.ingredients_with_papers)} / ${n(state.meta.ingredient_count)}`, '논문이 있는 성분', 'hormone'],
  ];
  $('#corpus-stats').innerHTML = tiles
    .map(([v, k, fam]) => `<div class="stat" data-fam="${fam}"><div class="v num">${v}</div>
        <div class="k">${esc(k)}</div></div>`)
    .join('');

  const built = c.last_aggregate ? new Date(c.last_aggregate).toLocaleString('ko-KR') : '아직 없음';
  const range = (c.year_min && c.year_max) ? ` · 논문 ${c.year_min}–${c.year_max}년` : '';
  $('#footer-build').innerHTML = `자료 정리 ${esc(built)}${esc(range)} · `;

  $('#about-corpus').innerHTML = `
    <h3>지금 모아 둔 자료</h3>
    <div class="scroll-x"><table class="plain">
      <tr><th>모은 논문</th><td class="num">${n(c.papers)}</td></tr>
      <tr><th>요약글이 있는 논문</th><td class="num">${n(c.papers)}</td></tr>
      <tr><th>사람에게 한 연구</th><td class="num">${n(c.human_papers)}</td></tr>
      <tr><th>여러 연구 종합</th><td class="num">${n(c.systematic_papers)}</td></tr>
      <tr><th>무작위 배정 시험</th><td class="num">${n(c.rct_papers)}</td></tr>
      <tr><th>취소된 논문 (숫자에서 뺌)</th><td class="num">${n(c.retracted_papers)}</td></tr>
      <tr><th>어디서 받았나</th><td>${esc(c.harvest_source || '—')}</td></tr>
      <tr><th>마지막으로 받은 날</th><td>${esc(c.last_harvest || '—')}</td></tr>
      <tr><th>마지막 정리</th><td>${esc(c.last_aggregate || '—')}</td></tr>
    </table></div>`;
}

/* ── 탭 ──────────────────────────────────────────────────────────────────── */
const PANELS = { ingredient: 'panel-ingredient', outcome: 'panel-outcome', about: 'panel-about' };
function showTab(name) {
  Object.entries(PANELS).forEach(([key, id]) => {
    const active = key === name;
    $('#' + id).hidden = !active;
    $('#tab-' + key).setAttribute('aria-selected', String(active));
  });
  moveUnderline();
}
Object.keys(PANELS).forEach((key) => {
  $('#tab-' + key).addEventListener('click', () => {
    location.hash = key === 'ingredient' ? '#/' : `#/${key}`;
  });
});

/* ── 성분 목록 ───────────────────────────────────────────────────────────── */
function renderCategoryChips() {
  const cats = state.meta.categories || {};
  const chips = [`<b>분류</b><button class="chip" data-cat="" aria-pressed="${!state.category}">전체</button>`];
  for (const [id, label] of Object.entries(cats)) {
    chips.push(`<button class="chip" data-cat="${esc(id)}"
      aria-pressed="${state.category === id}">${esc(label)}</button>`);
  }
  $('#cat-chips').innerHTML = chips.join('');
}

function ingredientCard(it) {
  const s = it.stats;
  const badge = s.total > 0
    ? `<span class="badge">논문 ${n(s.total)}건 · 사람 ${n(s.human)}건</span>`
    : '<span class="badge none">논문 없음</span>';
  const detail = s.total > 0
    ? `여러 연구 종합 <b>${n(s.systematic)}</b> · 무작위 배정 시험 <b>${n(s.rct)}</b>
       · 동물·세포 <b>${n(s.preclinical)}</b>${s.year_min ? ` · ${s.year_min}–${s.year_max}년` : ''}`
    : '아직 모은 논문이 없습니다. <b>효과가 없다는 뜻이 아닙니다.</b>';
  return `
    <button class="card reveal" data-ing="${esc(it.id)}" data-cat="${esc(it.category || '')}">
      <div class="chead">
        <span class="nm">${esc(it.name_ko)}</span>
        <span class="en">${esc(it.name_en)}</span>
        ${badge}
      </div>
      <div class="meta"><span class="ctag">${esc(it.category_ko)}</span>${detail}</div>
    </button>`;
}

async function loadIngredients({ append = false } = {}) {
  if (!append) { state.offset = 0; $('#ing-list').innerHTML = '<p class="loading">불러오는 중…</p>'; }
  const params = new URLSearchParams({
    limit: state.pageSize, offset: state.offset, category: state.category, q: state.query,
  });
  try {
    const data = await api('/api/ingredients?' + params);
    state.total = data.total;
    state.items = append ? state.items.concat(data.items) : data.items;
    const html = state.items.map(ingredientCard).join('');
    $('#ing-list').innerHTML = html || `
      <div class="empty"><b>“${esc(state.query)}”에 맞는 성분이 목록에 없습니다.</b><br>
        영어 이름(예: <i>lutein</i>)으로도 찾아보세요. 아래에서 바로 검색할 수도 있습니다.
        <div class="btnrow"><button class="btn primary" id="live-btn">논문 데이터베이스에서 바로 찾아보기</button></div>
        <div id="live-result"></div>
      </div>`;
    $('#ing-count').innerHTML = state.query
      ? `“<b>${esc(state.query)}</b>” 검색 결과 <b>${n(state.total)}</b>종`
      : `<b>${n(state.total)}</b>종의 성분`;
    $('#ing-more').hidden = state.items.length >= state.total;
    reveal($('#ing-list'), 28);
  } catch (e) {
    $('#ing-list').innerHTML = `<div class="empty"><b>${esc(e.message)}</b></div>`;
    $('#ing-count').textContent = '';
  }
}

/* ── 실시간 조회 (색인에 없는 검색어) ────────────────────────────────────── */
async function liveLookup(term, mount) {
  mount.innerHTML = '<p class="loading">논문 데이터베이스에서 찾는 중…</p>';
  try {
    const d = await api('/api/live?term=' + encodeURIComponent(term));
    if (!d.available) { mount.innerHTML = `<div class="note">${esc(d.reason)}</div>`; return; }
    const dc = d.direction_counts || {};
    mount.innerHTML = `
      <div class="note"><b>바로 찾아본 결과</b> — ${esc(d.note)}</div>
      <div class="stats">
        <div class="stat"><div class="v num">${n(d.hit_count)}</div><div class="k">데이터베이스 전체</div></div>
        <div class="stat"><div class="v num">${n(d.fetched)}</div><div class="k">살펴본 논문</div></div>
        <div class="stat"><div class="v num">${n(d.human)}</div><div class="k">사람에게 한 연구</div></div>
        <div class="stat"><div class="v num">${n(dc.significant)} / ${n(dc.null)} / ${n(dc.unclear)}</div>
          <div class="k">차이 있음 / 없음 / 모름</div></div>
      </div>
      ${d.outcomes.length ? `<h3>많이 재 본 항목</h3>${d.outcomes.map((o) =>
        `<div class="orow"><div class="oname">${esc(o.label_ko)}</div>
         <div class="bar"><i class="seg sig" style="flex:${o.human}"></i>
         <i class="seg unclear" style="flex:${Math.max(0, o.total - o.human)}"></i></div>
         <div class="onum num">사람 ${n(o.human)} · 전체 ${n(o.total)}</div></div>`).join('')}` : ''}
      <h3>논문</h3>${d.papers.map((p) => paperItem(p)).join('') || '<p class="dim">없습니다.</p>'}`;
  } catch (e) {
    mount.innerHTML = `<div class="empty"><b>찾지 못했습니다:</b> ${esc(e.message)}</div>`;
  }
}

/* ── 성분 상세 ───────────────────────────────────────────────────────────── */
function yearChart(byYear) {
  if (!byYear || byYear.length < 2) return '';
  const max = Math.max(...byYear.map((y) => y.count));
  const bars = byYear.map((y) =>
    `<i style="height:${Math.max(3, (y.count / max) * 100)}%" title="${y.year}년 ${y.count}건"></i>`).join('');
  return `<h2>해마다 나온 논문 수</h2>
    <div class="bars reveal" style="padding:26px 28px">
      <div class="years">${bars}</div>
      <div class="yearlbl"><span>${byYear[0].year}</span><span>${byYear[byYear.length - 1].year}</span></div>
    </div>`;
}

async function renderIngredient(id) {
  const box = $('#ingredient-detail');
  $('#ingredient-search').hidden = true;
  box.hidden = false;
  box.innerHTML = '<p class="loading">불러오는 중…</p>';
  let d;
  try {
    d = await api('/api/ingredients/' + encodeURIComponent(id));
  } catch (e) {
    box.innerHTML = `<button class="back" data-back>← 목록으로</button>
      <div class="empty"><b>${esc(e.message)}</b></div>`;
    return;
  }

  const s = d.stats;
  const maxHuman = Math.max(1, ...d.outcomes.map((o) => o.human));
  const hasData = s.total > 0;

  const sum = d.summary || {};
  const lede = sum.lede || (sum.lines || [])[0] || '';
  const small = (sum.small || []).join(' · ');

  // 영문명과 겹치는 검색어는 빼고 보여 준다 ("Vitamin A · vitamin a, …"는 중복).
  const extra = d.synonyms.filter((x) => x.toLowerCase() !== d.name_en.toLowerCase());

  box.dataset.cat = d.category || '';
  box.innerHTML = `
    <button class="back" data-back><span class="arw">←</span> 성분</button>

    <div class="detail-head reveal">
      <div class="kicker">${esc(d.category_ko)}</div>
      <h1 class="detail-title">${esc(d.name_ko)}</h1>
      <div class="detail-sub">${esc(d.name_en)}${extra.length ? ` · ${extra.map(esc).join(', ')}` : ''}</div>
    </div>

    ${hasData ? `
      <div class="pull reveal">
        <span class="v num" data-count="${s.human}">0</span>
        <span class="k">사람에게 한 연구 · 전체 ${n(s.total)}건 중</span>
      </div>
      <p class="lede reveal">${esc(lede)}</p>
      ${small ? `<div class="smallprint reveal">${esc(small)}</div>` : ''}

      <h2>어떤 걸 재 봤나</h2>
      ${LEGEND}
      ${d.outcomes.length
        ? `<div class="bars reveal">${d.outcomes.map((o) => directionBar(o, maxHuman)).join('')}</div>`
        : '<p class="dim" style="text-align:center">사람에게 한 연구에서 잡힌 항목이 없습니다.</p>'}

      <h2>대표 논문</h2>
      <p class="count">믿을 만한 연구부터 보여줍니다 —
        여러 연구 종합 → 논문 모아 정리 → 무작위 배정 시험 순.</p>
      ${d.top_papers.map((p) => paperItem(p, { showEvidence: false })).join('')}

      ${yearChart(d.by_year)}

      <h2>논문 전부 보기</h2>
      <div class="filters">
        <select id="f-outcome" aria-label="측정 항목으로 거르기">
          <option value="">측정 항목 전체</option>
          ${d.outcomes.map((o) => `<option value="${esc(o.outcome_id)}">${esc(o.label_ko)} (${n(o.total)})</option>`).join('')}
        </select>
        <select id="f-subject" aria-label="연구 대상으로 거르기">
          <option value="">사람·동물 모두</option>
          <option value="human">사람에게 한 연구만</option>
          <option value="animal">동물 실험만</option>
          <option value="invitro">세포·시험관 실험만</option>
        </select>
        <select id="f-study" aria-label="연구 방식으로 거르기">
          <option value="">연구 방식 전체</option>
          ${d.by_study_type.map((t) =>
            `<option value="${esc(t.study_type)}">${esc(t.label_ko)} (${n(t.count)})</option>`).join('')}
        </select>
        <select id="f-direction" aria-label="결과로 거르기">
          <option value="">결과 전체</option>
          <option value="significant">차이 있었음</option>
          <option value="null">차이 없었음</option>
          <option value="unclear">알 수 없음</option>
        </select>
      </div>
      <div id="paper-list"></div>
      <div class="btnrow">
        <button class="btn" id="p-prev">← 이전</button>
        <span id="p-info" class="dim"></span>
        <button class="btn" id="p-next">다음 →</button>
      </div>`
    : `
      <div class="empty" style="margin-top:26px">
        <b>${esc(d.name_ko)} 관련 논문을 아직 못 모았습니다.</b><br>
        아직 아무도 연구하지 않았거나, 여기 못 모았을 수 있습니다.
        <b>“효과가 없다”는 뜻이 아닙니다.</b>
        <div class="btnrow">
          <button class="btn primary" id="live-btn2">논문 데이터베이스에서 바로 찾아보기</button>
        </div>
        <div id="live-result2"></div>
      </div>`}`;

  window.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' });
  reveal(box);
  growBars(box);
  const pull = $('.pull .v', box);
  if (pull) countUp(pull);

  if (!hasData) {
    $('#live-btn2')?.addEventListener('click', () =>
      liveLookup(d.synonyms[0] || d.name_en, $('#live-result2')));
    return;
  }

  state.papers = { outcome: '', subject: '', study_type: '', direction: '', page: 1 };
  const reload = () => loadPapers(id);
  ['#f-outcome', '#f-subject', '#f-study', '#f-direction'].forEach((sel, i) => {
    $(sel).addEventListener('change', (e) => {
      state.papers[['outcome', 'subject', 'study_type', 'direction'][i]] = e.target.value;
      state.papers.page = 1;
      reload();
    });
  });
  $('#p-prev').addEventListener('click', () => {
    if (state.papers.page > 1) { state.papers.page--; reload(); }
  });
  $('#p-next').addEventListener('click', () => { state.papers.page++; reload(); });
  $$('.obtn', box).forEach((b) => b.addEventListener('click', () => {
    $('#f-outcome').value = b.dataset.outcome;
    state.papers.outcome = b.dataset.outcome;
    state.papers.page = 1;
    reload();
    $('#paper-list').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  reload();
}

async function loadPapers(id) {
  const mount = $('#paper-list');
  if (!mount) return;
  mount.innerHTML = '<p class="loading">불러오는 중…</p>';
  const p = state.papers;
  const params = new URLSearchParams({
    outcome: p.outcome, subject: p.subject, study_type: p.study_type,
    direction: p.direction, page: p.page,
  });
  try {
    const d = await api(`/api/ingredients/${encodeURIComponent(id)}/papers?` + params);
    const trunc = d.truncated
      ? ' <span class="dim">— 논문이 너무 많아 믿을 만한 것부터 일부만 담았습니다.</span>'
      : '';
    mount.innerHTML = d.items.length
      ? `<p class="count">조건에 맞는 논문 <b>${n(d.total)}</b>건${trunc}</p>`
        + d.items.map((x) => paperItem(x)).join('')
      : '<div class="empty">이 조건에 맞는 논문이 없습니다.</div>';
    reveal(mount, 26);
    const pages = Math.max(1, Math.ceil(d.total / d.page_size));
    $('#p-info').textContent = `${d.page} / ${pages} 쪽`;
    $('#p-prev').disabled = d.page <= 1;
    $('#p-next').disabled = d.page >= pages;
  } catch (e) {
    mount.innerHTML = `<div class="empty"><b>${esc(e.message)}</b></div>`;
  }
}

/* ── 효능(결과지표) 목록 ─────────────────────────────────────────────────── */
function renderOutcomeGrid(filter = '') {
  const q = filter.trim().toLowerCase();
  const items = state.outcomes.filter((o) => !q
    || o.label_ko.toLowerCase().includes(q)
    || o.label_en.toLowerCase().includes(q)
    || (o.aliases || []).some((a) => a.toLowerCase().includes(q)));
  $('#o-grid').innerHTML = items.length ? items.map((o) => `
    <button class="ocard reveal" data-outcome="${esc(o.id)}" data-fam="${esc(o.family || '')}">
      ${o.family_ko ? `<span class="ofam">${esc(o.family_ko)}</span>` : ''}
      <span class="ol">${esc(o.label_ko)}</span>
      <span class="oc num">성분 ${n(o.ingredients)}종 · 사람 대상 연구 ${n(o.human)}건</span>
    </button>`).join('')
    : `<div class="empty">“${esc(filter)}”에 해당하는 항목이 없습니다.</div>`;
  reveal($('#o-grid'), 22);
}

async function renderOutcome(id) {
  const box = $('#outcome-detail');
  $('#outcome-browse').hidden = true;
  box.hidden = false;
  box.innerHTML = '<p class="loading">불러오는 중…</p>';
  let d;
  try {
    d = await api('/api/outcomes/' + encodeURIComponent(id) + '?min_human=1&limit=80');
  } catch (e) {
    box.innerHTML = `<button class="back" data-back>← 목록으로</button>
      <div class="empty"><b>${esc(e.message)}</b></div>`;
    return;
  }
  const maxHuman = Math.max(1, ...d.ingredients.map((i) => i.human));

  box.dataset.fam = d.family || '';
  box.innerHTML = `
    <button class="back" data-back><span class="arw">←</span> 효능</button>
    <div class="detail-head reveal">
      <div class="kicker">${esc(d.family_ko || '이런 걸 재 봤어요')}</div>
      <h1 class="detail-title">${esc(d.label_ko)}</h1>
      <div class="detail-sub">${esc(d.label_en)}</div>
    </div>
    <p class="lede reveal">이걸 실제로 재 본 사람 연구가 있는 성분입니다.</p>
    <div class="smallprint reveal" style="margin-bottom:34px">${esc(d.note)}</div>
    ${LEGEND}
    ${d.ingredients.length ? `<div class="bars reveal">` + d.ingredients.map((i) => `
      <div class="orow" data-cat="${esc(i.category || '')}">
        <div class="oname"><button class="obtn" data-ing="${esc(i.id)}">${esc(i.name_ko)}</button>
          <span class="ctag sm">${esc(i.category_ko)}</span></div>
        <div class="bar grow" data-w="${Math.max(3, Math.round((i.human / maxHuman) * 100))}%">
          <i class="seg sig" style="flex:${i.human_significant}" title="차이 있었음 ${n(i.human_significant)}건"></i>
          <i class="seg null" style="flex:${i.human_null}" title="차이 없었음 ${n(i.human_null)}건"></i>
          <i class="seg unclear" style="flex:${i.human_unclear}" title="알 수 없음 ${n(i.human_unclear)}건"></i>
        </div>
        <div class="onum">사람 ${n(i.human)} · 전체 ${n(i.total)}</div>
      </div>`).join('') + `</div>`
      : '<div class="empty">이걸 재 본 사람 연구를 아직 못 모았습니다.</div>'}

    <h2>대표 논문</h2>
    ${d.top_papers.map((p) => paperItem(p)).join('') || '<p class="dim">없습니다.</p>'}`;
  window.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' });
  reveal(box);
  growBars(box);
}

/* ── 라우팅 ──────────────────────────────────────────────────────────────── */
function route() {
  const hash = location.hash || '#/';
  const mIng = hash.match(/^#\/i\/(.+)$/);
  const mOut = hash.match(/^#\/o\/(.+)$/);

  if (mIng) {
    showTab('ingredient');
    renderIngredient(decodeURIComponent(mIng[1]));
    return;
  }
  if (mOut) {
    showTab('outcome');
    renderOutcome(decodeURIComponent(mOut[1]));
    return;
  }
  if (hash === '#/about') { showTab('about'); return; }
  if (hash === '#/outcome') {
    showTab('outcome');
    $('#outcome-detail').hidden = true;
    $('#outcome-browse').hidden = false;
    return;
  }
  showTab('ingredient');
  $('#ingredient-detail').hidden = true;
  $('#ingredient-search').hidden = false;
}
addEventListener('hashchange', route);

/* ── 이벤트 위임 ─────────────────────────────────────────────────────────── */
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-home]')) { location.hash = '#/'; return; }

  const back = e.target.closest('[data-back]');
  if (back) { history.length > 1 ? history.back() : (location.hash = '#/'); return; }

  const ing = e.target.closest('[data-ing]');
  if (ing) { location.hash = '#/i/' + encodeURIComponent(ing.dataset.ing); return; }

  const oc = e.target.closest('.ocard[data-outcome]');
  if (oc) { location.hash = '#/o/' + encodeURIComponent(oc.dataset.outcome); return; }

  const cat = e.target.closest('[data-cat]');
  if (cat) {
    state.category = cat.dataset.cat;
    renderCategoryChips();
    loadIngredients();
    return;
  }

  if (e.target.id === 'live-btn') {
    liveLookup(state.query, $('#live-result'));
  }
});

/* ── 검색 입력 ───────────────────────────────────────────────────────────── */
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

$('#q').addEventListener('input', debounce((e) => {
  state.query = e.target.value.trim();
  $('#q-clear').hidden = !state.query;
  loadIngredients();
}, 220));
$('#q-clear').addEventListener('click', () => {
  $('#q').value = ''; state.query = ''; $('#q-clear').hidden = true; loadIngredients(); $('#q').focus();
});
$('#ing-more').addEventListener('click', () => {
  state.offset += state.pageSize;
  loadIngredients({ append: true });
});
$('#oq').addEventListener('input', debounce((e) => {
  $('#oq-clear').hidden = !e.target.value;
  renderOutcomeGrid(e.target.value);
}, 150));
$('#oq-clear').addEventListener('click', () => {
  $('#oq').value = ''; $('#oq-clear').hidden = true; renderOutcomeGrid('');
});

/* ── 시작 ────────────────────────────────────────────────────────────────── */
/** 서버 API 를 먼저 찾고, 없으면 정적 스냅샷으로 떨어진다. 설정할 것이 없다. */
async function bootstrap() {
  try {
    const res = await fetch(resolve('/api/meta'), { headers: { Accept: 'application/json' } });
    if (res.ok && (res.headers.get('content-type') || '').includes('json')) {
      return await res.json();          // 서버 배포
    }
  } catch { /* 정적 호스팅에서는 /api/meta 가 없다. 아래로 넘어간다. */ }

  const res = await fetch(resolve('data/index.json'));
  if (!res.ok) {
    throw new Error('서버 API 도 data/index.json 도 찾지 못했습니다. '
                  + '`make serve` 로 서버를 띄우거나 `make site` 로 정적 사이트를 만드세요.');
  }
  SNAPSHOT = await res.json();          // 정적 배포
  return snapshotRoute('/api/meta');
}

(async function init() {
  try {
    state.meta = await bootstrap();
  } catch (e) {
    $('#alerts').innerHTML = `<div class="banner alert"><span class="bt">데이터를 불러오지 못했습니다</span>
      ${esc(e.message)}</div>`;
    return;
  }
  renderAlerts();
  renderCorpusStats();
  renderCategoryChips();

  try {
    state.outcomes = (await api('/api/outcomes')).items;
    renderOutcomeGrid('');
  } catch { /* 지표 목록 실패는 성분 검색을 막지 않는다 */ }

  if (state.meta.corpus_ready && state.meta.corpus.papers) {
    await loadIngredients();
  } else {
    $('#ing-count').textContent = '';
    $('#ing-list').innerHTML = `<div class="empty">
      <b>아직 모은 논문이 없습니다.</b><br>
      <code>python -m ingest.build all --target 100000</code> 을 실행해
      논문을 모으면 이 화면이 실제 자료로 채워집니다.</div>`;
  }
  route();
  moveUnderline();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveUnderline);
})();
