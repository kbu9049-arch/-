/* 성분 근거 찾기 — 프런트엔드
   서버 API 가 돌려준 값만 그리고, 클라이언트에서 수치를 새로 만들어 내지 않는다. */
'use strict';

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const esc = (v) => String(v ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const n = (v) => Number(v || 0).toLocaleString('ko-KR');

async function api(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
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
  const seg = (cls, v) => (v > 0
    ? `<i class="seg ${cls}" style="flex:${v}" title="${esc(cls)} ${v}건"></i>` : '');
  const few = o.human > 0 && o.human < 3 ? ' few' : '';
  return `
    <div class="orow${few}">
      <div class="oname">
        <button class="obtn" data-outcome="${esc(o.outcome_id || o.id)}"
                title="이 항목의 논문만 보기">${esc(o.label_ko)}</button>
        ${o.human > 0 && o.human < 3 ? '<span class="few-tag">연구 적음</span>' : ''}
      </div>
      <div class="bar" style="width:${width}%">
        ${total ? seg('sig', o.human_significant) + seg('null', o.human_null)
                + seg('unclear', o.human_unclear)
                : '<i class="seg unclear" style="flex:1"></i>'}
      </div>
      <div class="onum num">사람 ${n(o.human)} · 전체 ${n(o.total)}</div>
    </div>`;
}

const LEGEND = `
  <div class="legend">
    <span><i class="sw" style="background:var(--sig)"></i>유의한 결과 보고</span>
    <span><i class="sw" style="background:var(--null)"></i>유의차 없음</span>
    <span><i class="sw" style="background:var(--unclear)"></i>판정 불가</span>
    <span class="dim">막대 길이 = 사람 대상 연구 건수 (효과 크기가 아님)</span>
  </div>`;

function paperItem(p, { showEvidence = true } = {}) {
  const dirCls = p.direction || 'unclear';
  const link = p.url
    ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>`
    : esc(p.title);
  const bits = [p.journal, p.year].filter(Boolean).map(esc).join(' · ');
  return `
    <div class="paper">
      <div class="ptitle">${link}</div>
      <div class="pmeta">
        <span class="tag">${esc(p.study_type_ko)}</span>
        <span class="tag">${esc(p.subject_ko)}</span>
        ${p.direction ? `<span class="tag ${dirCls}">${esc(p.direction_ko)}</span>` : ''}
        ${p.retracted ? '<span class="tag retracted">철회된 논문</span>' : ''}
        ${bits}${p.pmid ? ` · PMID ${esc(p.pmid)}` : ''}
        ${p.cited_by ? ` · 피인용 ${n(p.cited_by)}` : ''}
      </div>
      ${showEvidence && p.evidence
        ? `<div class="evidence"><b>분류 근거(초록 원문):</b> ${esc(p.evidence)}</div>` : ''}
    </div>`;
}

/* ── 상단 배너·통계 ──────────────────────────────────────────────────────── */
function renderAlerts() {
  const c = state.meta.corpus || {};
  const box = $('#alerts');
  const out = [];

  if (!state.meta.corpus_ready || !c.papers) {
    out.push(`<div class="banner warn"><span class="bt">⚠ 아직 논문을 수집하지 않았습니다</span>
      화면에 표시할 데이터가 없습니다. 저장소에서
      <code>python -m ingest.build all --target 100000</code> 을 실행해 문헌 DB 에서 논문을
      수집한 뒤 서버를 다시 시작하세요. <b>수집 전에는 어떤 수치도 지어내지 않습니다.</b></div>`);
  }
  if (c.fixture_papers > 0) {
    out.push(`<div class="banner alert"><span class="bt">⚠ 테스트 픽스처가 섞여 있습니다 —
      건강 정보로 읽지 마세요</span>
      현재 색인에 실제 논문이 아닌 합성 테스트 레코드가 <b>${n(c.fixture_papers)}건</b>
      들어 있습니다(전체 ${n(c.papers)}건 중). 파이프라인 점검용 데이터이며 실제 근거와
      아무 관련이 없습니다. <code>data/evidence.db</code> 를 지우고 실제 수집을 다시 하세요.</div>`);
  }
  box.innerHTML = out.join('');
}

function renderCorpusStats() {
  const c = state.meta.corpus || {};
  const tiles = [
    [n(c.papers), '수집한 논문'],
    [n(c.human_papers), '사람 대상 연구'],
    [n(c.systematic_papers), '메타분석·체계적 고찰'],
    [n(c.rct_papers), '무작위대조시험(RCT)'],
    [n(c.ingredients_with_papers) + ' / ' + n(state.meta.ingredient_count), '논문이 있는 성분'],
    [n(state.meta.outcome_count), '결과지표 종류'],
  ];
  $('#corpus-stats').innerHTML = tiles
    .map(([v, k]) => `<div class="stat"><div class="v num">${v}</div><div class="k">${esc(k)}</div></div>`)
    .join('');

  const built = c.last_aggregate ? new Date(c.last_aggregate).toLocaleString('ko-KR') : '아직 없음';
  const range = (c.year_min && c.year_max) ? ` · 논문 발표연도 ${c.year_min}–${c.year_max}` : '';
  $('#footer-build').innerHTML = `색인 생성 ${esc(built)}${esc(range)} · `;

  $('#about-corpus').innerHTML = `
    <h3>현재 색인 상태</h3>
    <div class="scroll-x"><table class="plain">
      <tr><th>수집한 논문</th><td class="num">${n(c.papers)}</td></tr>
      <tr><th>초록이 있는 논문</th><td class="num">${n(c.papers)}</td></tr>
      <tr><th>사람 대상 연구</th><td class="num">${n(c.human_papers)}</td></tr>
      <tr><th>메타분석·체계적 문헌고찰</th><td class="num">${n(c.systematic_papers)}</td></tr>
      <tr><th>무작위대조시험(RCT)</th><td class="num">${n(c.rct_papers)}</td></tr>
      <tr><th>철회 논문 (집계 제외)</th><td class="num">${n(c.retracted_papers)}</td></tr>
      <tr><th>수집 경로</th><td>${esc(c.harvest_source || '—')}</td></tr>
      <tr><th>마지막 수집</th><td>${esc(c.last_harvest || '—')}</td></tr>
      <tr><th>마지막 색인 생성</th><td>${esc(c.last_aggregate || '—')}</td></tr>
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
    : '<span class="badge none">색인된 논문 없음</span>';
  const detail = s.total > 0
    ? `메타분석·체계적 고찰 <b>${n(s.systematic)}</b> · RCT <b>${n(s.rct)}</b>
       · 동물·시험관 <b>${n(s.preclinical)}</b>${s.year_min ? ` · ${s.year_min}–${s.year_max}` : ''}`
    : '이 색인에 수집된 논문이 없습니다. <b>효과가 없다는 뜻이 아닙니다.</b>';
  return `
    <button class="card click" data-ing="${esc(it.id)}">
      <div class="chead">
        <span class="nm">${esc(it.name_ko)}</span>
        <span class="en">${esc(it.name_en)}</span>
        ${badge}
      </div>
      <div class="meta">${esc(it.category_ko)} · ${detail}</div>
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
      <div class="empty"><b>“${esc(state.query)}”에 해당하는 성분을 사전에서 찾지 못했습니다.</b><br>
        영문명(예: <i>lutein</i>)으로 검색해 보시거나, 아래에서 문헌 DB 에 직접 조회할 수 있습니다.
        <div class="btnrow"><button class="btn primary" id="live-btn">문헌 DB 에 실시간으로 조회</button></div>
        <div id="live-result"></div>
      </div>`;
    $('#ing-count').innerHTML = state.query
      ? `“<b>${esc(state.query)}</b>” 검색 결과 <b>${n(state.total)}</b>종`
      : `<b>${n(state.total)}</b>종의 성분 — 사람 대상 연구가 많은 순`;
    $('#ing-more').hidden = state.items.length >= state.total;
  } catch (e) {
    $('#ing-list').innerHTML = `<div class="empty"><b>${esc(e.message)}</b></div>`;
    $('#ing-count').textContent = '';
  }
}

/* ── 실시간 조회 (색인에 없는 검색어) ────────────────────────────────────── */
async function liveLookup(term, mount) {
  mount.innerHTML = '<p class="loading">문헌 DB 에 조회 중…</p>';
  try {
    const d = await api('/api/live?term=' + encodeURIComponent(term));
    if (!d.available) { mount.innerHTML = `<div class="note">${esc(d.reason)}</div>`; return; }
    const dc = d.direction_counts || {};
    mount.innerHTML = `
      <div class="note"><b>실시간 조회 결과</b> — ${esc(d.note)}</div>
      <div class="stats">
        <div class="stat"><div class="v num">${n(d.hit_count)}</div><div class="k">문헌 DB 전체 검색 결과</div></div>
        <div class="stat"><div class="v num">${n(d.fetched)}</div><div class="k">분석한 상위 논문</div></div>
        <div class="stat"><div class="v num">${n(d.human)}</div><div class="k">사람 대상</div></div>
        <div class="stat"><div class="v num">${n(dc.significant)} / ${n(dc.null)} / ${n(dc.unclear)}</div>
          <div class="k">유의 / 유의차없음 / 판정불가</div></div>
      </div>
      ${d.outcomes.length ? `<h3>많이 측정된 항목</h3>${d.outcomes.map((o) =>
        `<div class="orow"><div class="oname">${esc(o.label_ko)}</div>
         <div class="bar"><i class="seg sig" style="flex:${o.human}"></i>
         <i class="seg unclear" style="flex:${Math.max(0, o.total - o.human)}"></i></div>
         <div class="onum num">사람 ${n(o.human)} · 전체 ${n(o.total)}</div></div>`).join('')}` : ''}
      <h3>논문</h3>${d.papers.map((p) => paperItem(p)).join('') || '<p class="dim">없습니다.</p>'}`;
  } catch (e) {
    mount.innerHTML = `<div class="empty"><b>실시간 조회 실패:</b> ${esc(e.message)}</div>`;
  }
}

/* ── 성분 상세 ───────────────────────────────────────────────────────────── */
function yearChart(byYear) {
  if (!byYear || byYear.length < 2) return '';
  const max = Math.max(...byYear.map((y) => y.count));
  const bars = byYear.map((y) =>
    `<i style="height:${Math.max(3, (y.count / max) * 100)}%" title="${y.year}년 ${y.count}건"></i>`).join('');
  return `<h3>연도별 논문 수</h3><div class="years">${bars}</div>
    <div class="yearlbl"><span>${byYear[0].year}</span><span>${byYear[byYear.length - 1].year}</span></div>`;
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

  box.innerHTML = `
    <button class="back" data-back>← 성분 목록으로</button>
    <div class="chead" style="margin-bottom:4px">
      <span class="nm" style="font-size:22px">${esc(d.name_ko)}</span>
      <span class="en">${esc(d.name_en)}</span>
      <span class="badge">${esc(d.category_ko)}</span>
    </div>
    <p class="dim" style="font-size:12.5px">문헌 검색어: ${d.synonyms.map(esc).join(', ')}</p>

    ${hasData ? `
      <div class="stats">
        <div class="stat"><div class="v num">${n(s.total)}</div><div class="k">색인된 논문</div></div>
        <div class="stat"><div class="v num">${n(s.human)}</div><div class="k">사람 대상 연구</div></div>
        <div class="stat"><div class="v num">${n(s.systematic)}</div><div class="k">메타분석·체계적 고찰</div></div>
        <div class="stat"><div class="v num">${n(s.rct)}</div><div class="k">RCT</div></div>
        <div class="stat"><div class="v num">${n(s.preclinical)}</div><div class="k">동물·시험관</div></div>
      </div>
      <div class="note">${d.summary.lines.map((l) => esc(l)).join('<br>')}</div>

      <h2>어떤 항목을 측정했나</h2>
      ${LEGEND}
      ${d.outcomes.length
        ? d.outcomes.map((o) => directionBar(o, maxHuman)).join('')
        : '<p class="dim">사람 대상 연구에서 분류된 결과지표가 없습니다.</p>'}

      <h2>대표 논문</h2>
      <p class="count">근거 위계(메타분석 → 체계적 문헌고찰 → RCT → …)와 피인용 수 순입니다.</p>
      ${d.top_papers.map((p) => paperItem(p, { showEvidence: false })).join('')}

      ${yearChart(d.by_year)}

      <h2>논문 전체 보기</h2>
      <div class="filters">
        <select id="f-outcome"><option value="">전체 항목</option>
          ${d.outcomes.map((o) => `<option value="${esc(o.outcome_id)}">${esc(o.label_ko)} (${n(o.total)})</option>`).join('')}
        </select>
        <select id="f-subject"><option value="">사람·동물 전체</option>
          <option value="human">사람 대상만</option><option value="animal">동물 실험만</option>
          <option value="invitro">시험관·세포만</option></select>
        <select id="f-study"><option value="">모든 연구 유형</option>
          ${d.by_study_type.map((t) => `<option value="${esc(t.study_type)}">${esc(t.label_ko)} (${n(t.count)})</option>`).join('')}
        </select>
        <select id="f-direction"><option value="">모든 결과</option>
          <option value="significant">유의한 결과 보고</option>
          <option value="null">유의차 없음</option>
          <option value="unclear">판정 불가</option></select>
      </div>
      <div id="paper-list"></div>
      <div class="btnrow">
        <button class="btn" id="p-prev">← 이전</button>
        <span id="p-info" class="dim"></span>
        <button class="btn" id="p-next">다음 →</button>
      </div>`
    : `
      <div class="empty">
        <b>이 색인에 ${esc(d.name_ko)} 관련 논문이 없습니다.</b><br>
        아직 수집되지 않았거나, 사람 대상 연구가 보고되지 않았을 수 있습니다.
        <b>“효과가 없다”는 뜻이 아닙니다.</b>
        <div class="btnrow">
          <button class="btn primary" id="live-btn2">문헌 DB 에 실시간으로 조회</button>
        </div>
        <div id="live-result2"></div>
      </div>`}`;

  window.scrollTo({ top: 0, behavior: 'smooth' });

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
    mount.innerHTML = d.items.length
      ? `<p class="count">조건에 맞는 논문 <b>${n(d.total)}</b>건</p>`
        + d.items.map((x) => paperItem(x)).join('')
      : '<div class="empty">이 조건에 맞는 논문이 없습니다.</div>';
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
    <button class="ocard" data-outcome="${esc(o.id)}">
      <span class="ol">${esc(o.label_ko)}</span>
      <span class="oc num">성분 ${n(o.ingredients)}종 · 사람 대상 연구 ${n(o.human)}건</span>
    </button>`).join('')
    : `<div class="empty">“${esc(filter)}”에 해당하는 항목이 없습니다.</div>`;
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

  box.innerHTML = `
    <button class="back" data-back>← 항목 목록으로</button>
    <h2 style="margin-top:0">${esc(d.label_ko)} <span class="en">${esc(d.label_en)}</span></h2>
    <div class="note"><b>${esc(d.note)}</b><br>
      이 항목으로 분류하는 데 쓰는 대표 측정지표: ${d.measures.map(esc).join(', ')}</div>
    ${LEGEND}
    ${d.ingredients.length ? d.ingredients.map((i) => `
      <div class="orow">
        <div class="oname"><button class="obtn" data-ing="${esc(i.id)}">${esc(i.name_ko)}</button>
          <span class="dim" style="font-size:12px">${esc(i.category_ko)}</span></div>
        <div class="bar" style="width:${Math.max(3, Math.round((i.human / maxHuman) * 100))}%">
          <i class="seg sig" style="flex:${i.human_significant}"></i>
          <i class="seg null" style="flex:${i.human_null}"></i>
          <i class="seg unclear" style="flex:${i.human_unclear}"></i>
        </div>
        <div class="onum num">사람 ${n(i.human)} · 전체 ${n(i.total)}</div>
      </div>`).join('')
      : '<div class="empty">이 항목을 측정한 사람 대상 연구가 색인에 없습니다.</div>'}

    <h2>이 항목의 대표 논문</h2>
    ${d.top_papers.map((p) => paperItem(p)).join('') || '<p class="dim">없습니다.</p>'}`;
  window.scrollTo({ top: 0, behavior: 'smooth' });
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
(async function init() {
  try {
    state.meta = await api('/api/meta');
  } catch (e) {
    $('#alerts').innerHTML = `<div class="banner alert"><span class="bt">서버에 연결하지 못했습니다</span>
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
      <b>아직 수집된 논문이 없습니다.</b><br>
      <code>python -m ingest.build all --target 100000</code> 을 실행해 문헌 DB 에서
      논문을 수집하면 이 화면이 실제 데이터로 채워집니다.</div>`;
  }
  route();
})();
