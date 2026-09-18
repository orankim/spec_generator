// ================================================================
// Conversation State — 서버 세션/DB 없이 브라우저에만 둔다(요청서 12절).
// 대화 여러 개를 배열로 관리하고 sessionStorage에 저장한다. 매 API
// 호출은 활성 대화(active conversation)가 들고 있는 조각(current_
// requirement 등)을 그대로 요청 본문에 실어 보낸다 — 서버는 여전히
// 요청 단위로 무상태이며, Agent의 RAG/ChromaDB와는 완전히 분리된
// Frontend 전용 상태다.
// ================================================================
const STORAGE_KEY = 'electrode_ai_conversations_v1';
// sessionStorage는 같은 탭/창을 유지하는 동안(새로고침 포함)에는
// 대화 기록을 보존하지만, 탭이나 브라우저를 완전히 닫으면 사라진다 —
// "브라우저를 완전히 종료했다 재실행하면 이전 대화 목록이 남아있지
// 않아야 한다"는 정책을 브라우저 표준 동작만으로 정확히 만족한다.
// 그와는 별개로, 탭을 계속 열어둔 채 오래 자리를 비운 경우까지
// 대비해 일정 시간(8시간) 이상 비활성 상태면 추가로 초기화한다.
const INACTIVITY_CLEAR_MS = 8 * 60 * 60 * 1000;

const state = {
    conversations: [],        // Conversation[] — 아래 getOrCreateActiveConversation() 참고
    activeConversationId: null,
    searchQuery: '',
    // 대화 이름 변경/삭제(요청서 4절) — 대화 데이터가 아니라 순수 UI 상태이므로
    // sessionStorage에 저장하지 않는다(새로고침하면 자연스럽게 닫힌 상태로
    // 돌아가는 것이 맞다). 한 번에 하나의 항목만 메뉴/편집/삭제확인 상태를
    // 가질 수 있다.
    convMenuOpenId: null,      // ⋯ 더보기 메뉴가 열려 있는 대화 id
    convRenamingId: null,      // 이름 변경 인라인 입력이 열려 있는 대화 id
    pendingDeleteId: null,     // 삭제 확인 모달이 떠 있는 대화 id
};

function loadConversations() {
    try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        return [];
    }
}

// 마지막 활동(가장 최근 updatedAt/createdAt) 이후 INACTIVITY_CLEAR_MS가
// 지났으면 전체 대화 기록을 비운다 — 일부만 지우는 게 아니라 세션
// 전체를 초기화한다(사용자가 기대하는 "오늘 목록이 통째로 사라짐" 동작).
function pruneInactiveConversations(conversations) {
    if (!conversations.length) return conversations;
    const timestamps = conversations
        .map((c) => new Date(c.updatedAt || c.createdAt).getTime())
        .filter((t) => !Number.isNaN(t));
    if (!timestamps.length) return conversations;
    const mostRecent = Math.max(...timestamps);
    if (Date.now() - mostRecent > INACTIVITY_CLEAR_MS) {
        return [];
    }
    return conversations;
}

function saveConversations() {
    try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations));
    } catch (e) {
        // sessionStorage 사용 불가(프라이빗 모드, 용량 초과 등) — 조용히 무시한다.
        // 세션 내 메모리(state.conversations)는 계속 정상 동작하므로 새로고침
        // 전까지는 대화가 유지된다(요청서 12절 1단계 수준으로 자연스럽게 저하).
    }
}

function getActiveConversation() {
    return state.conversations.find(c => c.id === state.activeConversationId) || null;
}

// 활성 대화가 없으면(홈 화면 상태) 이 시점에 새 레코드를 만든다 — "새로운
// 대화 시작" 버튼을 눌러도 실제로 메시지를 보내기 전까지는 사이드바 목록에
// 빈 대화가 쌓이지 않는다.
function getOrCreateActiveConversation() {
    let conv = getActiveConversation();
    if (conv) return conv;
    const now = new Date().toISOString();
    conv = {
        id: (crypto.randomUUID ? crypto.randomUUID() : 'c-' + Date.now().toString(36) + Math.random().toString(36).slice(2)),
        title: '새로운 대화',
        createdAt: now,
        updatedAt: now,
        messages: [],
        currentRequirement: null,
        currentCandidates: null,
        lastSearchResult: null,
    };
    state.conversations.push(conv);
    state.activeConversationId = conv.id;
    return conv;
}

function truncateTitle(text) {
    const t = (text || '').trim().replace(/\\s+/g, ' ');
    if (!t) return '새로운 대화';
    return t.length > 28 ? t.slice(0, 28) + '…' : t;
}

const EXAMPLE_QUESTIONS = [
    '두께 측정 장비 찾기',
    '표면 결함 검사기 찾기',
    'Inline 검사기 찾기',
    'OCT 기반 장비 찾기',
    '3D Profile 검사기 찾기',
];
const EXAMPLE_QUESTION_TEXT = {
    '두께 측정 장비 찾기': '전극 두께를 측정할 수 있는 검사기를 찾아줘.',
    '표면 결함 검사기 찾기': '전극 표면 결함(스크래치, 이물)을 검사할 수 있는 검사기를 찾아줘.',
    'Inline 검사기 찾기': 'Inline으로 실시간 검사할 수 있는 전극 검사기를 찾아줘.',
    'OCT 기반 장비 찾기': 'OCT 기반으로 측정하는 전극 검사기를 찾아줘.',
    '3D Profile 검사기 찾기': '전극의 3D 프로파일(형상)을 측정할 수 있는 검사기를 찾아줘.',
};

// 신규 대화 첫 화면 안내(UX 개선) — 어떤 질문을 입력할 수 있는지 예시를
// 입력창 placeholder로 보여준다. 반드시 value가 아니라 placeholder여야
// 한다: 실제 입력값이면 포커스/타이핑과 무관하게 전송 버튼을 누르는 순간
// 그대로 메시지로 전송될 위험이 있지만, placeholder는 네이티브 HTML
// 동작상 그 자체로는 절대 값이 되지 않고 사용자가 타이핑을 시작하면
// 자동으로 사라진다. 빈 대화(메시지 0개)일 때만 이 문구를 쓰고, 메시지가
// 하나라도 있는(기존 대화를 불러온) 상태에서는 원래 안내 문구로
// 되돌린다 — renderAll()이 매번 이 상태를 다시 계산해서 반영한다.
const NEW_CONVERSATION_PLACEHOLDER = '예 : 폭 800mm 이상의 전극을 inline으로 검사하고, 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘';
const DEFAULT_CHAT_PLACEHOLDER = '필요한 전극 검사 조건이나 궁금한 내용을 입력하세요.';

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = (text === null || text === undefined) ? '' : String(text);
    return div.innerHTML;
}

function genId() {
    return 'm-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function addMessage(msg) {
    const conv = getOrCreateActiveConversation();
    const full = Object.assign({ id: genId(), timestamp: new Date().toISOString() }, msg);
    conv.messages.push(full);
    conv.updatedAt = full.timestamp;
    if (msg.role === 'user' && conv.title === '새로운 대화') {
        conv.title = truncateTitle(msg.content && msg.content.text);
    }
    saveConversations();
    return full;
}

// "답변을 생성하고 있습니다..." 같은 일시적 상태 메시지를 실제 응답이
// 도착하면 지우기 위한 헬퍼(UX 개선 A) — 대화 기록 자체(사용자 질문/AI
// 답변)는 건드리지 않고, id로 지정한 메시지 하나만 제거한다.
function removeMessageById(conv, id) {
    const idx = conv.messages.findIndex(m => m.id === id);
    if (idx !== -1) {
        conv.messages.splice(idx, 1);
        saveConversations();
    }
}

// ================================================================
// 렌더링 — 메시지 type별 Component(순수 함수, HTML 문자열 반환)
// ================================================================
// 값이 없으면 null을 반환한다(문자열 '미정'이 아니라) — 호출부가 행 자체를
// 렌더링하지 않고 건너뛸 수 있게 하기 위함이다(요청서: 값 없는 일반 항목은
// "미정"으로 표시하지 말고 아예 숨긴다. Hard Requirement 비교 영역만 예외).
function fmtRange(range) {
    if (!range || range.min === null || range.min === undefined || range.max === null || range.max === undefined) return null;
    return `${range.min} ~ ${range.max} ${range.unit || ''}`.trim();
}

function fmtReqValue(rv, withPlusMinus) {
    if (!rv || rv.value === null || rv.value === undefined) return null;
    const opLabel = {'<=': '이하', '>=': '이상', '<': '미만', '>': '초과'}[rv.operator] || '';
    const prefix = withPlusMinus ? '±' : '';
    return `${prefix}${rv.value} ${rv.unit || ''} ${opLabel}`.trim();
}

const STATUS_BADGE = {
    USER_DEFINED: '<span class="badge badge-userdefined">USER_DEFINED</span>',
    VERIFIED: '<span class="badge badge-verified">VERIFIED</span>',
    INFERRED: '<span class="badge badge-inferred">INFERRED</span>',
    UNKNOWN: '<span class="badge badge-unknown">UNKNOWN</span>',
};

function sourceDetailHtml(source) {
    if (!source || !source.document) return '';
    const parts = [escapeHtml(source.document)];
    if (source.chunk_id !== null && source.chunk_id !== undefined) parts.push('chunk_' + escapeHtml(source.chunk_id));
    if (source.section) parts.push(escapeHtml(source.section));
    // <summary>가 비어 있고 보이는 "근거 보기" 문구는 CSS ::before로만
    // 그려져(요청서 15절 접근성 테스트 — axe-core "summary-name" 위반
    // 실측: 생성된 콘텐츠는 스크린리더 접근성 트리에 이름으로 잡히지
    // 않는다) 스크린리더 사용자에게는 이름 없는 토글로 들린다.
    // aria-label을 직접 채우고, 펼침/접힘 상태에 따라 문구가 바뀌도록
    // ontoggle에서 갱신한다.
    return `<details class="source-detail" ontoggle="this.querySelector('summary').setAttribute('aria-label', this.open ? '근거 숨기기' : '근거 보기')"><summary aria-label="근거 보기"></summary><div class="source-body">${parts.join(' · ')}</div></details>`;
}

// 값 + 단위 + status 배지 + (VERIFIED면) 근거 문서/chunk. 요청서 13절.
// 값이 없으면 null을 반환한다 — 호출부(EquipmentCard)가 그 행을 아예
// 렌더링하지 않는다("미정"으로 표시하지 않는다. Hard Requirement 비교
// 영역은 이 함수를 쓰지 않고 항상 PASS/FAIL/UNKNOWN을 명시한다).
function fmtSourcedCell(sn) {
    if (!sn || sn.value === null || sn.value === undefined) {
        return null;
    }
    const badge = STATUS_BADGE[sn.status] || '';
    const valueText = escapeHtml(sn.value) + (sn.unit ? ' ' + escapeHtml(sn.unit) : '');
    let html = `<span class="value">${valueText}</span> ${badge}`;
    if (sn.status === 'VERIFIED' && sn.source && sn.source.document) {
        html += sourceDetailHtml(sn.source);
    }
    return html;
}

function fmtSourcedRangeCell(sr) {
    if (!sr || sr.min === null || sr.min === undefined || sr.max === null || sr.max === undefined) {
        return null;
    }
    const badge = STATUS_BADGE[sr.status] || '';
    const valueText = `${escapeHtml(sr.min)} ~ ${escapeHtml(sr.max)} ${escapeHtml(sr.unit || '')}`.trim();
    let html = `<span class="value">${valueText}</span> ${badge}`;
    if (sr.status === 'VERIFIED' && sr.source && sr.source.document) {
        html += sourceDetailHtml(sr.source);
    }
    return html;
}

// ----- 경량 Markdown 렌더러 (요청서 8절) -----
// 제목/소제목/bullet/번호 목록/표/강조/코드블록만 지원하는 최소 구현이다.
// escapeHtml()로 먼저 이스케이프한 뒤 그 결과 위에서 안전한 태그만
// 치환하므로(원본 <, >, &, ", ' 는 이미 엔티티로 바뀐 상태), 사용자/AI
// 텍스트에 실제 HTML 태그가 섞여 있어도 그대로 렌더링되지 않는다.
function renderMarkdownLite(rawText) {
    const escaped = escapeHtml(rawText);
    const lines = escaped.split('\\n');
    const htmlParts = [];
    let listBuffer = null;
    let tableBuffer = null;
    let codeBuffer = null;

    function flushList() {
        if (!listBuffer) return;
        const tag = listBuffer.type;
        htmlParts.push(`<${tag} class="md-list">` + listBuffer.items.map(i => `<li>${i}</li>`).join('') + `</${tag}>`);
        listBuffer = null;
    }
    function flushTable() {
        if (!tableBuffer) return;
        const headHtml = '<tr>' + tableBuffer.header.map(h => `<th>${h}</th>`).join('') + '</tr>';
        const bodyHtml = tableBuffer.rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('');
        htmlParts.push(`<table class="md-table"><thead>${headHtml}</thead><tbody>${bodyHtml}</tbody></table>`);
        tableBuffer = null;
    }
    function inline(s) {
        return s
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
    }

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.trim().startsWith('```')) {
            if (codeBuffer === null) { flushList(); flushTable(); codeBuffer = []; }
            else { htmlParts.push(`<pre class="md-code"><code>${codeBuffer.join('\\n')}</code></pre>`); codeBuffer = null; }
            continue;
        }
        if (codeBuffer !== null) { codeBuffer.push(line); continue; }

        const headerMatch = line.match(/^(#{1,3})\\s+(.*)$/);
        if (headerMatch) {
            flushList(); flushTable();
            const level = headerMatch[1].length + 2;
            htmlParts.push(`<h${level} class="md-heading">${inline(headerMatch[2])}</h${level}>`);
            continue;
        }

        const tableRowMatch = line.match(/^\\|(.+)\\|\\s*$/);
        if (tableRowMatch) {
            const cells = tableRowMatch[1].split('|').map(c => c.trim());
            if (cells.every(c => /^:?-{2,}:?$/.test(c))) {
                continue; // 구분행(|---|---|)은 헤더 확정 후 건너뛴다.
            }
            if (!tableBuffer) { tableBuffer = { header: cells, rows: [] }; }
            else { tableBuffer.rows.push(cells); }
            continue;
        }
        if (tableBuffer) { flushTable(); }

        const bulletMatch = line.match(/^[-*]\\s+(.*)$/);
        if (bulletMatch) {
            if (!listBuffer || listBuffer.type !== 'ul') { flushList(); listBuffer = { type: 'ul', items: [] }; }
            listBuffer.items.push(inline(bulletMatch[1]));
            continue;
        }
        const numberedMatch = line.match(/^\\d+\\.\\s+(.*)$/);
        if (numberedMatch) {
            if (!listBuffer || listBuffer.type !== 'ol') { flushList(); listBuffer = { type: 'ol', items: [] }; }
            listBuffer.items.push(inline(numberedMatch[1]));
            continue;
        }
        flushList();

        if (line.trim() === '') { htmlParts.push('<br>'); continue; }
        htmlParts.push(`<p class="md-p">${inline(line)}</p>`);
    }
    flushList();
    flushTable();
    if (codeBuffer !== null) {
        htmlParts.push(`<pre class="md-code"><code>${codeBuffer.join('\\n')}</code></pre>`);
    }
    return htmlParts.join('');
}

function renderTextMessage(content) {
    return `<div class="msg-text md-body">${renderMarkdownLite(content.text)}</div>`;
}

function renderErrorMessage(content) {
    return `<span class="msg-text">${escapeHtml(content.text)}</span>`;
}

// ----- 답변 생성 중 표시(UX 개선 A) -----
// 사용자가 메시지를 보낸 직후 첫 API 응답이 오기까지 화면 변화가 없어
// "멈췄다"고 오해하지 않도록, 단순하고 정직한 로딩 상태 하나만 보여준다.
// "검색 중...", "분석 중..." 처럼 실제 진행 단계와 연결되지 않은 가짜
// 다단계 문구는 쓰지 않는다 — handleUserMessage()가 실제 요청 시작
// 시점에 이 메시지를 추가하고, 첫 응답(성공/실패 상관없이)이 오면 즉시
// 제거한다(아래 removeMessageById 참고).
function renderThinkingMessage() {
    return `<span class="msg-text thinking-indicator">답변을 생성하고 있습니다...<span class="typing-dots"><span></span><span></span><span></span></span></span>`;
}

// ----- RequirementSummaryCard (요청서 6절) -----
// 정책: 사용자가 실제로 입력했거나 대화 중 확정된 값만 보여준다 — 값이
// 없는 항목은 "미정"으로 채워 넣지 않고 행 자체를 렌더링하지 않는다
// (실사용자 보고: "측정 원리 미정" 같은 줄이 반복되어 정보 밀도가 낮았다).
function renderRequirementSummaryCard(content) {
    const req = content.requirement || {};
    const target = req.target || {};
    const speed = req.measurement_speed && req.measurement_speed.value != null
        ? `${req.measurement_speed.value} ${req.measurement_speed.unit || ''} 이상`.trim() : null;
    const rows = [
        ['검사 대상', target.material || null],
        ['검사 방식', req.inline_offline || null],
        ['최소 검사 폭', (target.width_mm !== null && target.width_mm !== undefined) ? `${target.width_mm} mm` : null],
        ['검사 항목', (req.inspection_items || []).length ? req.inspection_items.join(', ') : null],
        ['측정 범위', fmtRange(req.measurement_range)],
        ['측정 방식', req.measurement_method || null],
        ['측정 원리', req.measurement_principle || null],
        ['요구 정확도', fmtReqValue(req.accuracy, true)],
        ['요구 검사 속도', speed],
    ];
    const rowsHtml = rows
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .map(([label, value]) => `<div class="card-row"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(value)}</span></div>`)
        .join('');
    return `
        <div class="card">
            <div class="card-header">AI가 이해한 요구사항</div>
            <div class="card-body">${rowsHtml || '<span class="value muted">아직 확정된 조건이 없습니다.</span>'}</div>
        </div>
    `;
}

// ----- SearchProgressCard (요청서 10절) -----
// 가짜 진행률이 아니라 실제 API 호출 하나(/generate-spec)의 in-flight
// 여부에 그대로 연결된다 — 'running'이면 전부 pending, 'done'이면 전부
// done으로 한 번에 바뀐다(백엔드가 이 4단계를 한 호출 안에서 순서대로
// 수행하는 것은 사실이며, 이 카드는 그 사실을 정직하게 보여줄 뿐 임의의
// 시간 간격으로 채워지는 연출이 아니다).
function renderSearchProgressCard(content) {
    const stepsPending = ['질문 내용 분석 중', '관련 장비 및 사양 검색 중', '후보 장비 비교 중', '답변 생성 중'];
    const stepsDone = ['질문 내용 분석 완료', '관련 장비 및 사양 검색 완료', '후보 장비 비교 완료', '답변 생성 완료'];
    const done = content.status === 'done';
    const steps = done ? stepsDone : stepsPending;
    const itemsHtml = steps.map(s => `<li class="${done ? 'done' : 'pending'}">${escapeHtml(s)}</li>`).join('');
    // 실제 AI와 대화하는 느낌을 주기 위한 typing indicator(요청서 11절) —
    // 단순 spinner 대신 애니메이션 점 3개를 붙인다. 그 아래 단계 목록은
    // 여전히 실제 API 호출의 in-flight 여부를 정직하게 반영한다(가짜
    // 진행률 아님).
    const runningDots = done ? '' : '<span class="typing-dots"><span></span><span></span><span></span></span>';
    return `
        <div class="card">
            <div class="card-header">${done ? '검색 완료' : '전극검사기 AI가 장비 정보를 분석하고 있습니다'}${runningDots}</div>
            <div class="card-body"><ul class="progress-list">${itemsHtml}</ul></div>
        </div>
    `;
}

// ----- EquipmentCard (요청서 11절) -----
// 정책(요청서 문제5/6): "추천 순위(ranking)"와 "요구조건 충족 여부
// (hard requirement compliance)"를 분리해서 보여준다. UNKNOWN이 하나라도
// 있으면(FAIL이 없어도) "가장 적합한 장비"처럼 단정하지 않고 "확인 필요"로
// 낮춰서 표현한다 — 검색된 후보 중 상대적으로 나은 순위일 뿐, 요구조건을
// 전부 확인했다는 뜻이 아니기 때문이다.
function equipmentBanner(hasFail, hasUnknown, hasRecords) {
    if (hasFail) return '<div class="banner banner-fail">모든 필수 조건을 만족하는 장비를 찾지 못했습니다 — 참고 후보 장비입니다.</div>';
    if (hasUnknown) return '<div class="banner banner-unknown">필수 조건 일부 확인 필요 — 확인된 조건은 만족하지만, 사양서에서 확인되지 않은 조건이 있어 모든 요구조건을 충족한다고 단정할 수 없습니다.</div>';
    if (hasRecords) return '<div class="banner banner-pass">필수 조건을 모두 충족합니다.</div>';
    return '';
}

function equipmentHeaderPrefix(hasFail, hasUnknown, hasRecords) {
    if (hasFail) return '참고 후보';
    if (!hasFail && !hasUnknown && hasRecords) return '추천 장비';
    return '추천 후보';
}

// Hard Requirement 결과를 "확인된 조건(PASS)/미충족 조건(FAIL)/확인 필요
// (UNKNOWN)"으로 묶어 카드 안에 간단히 요약한다 — 바로 아래 이어지는
// renderHardRequirementTable()의 항목별 상세 표(같은 카드 안)를 대체하지
// 않고 빠른 스캔용 요약으로 보완한다.
function confirmationSummaryHtml(hardRequirementReport) {
    const records = hardRequirementReport || [];
    if (records.length === 0) return '';
    const confirmed = records.filter(r => r.result === 'PASS').map(r => escapeHtml(r.item));
    const failed = records.filter(r => r.result === 'FAIL').map(r => escapeHtml(r.item));
    const unresolved = records.filter(r => r.result === 'UNKNOWN').map(r => escapeHtml(r.item));
    const blocks = [];
    if (confirmed.length) blocks.push(`<div class="confirm-block confirm-pass"><strong>확인된 조건</strong><br>${confirmed.map(x => '✓ ' + x).join('<br>')}</div>`);
    if (failed.length) blocks.push(`<div class="confirm-block confirm-fail"><strong>미충족 조건</strong><br>${failed.map(x => '✗ ' + x).join('<br>')}</div>`);
    if (unresolved.length) blocks.push(`<div class="confirm-block confirm-unknown"><strong>확인 필요</strong><br>${unresolved.map(x => '? ' + x).join('<br>')}</div>`);
    return blocks.join('');
}

// ----- 확인되지 않은 사양 접이식 목록(UX 개선 C) -----
// 정책: UNKNOWN 값을 "미정"으로 채워 넣거나 데이터 자체를 지우지 않는다
// (요청서: UNKNOWN 데이터를 결과/내부 데이터에서 삭제하지 않는다) — 다만
// 값이 있는 항목이 우선 보이도록, 값이 없는 항목은 기본 화면에서는 접어
// 두고 "확인되지 않은 사양 N개 보기"를 클릭해야 펼쳐지게 한다. "UNKNOWN"
// 이라는 시스템 용어 대신 "사양서에 정보 없음"으로 표현한다.
function renderUnknownFieldsBlock(labels) {
    if (!labels || labels.length === 0) return '';
    const items = labels
        .map(label => `<div class="unknown-spec-row"><span class="label">${escapeHtml(label)}</span><span>사양서에 정보 없음</span></div>`)
        .join('');
    return `
        <details class="unknown-specs-detail">
            <summary>확인되지 않은 사양 ${labels.length}개 보기</summary>
            <div class="unknown-specs-list">${items}</div>
        </details>
    `;
}

// 사양서 다운로드 포맷 정의 — Markdown/Word 버튼 렌더링과 생성 로직이
// 이 표 하나만 보고 동작하므로, 세 번째 포맷이 추가되어도 여기 한 곳만
// 늘리면 된다(요청서 11절: 중복 코드 방지).
const DOWNLOAD_FORMATS = {
    markdown: {
        endpoint: '/api/agent/build-candidate-markdown',
        btnClass: 'build-markdown-btn',
        urlField: 'downloadUrl',
        generatingField: 'markdownGenerating',
        errorField: 'markdownError',
        formatLabel: 'Markdown',
        generateLabel: 'Markdown 다운로드',
        retryLabel: 'Markdown 다운로드 다시 시도',
        readyLabel: 'Markdown 파일 다운로드',
    },
    docx: {
        endpoint: '/api/agent/build-candidate-docx',
        btnClass: 'build-docx-btn',
        urlField: 'docxDownloadUrl',
        generatingField: 'docxGenerating',
        errorField: 'docxError',
        formatLabel: 'Word',
        generateLabel: 'Word 다운로드',
        retryLabel: 'Word 다운로드 다시 시도',
        readyLabel: 'Word 파일 다운로드',
    },
};

function renderSingleDownloadButton(format, content, msgId) {
    const spec = DOWNLOAD_FORMATS[format];
    if (content[spec.urlField]) {
        return `<a class="download-btn ${spec.btnClass}-ready" href="${escapeHtml(content[spec.urlField])}" download>${spec.readyLabel}</a>`;
    }
    if (content[spec.generatingField]) {
        // Disabled 스타일은 CSS button.download-btn:disabled(grey-300
        // 기반)이 처리한다 — 인라인 opacity로 같은 색을 흐리게
        // 만드는 대신 명확히 구분되는 회색 상태로 표시한다(요청서 4절).
        return `<button type="button" class="download-btn" disabled style="border:none;">생성 중...</button>`;
    }
    // 오류 배너는 보여주되, 버튼 자체는 사라지지 않고 "다시 시도"로
    // 남아있어야 한다 — 그렇지 않으면 한 번 실패한 뒤에는 사용자가
    // 재시도할 방법이 없어 새 검색을 다시 시작해야 하는 silent-failure에
    // 가까운 상태가 된다(요청서: "클릭 후 아무 변화가 없는 silent
    // failure가 없는지"·"다시 시도할 수 있는가").
    const errorBanner = content[spec.errorField]
        ? `<div class="banner banner-fail" style="margin-top:8px;">${spec.formatLabel} 사양서 생성 중 오류가 발생했습니다: ${escapeHtml(content[spec.errorField])}</div>`
        : '';
    const label = content[spec.errorField] ? spec.retryLabel : spec.generateLabel;
    return `${errorBanner}<button type="button" class="download-btn ${spec.btnClass}" data-msg-id="${escapeHtml(msgId)}" data-format="${format}" style="border:none; cursor:pointer;">${label}</button>`;
}

function renderDownloadArea(content, msgId) {
    // 후보 장비가 아예 없으면(예: FAIL만 있어 select_best_candidate가
    // null을 반환한 극단적인 경우는 없지만, 방어적으로) 근거 없는
    // 사양서를 만들지 않고 버튼 자체를 숨긴다.
    if (!content.chosenCandidate) {
        return '';
    }
    return `
        <div class="download-actions">
            ${renderSingleDownloadButton('markdown', content, msgId)}
            ${renderSingleDownloadButton('docx', content, msgId)}
        </div>
    `;
}

// ----- 근거 자료(UX 개선 D) — EquipmentCard 하단에 별도 영역으로 표시.
// 정책 변경(요청서 6절 개선사항 D):
//   1) 기본 화면에서는 접어둔다 — 파일명 목록을 항상 펼쳐 나열하면 화면이
//      복잡해지고 "SPEC-013.md" 같은 내부 파일명이 그대로 노출되어 사용자
//      에게는 기술적으로 보인다. <details>로 감싸 "근거 자료 N개 보기"만
//      기본 표시하고, 클릭하면 펼쳐진다.
//   2) Document-centric(파일명만 나열)보다 Equipment-centric(장비명 +
//      파일명)을 우선한다 — 그 문서가 실제로 채택된 후보(chosenCandidate)의
//      근거 문서와 같으면, 이미 카드에 있는 장비명을 함께 보여준다. 근거가
//      없는 다른 문서까지 장비명을 지어내지 않는다(chosenCandidate와 일치
//      하지 않는 문서는 파일명만 그대로 보여준다 — 근거 없는 추측 금지).
// 문서별 개별 "문서 보기" 링크는 만들지 않는다 — 이 서버에는 SPEC 원본
// 파일을 브라우저에서 열어보는 뷰어 라우트가 없어서, 실제로 동작하지 않는
// 링크를 화면에만 그려 넣는 것은 근거 없는 기능을 지어내는 것과 같기
// 때문이다. 대신 실제로 존재하는 정보(검색된 chunk 수)를 메타 정보로
// 보여준다 — 다만 "chunk"는 개발자 관점 용어라 사용자에게는 "참고한
// 사양서 내용 N개"로 순화해서 표시한다(내부 변수명/데이터 자체는 그대로
// retrievedSourcesCount다 — 표시 문구만 바꾼다). primarySources(근거
// 데이터 자체)는 그대로 유지하고 표시 방식만 바꾼다 — 데이터를 삭제하거나
// 새로 만들지 않는다.
function renderSourcesBlock(primarySources, retrievedSourcesCount, equipmentName, chosenCandidate) {
    if (!primarySources || primarySources.length === 0) return '';
    const uniqueSources = Array.from(new Set(primarySources));
    const items = uniqueSources.map(s => {
        const isChosenDocument = !!(chosenCandidate && chosenCandidate.source_document === s);
        const equipmentLine = (isChosenDocument && equipmentName)
            ? `<div class="source-equipment">${escapeHtml(equipmentName)}</div>`
            : '';
        return `
            <div class="source-item">
                ${equipmentLine}
                <div class="source-doc">${escapeHtml(s)}</div>
            </div>
        `;
    }).join('');
    return `
        <details class="sources-block">
            <summary class="sources-title">근거 자료 ${uniqueSources.length}개 보기</summary>
            <div class="sources-list">${items}</div>
            <div class="source-row source-meta" style="margin-top:6px;">참고한 사양서 내용 ${escapeHtml(retrievedSourcesCount)}개</div>
        </details>
    `;
}

// ----- Duplicate Equipment Name Disambiguation -----
// 배경: sample_specs Corpus 무결성 조사에서 서로 다른 두 사양서(SPEC-044.md/
// SPEC-051.md)가 우연히 같은 Equipment Name("MultiInspect MI-800")을 쓰는
// 사례가 발견됐다. 이름만으로는 후보를 구분할 수 없고, 대화 흐름상 후속
// 질문(예: 정확도를 더 엄격하게)으로 요구사항을 바꾸면 실제로 서로 다른
// SPEC 문서가 chosen_candidate로 선택될 수 있다(재현 확인됨) — 그러면 같은
// 대화 안에 이름이 같은 EquipmentCard 두 개가 나타나 "같은 장비가 중복
// 추천된 것"인지 "실제로 다른 장비"인지 사용자가 구분할 수 없다.
//
// 정책: 이름이 같아도 가리키는 SPEC 문서(source_document)가 실제로 같으면
// (진짜 같은 추천 반복) 아무것도 표시하지 않는다 — 문서가 서로 다를 때만
// 이 카드들이 실제로 구분이 필요한 상황이다. 구분 정보는 이미
// chosen_candidate(CandidateEquipment)에 들어있는 값만 쓰고, 새 Backend
// 데이터를 추가하지 않는다.
const DISAMBIGUATION_PRIORITY = ['manufacturer', 'measurement_method', 'inspection_item', 'width', 'range', 'accuracy', 'source'];

function disambiguationFieldMap(candidate) {
    const map = {};
    if (!candidate) return map;
    const ef = candidate.equipment_fact || {};
    if (candidate.manufacturer) {
        map.manufacturer = { value: candidate.manufacturer, display: candidate.manufacturer };
    }
    if (ef.measurement_method) {
        map.measurement_method = { value: 'method:' + ef.measurement_method, display: `측정 방식: ${ef.measurement_method}` };
    } else if (ef.measurement_principle) {
        map.measurement_method = { value: 'principle:' + ef.measurement_principle, display: `측정 원리: ${ef.measurement_principle}` };
    }
    if (ef.defect_types && ef.defect_types.length) {
        const text = ef.defect_types.join(', ');
        map.inspection_item = { value: text, display: `검사 항목: ${text}` };
    }
    if (ef.width_mm != null) {
        map.width = { value: ef.width_mm, display: `대응 폭: ${ef.width_mm}mm` };
    }
    if (ef.range_min != null && ef.range_max != null) {
        const text = `${ef.range_min}~${ef.range_max}${ef.range_unit || ''}`;
        map.range = { value: text, display: `측정 범위: ${text}` };
    }
    if (ef.accuracy_value != null) {
        const text = `±${ef.accuracy_value}${ef.accuracy_unit || ''}`;
        map.accuracy = { value: text, display: `정확도: ${text}` };
    }
    const specId = (candidate.source_document || '').replace(/\\.md$/i, '');
    if (specId) {
        map.source = { value: specId, display: `Reference: ${specId}` };
    }
    return map;
}

// group: [{ msgId, candidate }] — 모두 같은 Equipment Name이면서 서로 다른
// source_document를 가진 경우에만 호출된다. 우선순위 순서대로 "그룹 전원이
// 값을 갖고 있고 + 값이 서로 다른" 첫 필드를 찾아 그 필드로 구분한다 —
// Random이나 RAG 결과 순서에 의존하지 않는, 후보 데이터 자체만 보는 결정론적
// 선택이다. Source Document(우선순위 마지막)는 spec_id가 서로 다른 한 항상
// 값이 갈리므로 다른 필드가 전부 같아도 반드시 여기서 구분이 성립한다.
function pickDisambiguationLabels(group) {
    const maps = group.map(g => disambiguationFieldMap(g.candidate));
    for (const key of DISAMBIGUATION_PRIORITY) {
        if (!maps.every(m => m[key] !== undefined)) continue;
        const values = maps.map(m => m[key].value);
        if (values.every(v => v === values[0])) continue;
        const labels = {};
        group.forEach((g, i) => { labels[g.msgId] = maps[i][key].display; });
        return labels;
    }
    return {};
}

// 실제 브라우저 재현(요청서 1/5절) 결과, Disambiguation Label(구분 정보)
// 만으로는 "이것이 서로 다른 장비를 구분하기 위한 정보"라는 사실 자체가
// 사용자에게 명확히 전달되지 않았다 — "검사 항목: Surface Defect"와
// "검사 항목: Scratch, Crack, Particle" 같은 값 차이만 보고는, 같은 장비의
// 답변이 문맥에 따라 다르게 요약된 것인지 실제로 다른 장비인지 구분하기
// 어렵다(문제 A). 이를 보완하기 위해 짧은 안내 문구(Contextual Hint)를
// "새로 등장해 기존 그룹과 충돌하는" 메시지에만 추가한다 — 이미 표시된
// 과거 카드에 안내 문구까지 추가로 끼워 넣으면 과거 메시지가 두 번(구분
// 정보 + 안내 문구) 바뀌는 셈이라 오히려 문제 C를 키운다. 안내는 "지금 막
// 등장한, 이전과 다른 장비"라는 대화의 자연스러운 시간 순서를 그대로
// 따른다: 그룹 내에서 이미 등장한 source_document 집합에 없는
// source_document가 새로 나타나는 시점의 메시지에만 붙인다(맨 처음
// 등장한 메시지는 비교 대상이 아직 없으므로 안내가 필요 없다).
function pickContextualHints(group) {
    const hints = {};
    const seenSources = new Set();
    group.forEach((g) => {
        const source = g.candidate.source_document;
        if (seenSources.size > 0 && !seenSources.has(source)) {
            hints[g.msgId] = '이전 추천과 이름은 같지만, 서로 다른 장비입니다.';
        }
        seenSources.add(source);
    });
    return hints;
}

// 현재 대화의 모든 equipment_result 메시지를 Equipment Name으로 묶고,
// 실제로 서로 다른 SPEC 문서를 가리키는 이름 그룹에만 구분 Label/안내
// 문구를 계산한다. 정상적인(이름이 유일하거나, 같은 문서가 반복 추천된)
// 경우는 빈 Map을 돌려줘 기존 카드 UI를 그대로 유지한다. 대화(conv.messages)
// 단위로만 그룹화하므로 다른 Conversation의 동일 이름 장비는 전혀 영향을
// 주지 않는다.
function computeEquipmentDisambiguation(messages) {
    const byName = new Map();
    for (const msg of messages) {
        if (msg.type !== 'equipment_result') continue;
        const spec = msg.content && msg.content.specification;
        const name = spec && spec.equipment && spec.equipment.name;
        const candidate = msg.content && msg.content.chosenCandidate;
        if (!name || !candidate) continue;
        if (!byName.has(name)) byName.set(name, []);
        byName.get(name).push({ msgId: msg.id, candidate: candidate });
    }
    const labels = new Map();
    const hints = new Map();
    for (const group of byName.values()) {
        if (group.length < 2) continue;
        const distinctSources = new Set(group.map(g => g.candidate.source_document));
        if (distinctSources.size < 2) continue; // 같은 문서가 반복 추천된 것뿐 — 구분 불필요
        for (const [msgId, label] of Object.entries(pickDisambiguationLabels(group))) {
            labels.set(msgId, label);
        }
        for (const [msgId, hint] of Object.entries(pickContextualHints(group))) {
            hints.set(msgId, hint);
        }
    }
    return { labels, hints };
}

function renderEquipmentCard(content, msgId, disambiguationLabel, contextualHint) {
    const spec = content.specification;
    const eq = spec.equipment || {};
    const target = spec.inspection_target || {};
    const mp = spec.measurement_performance || {};
    const dd = spec.defect_detection || {};
    const ip = spec.inspection_performance || {};
    const primarySources = (spec.primary_sources && spec.primary_sources.length > 0) ? spec.primary_sources : (spec.sources || []);

    const noResults = content.retrievedSourcesCount === 0
        ? '<div class="banner banner-unknown">조건에 맞는 참고 사양서를 찾지 못했습니다(참고한 사양서 내용 0개). 아래 값은 사용자가 입력한 요구사항 외에는 근거가 없습니다.</div>'
        : '';

    // 검사 폭/속도는 target.width_mm(요구값 echo)이 아니라 후보 문서에서
    // 실제로 확인된 equipment_max_width_mm/line_speed_mm_s를 보여준다 —
    // 다른 행(정확도/최소 검출 결함 크기 등)과 동일하게 "요구값을 그냥
    // 되돌려 보여주면서 마치 확인된 것처럼 보이는" 문제를 피하기 위함이다
    // (실사용자 보고 버그: Width/Speed hard requirement가 FAIL인데도
    // 카드에는 요구값이 그대로 표시되어 통과한 것처럼 보였다).
    //
    // 정책: 실제 장비 사양이 존재하는 항목만 기본 화면에 보여준다 —
    // None/빈 문자열/"미정" 등은 행 자체를 감춘다(Hard Requirement 비교
    // 영역만 예외로 항상 PASS/FAIL/UNKNOWN을 명시한다). 다만 값이 없다고
    // 해서 그 항목이 "확인되지 않았다"는 사실 자체를 완전히 숨기지는
    // 않는다(UX 개선 C) — 근거 문서 대비 값이 있는지(status 개념이 있는)
    // 수치 항목(sourcedFieldRows)만 "확인되지 않은 사양" 접이식 목록으로
    // 따로 모아 필요할 때 펼쳐볼 수 있게 한다. 검사 방식/검사 항목처럼
    // status 개념이 없는 일반 필드(plainFieldRows)는 애초에 "UNKNOWN"이
    // 아니라 "해당 없음"에 가까우므로 이 목록에 넣지 않는다.
    const inspectionItemsText = (spec.inspection_items || []).join(', ');
    const sourcedFieldRows = [
        ['측정 범위', fmtSourcedRangeCell(mp.measurement_range_full)],
        ['정확도', fmtSourcedCell(mp.equipment_accuracy_um)],
        ['분해능', fmtSourcedCell(mp.resolution_um)],
        ['최소 검출 결함 크기', fmtSourcedCell(dd.equipment_minimum_defect_size_um || dd.minimum_defect_size_um)],
        ['대응 가능 폭', fmtSourcedCell(target.equipment_max_width_mm)],
        ['검사 속도', fmtSourcedCell(ip.line_speed_mm_s)],
    ];
    const plainFieldRows = [
        ['검사 방식', eq.inline_offline ? `<span class="value">${escapeHtml(eq.inline_offline)}</span>` : null],
        ['검사 항목', inspectionItemsText ? `<span class="value">${escapeHtml(inspectionItemsText)}</span>` : null],
    ];
    const rowsHtml = [...sourcedFieldRows, ...plainFieldRows]
        .filter(([, valueHtml]) => valueHtml !== null && valueHtml !== undefined)
        .map(([label, valueHtml]) => `<div class="card-row"><span class="label">${escapeHtml(label)}</span>${valueHtml}</div>`)
        .join('');
    const unknownFieldLabels = sourcedFieldRows
        .filter(([, valueHtml]) => valueHtml === null || valueHtml === undefined)
        .map(([label]) => label);
    const unknownFieldsHtml = renderUnknownFieldsBlock(unknownFieldLabels);

    const subtitleHtml = disambiguationLabel
        ? `<div class="card-subtitle">${escapeHtml(disambiguationLabel)}</div>`
        : '';
    // Contextual Hint(요청서 3/4절 Option B) — 같은 이름의 다른 SPEC 문서가
    // "새로 등장"했을 때만, 왜 정보가 다른지 일반 사용자가 이해할 수 있는
    // 자연어 문장으로 짧게 안내한다. 내부 식별자(SPEC ID 등)는 절대 언급하지
    // 않는다 — computeEquipmentDisambiguation/pickContextualHints가 실제로
    // 서로 다른 SPEC 문서가 같은 이름으로 충돌할 때만 값을 채운다.
    const hintHtml = contextualHint
        ? `<div class="card-hint">${escapeHtml(contextualHint)}</div>`
        : '';
    // 문서형 답변 레이아웃: 예전에는 "확인된/미충족/확인 필요 요약"과
    // "항목별 상세 비교"가 각각 이 카드와 별도의 comparison_result 카드로
    // 나뉘어 있었다 — 같은 장비에 대한 같은 정보인데 카드 두 개로 쪼개져
    // 보이는 문제가 있었다. 지금은 요약 다음에 상세 비교 표를 바로 이어
    // 붙여 하나의 "필수 조건" 섹션으로 통합한다(데이터는 동일).
    const specSectionHtml = (rowsHtml || unknownFieldsHtml)
        ? `<div class="doc-subheading">사양 정보</div>${rowsHtml}${unknownFieldsHtml}`
        : '';
    return `
        <div class="card">
            <div class="card-header">${equipmentHeaderPrefix(content.hasFail, content.hasUnknown, content.hasRecords)} — ${escapeHtml(eq.name || 'N/A')}</div>
            ${subtitleHtml}
            <div class="card-body">
                ${hintHtml}
                ${equipmentBanner(content.hasFail, content.hasUnknown, content.hasRecords)}
                ${noResults}
                ${confirmationSummaryHtml(content.hardRequirementReport)}
                ${renderHardRequirementTable(content.hardRequirementReport)}
                ${specSectionHtml}
                ${renderQuoteSummaryBlock(content, msgId)}
                ${renderSourcesBlock(primarySources, content.retrievedSourcesCount, eq.name, content.chosenCandidate)}
                ${renderDownloadArea(content, msgId)}
            </div>
        </div>
    `;
}

// ----- RequirementComparison (요청서 12/13절) -----
// 정책: UNKNOWN을 PASS로 표시하지 않는다 — Backend(agent.candidate_matcher/
// agent.spec_validator)가 이미 PASS/FAIL/UNKNOWN을 코드로 확정해 보내주므로
// 여기서는 그 값을 그대로(재판단 없이) 배지로만 옮긴다.
// 개발자/AI 용어("Hard Requirement", "PASS"/"FAIL"/"UNKNOWN")를 현업
// 사용자가 이해하기 쉬운 한국어 표현으로 옮긴다(UX 개선 B) — 내부
// 값(ComplianceRecord.result/CandidateEquipment.status)이나 배지 CSS
// 클래스(badge-pass/badge-fail/badge-unknown)는 그대로 두고, 화면에
// 보이는 문구만 바꾼다. PARTIAL은 이 화면에서 별도 문자열로 노출되지
// 않지만(hasFail=false && hasUnknown=true 조합이 이미 그 의미를
// banner-unknown/"필수 조건 일부 확인 필요"로 표현한다), 다른 화면에서
// 후보 status를 그대로 문구로 옮겨야 할 때를 대비해 함께 정의해둔다.
const HARD_REQ_RESULT_LABEL = {
    PASS: '필수 조건 충족',
    FAIL: '필수 조건 미충족',
    UNKNOWN: '필수 조건 확인 불가',
    PARTIAL: '필수 조건 일부 확인 필요',
    'N/A': '해당 없음',
};
const RESULT_BADGE = {
    PASS: `<span class="badge badge-pass">${HARD_REQ_RESULT_LABEL.PASS}</span>`,
    FAIL: `<span class="badge badge-fail">${HARD_REQ_RESULT_LABEL.FAIL}</span>`,
    UNKNOWN: `<span class="badge badge-unknown">${HARD_REQ_RESULT_LABEL.UNKNOWN}</span>`,
    'N/A': `<span class="badge badge-unknown" style="background:#e0e0e0; color:#555;">${HARD_REQ_RESULT_LABEL['N/A']}</span>`,
};

// 요구사항/장비 사양 셀 표시 문자열 — hardRequirementReport(ComplianceRecord)의
// requirement/specification은 단일 숫자값이다(범위 표시는 EquipmentCard의
// sourcedFieldRows가 이미 별도로 보여준다). fmtReqValue와 동일한 연산자
// 한글 표기(이상/이하/미만/초과)를 재사용해 표 안에서도 자연스럽게 읽히게 한다.
const _OP_LABEL = {'<=': '이하', '>=': '이상', '<': '미만', '>': '초과', '=': ''};
function hardReqCellText(value, unit, operator, emptyText) {
    if (value === null || value === undefined) return emptyText || '-';
    const opLabel = operator ? (_OP_LABEL[operator] ?? '') : '';
    return `${value}${unit ? ' ' + unit : ''}${opLabel ? ' ' + opLabel : ''}`.trim();
}

// ----- 필수 조건 비교 표(요청서: "조건 | 요구사항 | 장비 사양 | 결과") -----
// 예전에는 별도의 "comparison_result" 메시지/카드로 EquipmentCard 아래에
// 뜬금없이 하나 더 쌓였다 — 지금은 EquipmentCard 안에서 확인된/미충족/확인
// 필요 요약(confirmationSummaryHtml) 바로 다음에 이어지는 하나의 표로
// 통합해 "추천 장비 하나에 대한 답변"이 카드 여러 개가 아니라 하나의
// 문서처럼 읽히게 한다. 데이터(hardRequirementReport)와 PASS/FAIL/UNKNOWN
// 판정 자체는 그대로이고 표시 형태만 바뀐다.
function renderHardRequirementTable(hardRequirementReport) {
    const records = hardRequirementReport || [];
    if (records.length === 0) return '';
    const rowsHtml = records.map(r => {
        const badge = RESULT_BADGE[r.result] || RESULT_BADGE.UNKNOWN;
        const src = (r.result !== 'UNKNOWN' && r.source && r.source.document) ? sourceDetailHtml(r.source) : '';
        return `
            <tr>
                <td class="item-name">${escapeHtml(r.item)}</td>
                <td>${escapeHtml(hardReqCellText(r.requirement, r.unit, r.operator))}</td>
                <td>${escapeHtml(hardReqCellText(r.specification, r.unit, null, '확인 불가'))}</td>
                <td>${badge}${src}</td>
            </tr>
        `;
    }).join('');
    return `
        <div class="doc-subheading">필수 조건 비교</div>
        <div class="table-scroll">
            <table class="hard-req-list">
                <thead><tr><th>조건</th><th>요구사항</th><th>장비 사양</th><th>결과</th></tr></thead>
                <tbody>${rowsHtml}</tbody>
            </table>
        </div>
    `;
}

// ----- 예상 견적(EquipmentCard 내부, 견적 통합 개선) -----
// 추천 장비 결과가 있으면 그 장비에 실제로 연결된 QUOTE 데이터를 함께
// 보여준다(agent/routes.py generate_spec_api가 이제 견적 키워드 유무와
// 무관하게 quote_analyses를 채워 보낸다). 예전에는 이 정보가 답변 맨
// 아래에 별도 "견적 분석" 카드로 뜬금없이 나타났고, 그마저도 후보 전체를
// 한 표에 뒤섞어 "이 견적이 어떤 장비의 것인지" 알기 어려웠다 — 지금은
// 추천된 그 장비(chosenCandidate)의 견적만, 그 장비의 EquipmentCard
// 안에서 바로 이어서 보여준다.
//
// 가격 Hallucination 방어(요청서 10단계): 여기서 보여주는 모든 금액은
// agent.quote_parser.analyze_quotation()이 QUOTE-*.md 원문에서 코드로
// 재계산한 값(computed_*)이며, LLM이 만든 숫자가 아니다. 연결된 QUOTE가
// 없으면 가격을 추측하지 않고 "없음"을 명시한다.
function fmtQuoteAmount(n) {
    if (n === null || n === undefined) return '확인 불가';
    const sign = n < 0 ? '-' : '';
    return `${sign}₩${Math.round(Math.abs(n)).toLocaleString('ko-KR')}`;
}

function quoteIssueHtml(analysis) {
    return (analysis.issues && analysis.issues.length)
        ? `<div class="quote-issue">계산 오류 검출: ${analysis.issues.length}건 — 이 견적 데이터를 신뢰하기 전에 확인이 필요합니다.</div>`
        : '';
}

// 견적 구성 접이식 상세 — 실제 quote_parser 계산 결과에 존재하는(0이
// 아닌) 항목만 나열한다(요청서 7-2절: "실제 QUOTE 데이터 구조에 존재하는
// 항목만 표시"). 기본 장비/합계는 항상 보여준다.
function quoteDetailRowsHtml(analysis) {
    const rows = [['기본 장비', analysis.computed_equipment_amount]];
    if (analysis.computed_options_amount) rows.push(['옵션', analysis.computed_options_amount]);
    if (analysis.computed_additional_cost_amount) rows.push(['추가 비용', analysis.computed_additional_cost_amount]);
    if (analysis.computed_discount) rows.push(['할인', analysis.computed_discount]);
    if (analysis.computed_vat_amount !== null && analysis.computed_vat_amount !== undefined) {
        rows.push(['부가세', analysis.computed_vat_amount]);
    }
    rows.push(['합계', analysis.computed_grand_total]);
    const excludedItems = (analysis.quotation.excluded_items || []);
    const rowsHtml = rows
        .map(([label, amount]) => `<div class="quote-detail-row"><span class="label">${escapeHtml(label)}</span><span class="value">${fmtQuoteAmount(amount)}</span></div>`)
        .join('');
    const excludedHtml = excludedItems.length
        ? `<div class="quote-detail-row"><span class="label">제외 항목</span><span class="value">${excludedItems.map(escapeHtml).join(', ')}</span></div>`
        : '';
    return `<div class="quote-detail-list">${rowsHtml}${excludedHtml}</div>`;
}

// 견적서 다운로드 포맷 정의 — DOWNLOAD_FORMATS(사양서)와 같은 표 기반 패턴.
// 사양서는 EquipmentCard 전체에 후보 하나뿐이라 버튼 상태를 msg.content에
// 바로 두지만, 견적은 한 장비에 여러 건(Case H 대안 견적)이 있을 수 있어
// msg.content.quoteDownloads[quoteKey]로 견적 건별 상태를 따로 둔다
// (quoteKey = "{source_document}::{index}").
const QUOTE_DOWNLOAD_FORMATS = {
    markdown: {
        endpoint: '/api/agent/build-quote-markdown',
        btnClass: 'build-quote-markdown-btn',
        urlField: 'downloadUrl',
        generatingField: 'markdownGenerating',
        errorField: 'markdownError',
        formatLabel: 'Markdown',
        generateLabel: '견적서 Markdown 다운로드',
        retryLabel: '견적서 Markdown 다시 시도',
        readyLabel: '견적서 Markdown 파일 다운로드',
    },
    docx: {
        endpoint: '/api/agent/build-quote-docx',
        btnClass: 'build-quote-docx-btn',
        urlField: 'docxDownloadUrl',
        generatingField: 'docxGenerating',
        errorField: 'docxError',
        formatLabel: 'Word',
        generateLabel: '견적서 Word 다운로드',
        retryLabel: '견적서 Word 다시 시도',
        readyLabel: '견적서 Word 파일 다운로드',
    },
};

function renderSingleQuoteDownloadButton(format, quoteState, msgId, quoteKey) {
    const spec = QUOTE_DOWNLOAD_FORMATS[format];
    if (quoteState[spec.urlField]) {
        return `<a class="download-btn ${spec.btnClass}-ready" href="${escapeHtml(quoteState[spec.urlField])}" download>${spec.readyLabel}</a>`;
    }
    if (quoteState[spec.generatingField]) {
        return `<button type="button" class="download-btn" disabled style="border:none;">생성 중...</button>`;
    }
    const errorBanner = quoteState[spec.errorField]
        ? `<div class="banner banner-fail" style="margin-top:8px;">견적서 ${spec.formatLabel} 생성 중 오류가 발생했습니다: ${escapeHtml(quoteState[spec.errorField])}</div>`
        : '';
    const label = quoteState[spec.errorField] ? spec.retryLabel : spec.generateLabel;
    return `${errorBanner}<button type="button" class="download-btn ${spec.btnClass}" data-msg-id="${escapeHtml(msgId)}" data-quote-key="${escapeHtml(quoteKey)}" data-format="${format}" style="border:none; cursor:pointer;">${label}</button>`;
}

function renderQuoteDownloadArea(content, msgId, quoteKey) {
    content.quoteDownloads = content.quoteDownloads || {};
    const state = content.quoteDownloads[quoteKey] || {};
    return `
        <div class="download-actions" style="margin-top:8px;">
            ${renderSingleQuoteDownloadButton('markdown', state, msgId, quoteKey)}
            ${renderSingleQuoteDownloadButton('docx', state, msgId, quoteKey)}
        </div>
    `;
}

function quoteVariantHtml(analysis, label, downloadAreaHtml) {
    const labelHtml = label ? `<div class="card-row"><span class="label">${escapeHtml(label)}</span><span class="value">${fmtQuoteAmount(analysis.computed_grand_total)}</span></div>` : '';
    return `
        <div class="quote-variant">
            ${labelHtml}
            ${quoteIssueHtml(analysis)}
            <details class="quote-detail-toggle">
                <summary>견적 구성 보기</summary>
                ${quoteDetailRowsHtml(analysis)}
            </details>
            ${downloadAreaHtml}
        </div>
    `;
}

function renderQuoteSummaryBlock(content, msgId) {
    const chosenCandidate = content.chosenCandidate;
    if (!chosenCandidate) return '';
    const quoteAnalyses = content.quoteAnalyses;
    const analyses = (quoteAnalyses && quoteAnalyses[chosenCandidate.source_document]) || [];
    if (analyses.length === 0) {
        return `
            <div class="quote-summary-block">
                <div class="quote-summary-title">예상 견적</div>
                <span class="value muted">현재 저장된 견적 자료가 없어 예상 견적을 제공할 수 없습니다.</span>
            </div>
        `;
    }

    const sourcesHtml = analyses.map(a => `
        <div class="source-item">
            <div class="source-doc">${escapeHtml(a.quotation.source_file)}</div>
        </div>
    `).join('');
    const evidenceHtml = `
        <details class="sources-block">
            <summary class="sources-title">견적 근거 ${analyses.length}개 보기</summary>
            <div class="sources-list">${sourcesHtml}</div>
        </details>
    `;

    if (analyses.length === 1) {
        const quoteKey = `${chosenCandidate.source_document}::0`;
        return `
            <div class="quote-summary-block">
                <div class="quote-summary-title">예상 견적</div>
                <div class="card-row"><span class="label">총 예상 금액</span><span class="value">${fmtQuoteAmount(analyses[0].computed_grand_total)}</span></div>
                ${quoteIssueHtml(analyses[0])}
                <details class="quote-detail-toggle">
                    <summary>견적 구성 보기</summary>
                    ${quoteDetailRowsHtml(analyses[0])}
                </details>
                ${renderQuoteDownloadArea(content, msgId, quoteKey)}
                ${evidenceHtml}
                <div class="value muted" style="margin-top:6px; display:block;">SAMPLE/TEST 데이터 기반이며, 가격이 비싸다/저렴하다는 판단은 비교 근거가 없어 제공하지 않습니다.</div>
            </div>
        `;
    }

    // 동일 장비에 견적이 여러 건 있는 경우(예: 옵션 포함/대안 견적) — 하나를
    // 숨기지 않고 각각 구조적으로 구분해서 보여준다(요청서 6-2절). 다운로드도
    // 건별로 독립적으로 생성/실패한다.
    const variantsHtml = analyses
        .map((a, idx) => quoteVariantHtml(
            a,
            idx === 0 ? '기본 견적' : `대안 견적 ${idx}`,
            renderQuoteDownloadArea(content, msgId, `${chosenCandidate.source_document}::${idx}`)
        ))
        .join('');
    return `
        <div class="quote-summary-block">
            <div class="quote-summary-title">예상 견적 (${analyses.length}건)</div>
            ${variantsHtml}
            ${evidenceHtml}
            <div class="value muted" style="margin-top:6px; display:block;">SAMPLE/TEST 데이터 기반이며, 가격이 비싸다/저렴하다는 판단은 비교 근거가 없어 제공하지 않습니다.</div>
        </div>
    `;
}

function renderMessageContent(msg, disambiguation) {
    switch (msg.type) {
        case 'text': return renderTextMessage(msg.content);
        case 'requirement_summary': return renderRequirementSummaryCard(msg.content);
        case 'search_status': return renderSearchProgressCard(msg.content);
        case 'equipment_result': return renderEquipmentCard(
            msg.content, msg.id,
            disambiguation && disambiguation.labels.get(msg.id),
            disambiguation && disambiguation.hints.get(msg.id)
        );
        case 'error': return renderErrorMessage(msg.content);
        case 'thinking': return renderThinkingMessage();
        default: return '';
    }
}

function renderExampleChips() {
    const chips = EXAMPLE_QUESTIONS.map(q => `<button type="button" class="chip" data-question="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join('');
    return `<div class="chip-row">${chips}</div>`;
}

function makeWelcomeBlock() {
    const wrap = document.createElement('div');
    wrap.className = 'welcome-block';
    wrap.innerHTML = `
        <div class="welcome-icon"></div>
        <h2>안녕하세요. 전극검사기 AI입니다.</h2>
        <p>찾고 있는 전극 검사 장비의 조건이나 궁금한 내용을 입력해주세요.</p>
        ${renderExampleChips()}
    `;
    return wrap;
}

function renderAll() {
    const container = document.getElementById('messages');
    const conv = getActiveConversation();
    const messages = conv ? conv.messages : [];
    const wasAtBottom = (container.scrollTop + container.clientHeight) >= (container.scrollHeight - 40);
    // 동일 Equipment Name을 가진 서로 다른 SPEC 문서가 이 대화(conv.messages,
    // 다른 대화에는 영향 없음) 안에 함께 등장하는지는 매번(새 메시지 추가/
    // 복원 포함) 메시지 전체를 다시 봐야만 알 수 있다 — 렌더링마다 결정론적
    // 으로 재계산한다(Message에 상태로 저장하지 않음: 후보가 하나 더 추가돼
    // 그룹을 구분하는 기준 필드 자체가 바뀌어야 하는 경우, 예전에 저장해둔
    // 값을 그대로 두면 오히려 틀린 구분 정보가 굳어버릴 수 있다 — 아래
    // TESTING.md "과거 메시지 처리 방식" 절 참고).
    const disambiguation = computeEquipmentDisambiguation(messages);

    container.innerHTML = '';
    if (messages.length === 0) {
        container.classList.add('is-empty');
        container.appendChild(makeWelcomeBlock());
        chatInput.placeholder = NEW_CONVERSATION_PLACEHOLDER;
    } else {
        container.classList.remove('is-empty');
        chatInput.placeholder = DEFAULT_CHAT_PLACEHOLDER;
        messages.forEach(msg => {
            const isUser = msg.role === 'user';
            const row = document.createElement('div');
            row.className = 'msg-row ' + (isUser ? 'user' : 'ai');
            const bubble = document.createElement('div');
            bubble.className = 'bubble ' + (isUser ? 'user' : (msg.type === 'error' ? 'ai error' : 'ai'));
            // .bubble은 텍스트 메시지의 줄바꿈(\\n)을 살리려고 white-space:
            // pre-wrap을 쓴다 — 그런데 카드 컴포넌트들은 들여쓰기된 템플릿
            // 리터럴을 반환하므로, trim() 없이 그대로 넣으면 앞뒤 공백/개행이
            // 그대로 렌더링되어 카드 위에 빈 공백이 보이는 문제가 있다.
            bubble.innerHTML = renderMessageContent(msg, disambiguation).trim();
            if (isUser) {
                // 사용자 Avatar(문서 9절): Secondary-500 Purple.
                const avatar = document.createElement('div');
                avatar.className = 'user-avatar';
                avatar.textContent = '나';
                row.appendChild(bubble);
                row.appendChild(avatar);
            } else {
                row.appendChild(bubble);
            }
            container.appendChild(row);
        });
    }
    if (wasAtBottom || messages.length <= 1) {
        container.scrollTop = container.scrollHeight;
    }
    wireExampleChips();
    wireCardActions();
    renderConvList();
}

function wireCardActions() {
    document.querySelectorAll('.build-markdown-btn, .build-docx-btn').forEach(btn => {
        btn.addEventListener('click', () => buildDocumentForMessage(btn.dataset.msgId, btn.dataset.format));
    });
    document.querySelectorAll('.build-quote-markdown-btn, .build-quote-docx-btn').forEach(btn => {
        btn.addEventListener('click', () => buildQuoteDocumentForMessage(btn.dataset.msgId, btn.dataset.quoteKey, btn.dataset.format));
    });
}

// 생성 완료 직후 실제 파일 다운로드를 코드로 트리거한다 — 사용자가
// "생성" 버튼을 누른 뒤 화면에 나타난 다운로드 링크를 다시 한 번
// 클릭해야 하는 2단계 흐름(버그 리포트)을 없애고, 한 번의 클릭으로
// 생성과 다운로드가 모두 끝나도록 한다. 서버(main.py:/api/download/
// {file_name})가 FileResponse(filename=...)로 Content-Disposition:
// attachment를 이미 보내므로 파일명은 서버가 결정한 값을 그대로
// 따른다 — 여기서는 클릭을 대신 발생시키는 역할만 한다.
function triggerDownload(url) {
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    // download 속성이 없으면 서버가 Content-Disposition: attachment를
    // 보내지 않는 응답(예: 오류 페이지)에서 브라우저가 다운로드 대신
    // 그 URL로 페이지 전체를 이동시켜버린다(SPA 상태 소실). 기존에
    // 렌더링되던 정적 <a ... download> 링크와 동일하게 download 속성을
    // 붙여, 같은 출처 링크는 항상 다운로드로 처리되도록 강제한다.
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// 요청서 흐름의 마지막 단계(최종 사양서 다운로드) — EquipmentCard에 심은
// Markdown/Word 버튼 둘 다 이 함수 하나로 처리한다(format 인자로 분기).
// 그 검색을 만든 시점의 requirement/hardRequirementReport를 그대로 함께
// 보내(각 메시지 content에 스냅샷으로 저장해둠) build-candidate-markdown/
// build-candidate-docx API(agent/routes.py)가 같은 Structured Data
// (renderers/candidate_specification.py)로 두 포맷을 만들도록 한다 —
// 두 포맷이 서로 다른 값을 보여주는 문제를 막는다(요청서 4/11절).
async function buildDocumentForMessage(msgId, format) {
    const spec = DOWNLOAD_FORMATS[format];
    if (!spec) return;
    const conv = getActiveConversation();
    const msg = conv && conv.messages.find(m => m.id === msgId);
    if (!msg || !msg.content.chosenCandidate) return;
    // 이미 생성되어 다운로드 URL이 있으면(예: 재렌더링 사이에 같은 버튼이
    // 다시 클릭된 경우) API를 다시 호출하지 않고 있는 파일을 그대로
    // 다시 내려받는다 — "한 번 생성되면 그 다음부터는 생성 없이 다운로드만"
    // 정책. 평소에는 생성이 끝나는 즉시 렌더링이 실제 <a href download>
    // 링크로 바뀌어 이 함수 자체가 다시 호출되지 않지만, 방어적으로 남겨둔다.
    if (msg.content[spec.urlField]) {
        triggerDownload(msg.content[spec.urlField]);
        return;
    }
    // 이미 생성 중이면 같은 버튼을 다시 눌러도 무시한다 — 클릭과 renderAll()
    // 재렌더링(버튼 disabled 반영) 사이의 짧은 틈에 빠르게 여러 번 누르면
    // 중복 API 요청/중복 파일 생성이 발생하는 문제를 막는다(요청서 14절).
    if (msg.content[spec.generatingField]) return;
    // 클릭 즉시 버튼을 "생성 중..."으로 바꿔 눈에 보이는 피드백을 준다 —
    // 요청이 오래 걸리면 버튼이 그대로 있어 "눌러도 반응이 없다"처럼
    // 보일 수 있었다.
    msg.content[spec.generatingField] = true;
    msg.content[spec.errorField] = null;
    renderAll();
    try {
        const data = await postJSON(spec.endpoint, {
            candidate: msg.content.chosenCandidate,
            requirement: msg.content.requirement,
            hard_requirement_report: msg.content.hardRequirementReport,
        });
        msg.content[spec.urlField] = data.download_url;
    } catch (err) {
        msg.content[spec.errorField] = err.message;
    } finally {
        msg.content[spec.generatingField] = false;
        saveConversations();
        renderAll();
    }
    // 생성이 실제로 성공했을 때만(URL이 채워졌을 때만) 자동으로 다운로드를
    // 시작한다 — 실패 시에는 오류 배너 + "다시 시도" 버튼만 보여준다.
    if (msg.content[spec.urlField]) {
        triggerDownload(msg.content[spec.urlField]);
    }
}

// buildDocumentForMessage(사양서)와 같은 흐름이지만, 견적은 한 장비에
// 여러 건(대안 견적)이 있을 수 있어 상태를 msg.content 최상위가 아니라
// msg.content.quoteDownloads[quoteKey]에 견적 건별로 따로 둔다. 서버에
// 다시 계산을 맡기지 않고, 화면에 이미 표시된(그 검색 시점에 계산된)
// QuoteAnalysis를 그대로 build-quote-markdown/build-quote-docx로 보낸다
// — 다운로드 문서의 금액이 화면에 보이는 금액과 항상 일치하도록.
async function buildQuoteDocumentForMessage(msgId, quoteKey, format) {
    const spec = QUOTE_DOWNLOAD_FORMATS[format];
    if (!spec) return;
    const conv = getActiveConversation();
    const msg = conv && conv.messages.find(m => m.id === msgId);
    if (!msg) return;
    const sepIdx = quoteKey.lastIndexOf('::');
    const sourceDocument = quoteKey.slice(0, sepIdx);
    const idx = Number(quoteKey.slice(sepIdx + 2));
    const analyses = (msg.content.quoteAnalyses && msg.content.quoteAnalyses[sourceDocument]) || [];
    const analysis = analyses[idx];
    if (!analysis) return;

    msg.content.quoteDownloads = msg.content.quoteDownloads || {};
    const state = msg.content.quoteDownloads[quoteKey] = msg.content.quoteDownloads[quoteKey] || {};

    if (state[spec.urlField]) {
        triggerDownload(state[spec.urlField]);
        return;
    }
    if (state[spec.generatingField]) return;
    state[spec.generatingField] = true;
    state[spec.errorField] = null;
    renderAll();
    try {
        const data = await postJSON(spec.endpoint, { quote_analysis: analysis });
        state[spec.urlField] = data.download_url;
    } catch (err) {
        state[spec.errorField] = err.message;
    } finally {
        state[spec.generatingField] = false;
        saveConversations();
        renderAll();
    }
    if (state[spec.urlField]) {
        triggerDownload(state[spec.urlField]);
    }
}

function wireExampleChips() {
    document.querySelectorAll('.chip').forEach(btn => {
        btn.addEventListener('click', () => {
            const question = btn.dataset.question;
            handleUserMessage(EXAMPLE_QUESTION_TEXT[question] || question);
        });
    });
}

// ================================================================
// 대화 목록 사이드바 — 검색/날짜별 그룹핑/선택
// ================================================================
function formatGroupLabel(dateObj) {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfYesterday = new Date(startOfToday);
    startOfYesterday.setDate(startOfYesterday.getDate() - 1);
    const startOfThat = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
    if (startOfThat.getTime() === startOfToday.getTime()) return '오늘';
    if (startOfThat.getTime() === startOfYesterday.getTime()) return '어제';
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}/${m}/${d}`;
}

// 대화 하나(.conv-item-row)를 상태(state.convRenamingId/convMenuOpenId)에 따라
// "일반 표시" 또는 "이름 변경 인라인 입력" 중 하나로 그린다(요청서 4-1절).
function renderConvItemRow(c) {
    const isActive = c.id === state.activeConversationId;
    const title = c.title || '새로운 대화';

    if (state.convRenamingId === c.id) {
        return `
            <div class="conv-item-row ${isActive ? 'active' : ''}" data-conv-id="${escapeHtml(c.id)}">
                <form class="conv-rename-form" data-conv-id="${escapeHtml(c.id)}">
                    <input type="text" class="conv-rename-input" value="${escapeHtml(title)}" maxlength="60" aria-label="대화 이름 변경">
                    <button type="submit" class="conv-rename-save" title="저장" aria-label="저장">✓</button>
                    <button type="button" class="conv-rename-cancel" title="취소" aria-label="취소">✕</button>
                </form>
            </div>
        `;
    }

    const isMenuOpen = state.convMenuOpenId === c.id;
    const dropdownHtml = isMenuOpen ? `
        <div class="conv-item-dropdown" role="menu">
            <button type="button" class="conv-menu-item conv-menu-rename" data-conv-id="${escapeHtml(c.id)}" role="menuitem">✏️ 이름 변경</button>
            <button type="button" class="conv-menu-item conv-menu-delete" data-conv-id="${escapeHtml(c.id)}" role="menuitem">🗑 대화 삭제</button>
        </div>
    ` : '';
    return `
        <div class="conv-item-row ${isActive ? 'active' : ''}" data-conv-id="${escapeHtml(c.id)}">
            <button type="button" class="conv-item" data-conv-id="${escapeHtml(c.id)}" title="${escapeHtml(title)}">
                ${escapeHtml(title)}
            </button>
            <button type="button" class="conv-item-menu-btn" data-conv-id="${escapeHtml(c.id)}" title="대화 관리" aria-label="대화 관리 메뉴" aria-haspopup="true" aria-expanded="${isMenuOpen ? 'true' : 'false'}">⋯</button>
            ${dropdownHtml}
        </div>
    `;
}

function renderConvList() {
    const container = document.getElementById('convList');
    const query = (state.searchQuery || '').trim().toLowerCase();
    let list = state.conversations.filter(c => c.messages.length > 0);
    list.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    if (query) list = list.filter(c => (c.title || '').toLowerCase().includes(query));

    if (list.length === 0) {
        container.innerHTML = `<div class="conv-empty">${query ? '검색 결과가 없습니다.' : '대화 이력이 없습니다.'}</div>`;
        renderConvDeleteModal();
        return;
    }

    const groups = [];
    const groupIndex = {};
    list.forEach(c => {
        const label = formatGroupLabel(new Date(c.updatedAt || c.createdAt));
        if (!(label in groupIndex)) { groupIndex[label] = { label: label, items: [] }; groups.push(groupIndex[label]); }
        groupIndex[label].items.push(c);
    });

    container.innerHTML = groups.map(g => `
        <div class="conv-group">
            <div class="conv-group-label">${escapeHtml(g.label)}</div>
            ${g.items.map(c => renderConvItemRow(c)).join('')}
        </div>
    `).join('');

    // 대화 전환 — 편집 폼(.conv-rename-form)이 떠 있는 행에는 .conv-item 버튼
    // 자체가 없으므로 자연히 이 핸들러의 대상이 아니다.
    container.querySelectorAll('.conv-item').forEach(btn => {
        btn.addEventListener('click', () => {
            state.activeConversationId = btn.dataset.convId;
            state.convMenuOpenId = null;
            renderAll();
        });
    });

    container.querySelectorAll('.conv-item-menu-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleConvMenu(btn.dataset.convId);
        });
    });

    container.querySelectorAll('.conv-menu-rename').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            startRenameConversation(btn.dataset.convId);
        });
    });

    container.querySelectorAll('.conv-menu-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            requestDeleteConversation(btn.dataset.convId);
        });
    });

    container.querySelectorAll('.conv-rename-form').forEach(form => {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = form.querySelector('.conv-rename-input');
            commitRenameConversation(form.dataset.convId, input.value);
        });
        form.querySelector('.conv-rename-cancel').addEventListener('click', (e) => {
            e.stopPropagation();
            cancelRenameConversation();
        });
        const input = form.querySelector('.conv-rename-input');
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                cancelRenameConversation();
            }
        });
    });

    // 이름 변경 모드로 막 들어왔다면 입력에 포커스 + 전체 선택(바로 typing으로
    // 덮어쓸 수 있게) — DOM이 매 렌더마다 새로 만들어지므로 매번 다시 해준다.
    if (state.convRenamingId) {
        const activeInput = container.querySelector(
            '.conv-rename-form[data-conv-id="' + cssEscapeAttr(state.convRenamingId) + '"] .conv-rename-input'
        );
        if (activeInput) { activeInput.focus(); activeInput.select(); }
    }

    renderConvDeleteModal();
}

// CSS.escape가 없는 아주 오래된 환경까지 고려한 최소 폴백 — 대화 id는
// crypto.randomUUID() 결과이거나 영숫자 접두사 조합이라 실제로는 특수문자를
// 걱정할 필요가 거의 없지만, 속성 선택자에 그대로 문자열 보간하는 것은
// 피한다.
function cssEscapeAttr(value) {
    return (window.CSS && CSS.escape) ? CSS.escape(value) : String(value).replace(/["\\\\]/g, '\\\\$&');
}

// ----- 대화 관리(⋯) 메뉴 열기/닫기 -----
function toggleConvMenu(id) {
    state.convMenuOpenId = (state.convMenuOpenId === id) ? null : id;
    renderConvList();
}

function closeConvMenu() {
    if (state.convMenuOpenId !== null) {
        state.convMenuOpenId = null;
        renderConvList();
    }
}

// ----- 대화 이름 변경(요청서 4-1절) -----
function startRenameConversation(id) {
    state.convMenuOpenId = null;
    state.convRenamingId = id;
    renderConvList();
}

function cancelRenameConversation() {
    state.convRenamingId = null;
    renderConvList();
}

// 빈 문자열/공백만 입력하면 저장하지 않고 기존 이름을 유지한다(요청서:
// "빈 문자열, 공백(whitespace only) 입력 방지"). 대화 id/메시지 기록은
// 절대 건드리지 않고 title 필드만 바꾼다.
function commitRenameConversation(id, rawValue) {
    const trimmed = (rawValue || '').trim();
    if (trimmed) {
        const conv = state.conversations.find(c => c.id === id);
        if (conv) {
            conv.title = trimmed;
            saveConversations();
        }
    }
    state.convRenamingId = null;
    renderConvList();
}

// ----- 대화 삭제(요청서 4-2절) -----
function requestDeleteConversation(id) {
    state.convMenuOpenId = null;
    state.pendingDeleteId = id;
    renderConvList();
}

function cancelDeleteConversation() {
    state.pendingDeleteId = null;
    renderConvList();
}

function confirmDeleteConversation(id) {
    const idx = state.conversations.findIndex(c => c.id === id);
    if (idx !== -1) state.conversations.splice(idx, 1);
    state.pendingDeleteId = null;
    // 지금 보고 있던 대화를 삭제한 경우 화면이 깨지지 않도록(참조하던
    // conv가 배열에서 사라짐) 새로운 빈 대화 화면으로 안전하게 전환한다 —
    // getOrCreateActiveConversation()이 다음 메시지 전송 시점에 알아서
    // 새 레코드를 만들므로 여기서는 activeConversationId만 비우면 된다.
    if (state.activeConversationId === id) {
        state.activeConversationId = null;
    }
    saveConversations();
    renderAll(); // messages 영역도 함께 갱신(현재 대화가 삭제됐다면 welcome-block으로).
}

function renderConvDeleteModal() {
    const root = document.getElementById('convDeleteModalRoot');
    if (!state.pendingDeleteId) {
        root.innerHTML = '';
        return;
    }
    const conv = state.conversations.find(c => c.id === state.pendingDeleteId);
    const title = (conv && conv.title) || '새로운 대화';
    root.innerHTML = `
        <div class="modal-backdrop" id="convDeleteBackdrop">
            <div class="modal-box" role="alertdialog" aria-modal="true" aria-labelledby="convDeleteTitle">
                <h2 id="convDeleteTitle">대화를 삭제할까요?</h2>
                <p>"${escapeHtml(title)}" 대화가 영구적으로 삭제되며 되돌릴 수 없습니다.</p>
                <div class="modal-actions">
                    <button type="button" class="modal-btn-cancel" id="convDeleteCancelBtn">취소</button>
                    <button type="button" class="modal-btn-danger" id="convDeleteConfirmBtn">삭제</button>
                </div>
            </div>
        </div>
    `;
    document.getElementById('convDeleteCancelBtn').addEventListener('click', cancelDeleteConversation);
    document.getElementById('convDeleteConfirmBtn').addEventListener('click', () => confirmDeleteConversation(state.pendingDeleteId));
    // Backdrop의 빈 영역 클릭 시에도 취소(모달 상자 자체 클릭은 버블링을
    // 막지 않아도 된다 — 클릭 지점이 정확히 backdrop 요소 자신일 때만 닫는다).
    document.getElementById('convDeleteBackdrop').addEventListener('click', (e) => {
        if (e.target.id === 'convDeleteBackdrop') cancelDeleteConversation();
    });
}

// ================================================================
// 메시지 처리 — 요청서 5/7/8/9/14/15절
// ================================================================
function isExplanationQuery(text) {
    return /왜|이유|설명해|근거가|어째서/.test(text);
}

// 요청서 14절: 근거 없는 내용을 새로 생성하지 않는다 — LLM을 호출하지
// 않고, 이미 검증된 lastSearchResult(hard_requirement_report)만 문구로
// 옮긴다.
// 정책(요청서 문제6): "ranking"(검색된 후보 중 상대적으로 나음)과 "hard
// requirement compliance"(요구조건을 실제로 다 확인했는지)를 표현을
// 분리한다 — UNKNOWN이 하나라도 있으면 "추천된 이유"(=전부 만족한다는
// 인상을 주는 표현) 대신 "확인된 조건을 가장 많이 만족하는 후보"라고만
// 말하고, 확인되지 않은 조건과 추가 확인이 필요하다는 점을 명시한다.
function buildExplanationMessage(conv) {
    const result = conv.lastSearchResult;
    if (!result) return '아직 추천된 장비가 없습니다. 먼저 요구사항을 말씀해 주세요.';
    const spec = result.specification;
    const records = result.hardRequirementReport || [];
    const name = (spec.equipment && spec.equipment.name) || '이 장비';
    const passItems = records.filter(r => r.result === 'PASS').map(r => r.item);
    const failItems = records.filter(r => r.result === 'FAIL').map(r => r.item);
    const unknownItems = records.filter(r => r.result === 'UNKNOWN').map(r => r.item);

    if (records.length === 0) {
        return `${name}에 대해 평가된 필수 조건 항목이 없습니다(요구사항에 확인 가능한 조건이 지정되지 않았습니다).`;
    }

    const hasFail = failItems.length > 0;
    const hasUnknown = unknownItems.length > 0;

    if (!hasFail && !hasUnknown) {
        return `${name}가 추천된 이유는 다음과 같습니다.\\n\\n` + passItems.map(x => `✓ ${x} 조건 만족`).join('\\n');
    }

    const parts = [`현재 검색된 후보 중 확인된 요구조건을 가장 많이 만족하는 후보(${name})입니다.`];
    if (passItems.length) parts.push('확인된 조건:\\n' + passItems.map(x => `✓ ${x}`).join('\\n'));
    if (failItems.length) parts.push('충족하지 못한 조건:\\n' + failItems.map(x => `✗ ${x}`).join('\\n'));
    if (unknownItems.length) parts.push('확인되지 않은 조건:\\n' + unknownItems.map(x => `? ${x}`).join('\\n'));
    if (hasUnknown) parts.push('따라서 최종 도입 전에는 확인되지 않은 조건을 장비 제조사 또는 추가 사양서로 반드시 확인해야 합니다.');
    return parts.join('\\n\\n');
}

// 요청서 문제1: 후속 메시지가 반영된 뒤 보여줄 문구는 절대 내부 필드명
// (accuracy, raw_text, required_accuracy_um 등)을 그대로 노출하지 않는다 —
// 서버(agent/routes.py._summarize_requirement_changes)가 이미 사람이 읽는
// label/action(added·changed·removed)으로 정리해 보내주므로, 여기서는
// 그 label만 문구로 옮긴다.
function buildRequirementChangeMessage(changedSummary) {
    const added = changedSummary.filter(c => c.action === 'added').map(c => c.label);
    const changed = changedSummary.filter(c => c.action === 'changed').map(c => c.label);
    const removed = changedSummary.filter(c => c.action === 'removed').map(c => c.label);

    if (added.length === 0 && changed.length === 0 && removed.length === 1) {
        return `요구 ${removed[0]} 조건을 삭제했습니다.\\n\\n기존 조건을 기준으로 다시 검색하겠습니다.`;
    }

    const lines = ['요구사항을 수정했습니다.', ''];
    if (added.length) lines.push('추가된 조건:', ...added.map(l => `- ${l}`), '');
    if (changed.length) lines.push('변경된 조건:', ...changed.map(l => `- ${l}`), '');
    if (removed.length) lines.push('삭제된 조건:', ...removed.map(l => `- ${l}`), '');
    lines.push('나머지 조건은 그대로 유지됩니다. 새로운 조건을 기준으로 다시 검색하겠습니다.');
    return lines.join('\\n');
}

function buildFollowupQuestionText(validation) {
    const questions = validation.questions || [];
    if (!questions.length) return '';
    const numbered = questions.map((q, i) => `${i + 1}. ${q}`).join('\\n');
    return `더 적합한 장비를 찾기 위해 몇 가지 조건을 추가로 알려주시면 좋습니다(꼭 전부 답하지 않아도 지금 조건으로 검색은 계속 진행됩니다).\\n\\n${numbered}`;
}

async function postJSON(url, payload) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (url + ' 요청 실패'));
    return data;
}

async function runSearch(conv, requirement) {
    const progressMsg = addMessage({ role: 'assistant', type: 'search_status', content: { status: 'running' } });
    renderAll();

    const data = await postJSON('/api/agent/generate-spec', { requirement: requirement });

    progressMsg.content = { status: 'done' };

    const hardRecords = data.hard_requirement_report || [];
    const hasFail = hardRecords.some(r => r.result === 'FAIL');
    const hasUnknown = hardRecords.some(r => r.result === 'UNKNOWN');
    const retrievedSourcesCount = (data.retrieved_sources || []).length;

    conv.lastSearchResult = {
        specification: data.specification,
        validation: data.validation,
        hardRequirementReport: hardRecords,
        retrievedSourcesCount: retrievedSourcesCount,
    };
    conv.currentCandidates = hardRecords;

    addMessage({
        role: 'assistant', type: 'equipment_result',
        content: {
            specification: data.specification, retrievedSourcesCount: retrievedSourcesCount,
            hasFail: hasFail, hasUnknown: hasUnknown, hasRecords: hardRecords.length > 0,
            hardRequirementReport: hardRecords,
            // build-markdown 호출 시 이 검색을 만든 시점 그대로 재사용하기 위한 스냅샷.
            requirement: requirement, validation: data.validation,
            // "마크다운 사양서 생성" 버튼용 — RAG로 찾은 후보 장비 원본 사양
            // (LLM을 거치지 않은 값). 후보가 아예 없으면 null.
            chosenCandidate: data.chosen_candidate || null,
            // 추천 장비에 연결된 QUOTE 데이터(견적 통합 개선) — backend가
            // 이제 견적 키워드 유무와 무관하게 채워 보낸다. renderEquipmentCard가
            // chosenCandidate.source_document로 이 dict에서 자기 견적만
            // 찾아 카드 안에 바로 이어서 보여준다(renderQuoteSummaryBlock).
            quoteAnalyses: data.quote_analyses || {},
        },
    });
}

// #chatInput/#sendBtn만 disabled로 막는 것으로는 부족하다 — 홈 화면
// 예시 질문 chip(.chip)처럼 메인 입력창과 무관한 다른 클릭
// 요소에서도 handleUserMessage()를 호출하는데, 이런 요소는 setInput
// Disabled()의 대상이 아니라서 요청이 진행 중이어도 계속 클릭 가능한
// 상태로 남는다 — 그 상태에서 빠르게 여러 번 누르면 동일 질문이 여러
// 번 중복 전송된다(요청서 3/8절: "중복 요청이 발생하지 않는가"). 이
// 플래그로 handleUserMessage 자체를 재진입 금지시켜 어떤 UI 요소에서
// 호출되든 동일하게 막는다.
let isProcessingMessage = false;

async function handleUserMessage(rawText) {
    const text = (rawText || '').trim();
    if (!text || isProcessingMessage) return;
    isProcessingMessage = true;

    addMessage({ role: 'user', type: 'text', content: { text: text } });
    renderAll();

    const conv = getActiveConversation();

    if (isExplanationQuery(text) && conv.lastSearchResult) {
        addMessage({ role: 'assistant', type: 'text', content: { text: buildExplanationMessage(conv) } });
        renderAll();
        isProcessingMessage = false;
        return;
    }

    setInputDisabled(true);
    // 요청 시작 즉시(첫 API 호출을 걸기 전에) 단일 로딩 상태를 보여준다
    // (UX 개선 A) — Requirement Parsing처럼 첫 응답이 오기까지 시간이
    // 걸리는 구간에도 화면이 멈춘 것처럼 보이지 않게 하기 위함이다. 첫
    // 응답이 도착하는 즉시(성공/실패 모두) 지운다.
    const thinkingMsg = addMessage({ role: 'assistant', type: 'thinking', content: {} });
    renderAll();
    try {
        if (!conv.currentRequirement) {
            // 최초 메시지 — 기존 LLM 기반 전체 파싱(agent.requirement_parser.
            // parse_requirement_text)을 그대로 재사용한다.
            const data = await postJSON('/api/agent/analyze-requirement', { user_text: text });
            removeMessageById(conv, thinkingMsg.id);
            conv.currentRequirement = data.requirement;
            addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
            if (!data.validation.is_valid) {
                addMessage({ role: 'assistant', type: 'text', content: { text: buildFollowupQuestionText(data.validation) } });
            }
            renderAll();
            await runSearch(conv, conv.currentRequirement);
        } else {
            // 후속 메시지 — LLM을 다시 부르지 않고 결정론적 패치만 적용한다
            // (agent.requirement_parser.apply_conversational_patch, 요청서
            // 22절 원칙 6).
            const data = await postJSON('/api/agent/update-requirement', { current_requirement: conv.currentRequirement, message: text });
            removeMessageById(conv, thinkingMsg.id);
            conv.currentRequirement = data.requirement;
            const changedSummary = data.changed_summary || [];
            if (changedSummary.length > 0) {
                addMessage({ role: 'assistant', type: 'text', content: { text: buildRequirementChangeMessage(changedSummary) } });
                addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
            } else {
                addMessage({ role: 'assistant', type: 'text', content: { text: '이 메시지에서 반영할 새 조건을 찾지 못해 기존 요구사항으로 계속 검색하겠습니다.' } });
            }
            renderAll();
            await runSearch(conv, conv.currentRequirement);
        }
        renderAll();
    } catch (err) {
        removeMessageById(conv, thinkingMsg.id);
        addMessage({ role: 'assistant', type: 'error', content: { text: err.message } });
        renderAll();
    } finally {
        setInputDisabled(false);
        isProcessingMessage = false;
    }
}

function setInputDisabled(disabled) {
    document.getElementById('chatInput').disabled = disabled;
    document.getElementById('sendBtn').disabled = disabled;
}

// ================================================================
// 입력창 wiring
// ================================================================
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');

chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = chatInput.value;
    chatInput.value = '';
    chatInput.style.height = 'auto';
    handleUserMessage(text);
});

chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.requestSubmit();
    }
});

chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
});

// ================================================================
// 사이드바 wiring — 새 대화 / 검색 / 접기
// ================================================================
document.getElementById('newChatBtn').addEventListener('click', () => {
    // 실제 레코드는 getOrCreateActiveConversation()이 첫 메시지 전송 시점에
    // 만든다 — 여기서는 활성 대화만 비워 홈 화면으로 되돌린다(요청서 4절).
    state.activeConversationId = null;
    renderAll();
    chatInput.focus();
});

const searchToggleBtn = document.getElementById('searchToggleBtn');
const convSearchBox = document.getElementById('convSearchBox');
const convSearchInput = document.getElementById('convSearchInput');
searchToggleBtn.addEventListener('click', () => {
    const isHidden = convSearchBox.style.display === 'none';
    convSearchBox.style.display = isHidden ? 'block' : 'none';
    if (isHidden) {
        convSearchInput.focus();
    } else {
        convSearchInput.value = '';
        state.searchQuery = '';
        renderConvList();
    }
});
convSearchInput.addEventListener('input', () => {
    state.searchQuery = convSearchInput.value;
    renderConvList();
});

// ================================================================
// Sidebar / Mobile Overlay Drawer(요청서 7~11절)
// ================================================================
// 데스크톱과 모바일(640px 이하)에서 같은 `.shell.sidebar-collapsed`
// 클래스를 재사용하지만 의미가 반대다 — 데스크톱은 "접힘"(숨김),
// 모바일은 CSS 미디어쿼리에서 그 의미를 "펼침"(Drawer 열림)으로
// 뒤집어 쓴다(main.py의 해당 CSS 주석 참고). 두 화면 폭을 하나의
// 로직으로 다루기 위해 "지금 모바일 Drawer 모드인가"를 640이라는
// 숫자를 JS에 또 하드코딩하지 않고, 실제 적용된 CSS
// (position:fixed 여부)로 판단한다 — CSS 브레이크포인트가 바뀌어도
// 이 판단 로직은 그대로 맞다.
const appShellEl = document.getElementById('appShell');
const hamburgerBtnEl = document.getElementById('hamburgerBtn');
const convSidebarEl = document.getElementById('convSidebar');
const mobileBackdropEl = document.getElementById('mobileBackdrop');
const mainChatEl = document.querySelector('.main-chat');

function isMobileDrawerMode() {
    return window.getComputedStyle(convSidebarEl).position === 'fixed';
}

function isSidebarVisuallyOpen() {
    const collapsedClassPresent = appShellEl.classList.contains('sidebar-collapsed');
    return isMobileDrawerMode() ? collapsedClassPresent : !collapsedClassPresent;
}

function updateHamburgerAria() {
    hamburgerBtnEl.setAttribute('aria-expanded', String(isSidebarVisuallyOpen()));
}

// Drawer 내부에서 실제로 Tab이 도달할 수 있는 요소를 그때그때
// 동적으로 찾는다(요청서: 첫/마지막 요소를 하드코딩하지 말 것 —
// Sidebar 내부 구조가 나중에 바뀌어도 그대로 맞아야 한다). 화면에
// 실제로 보이지 않는 요소(display:none/visibility:hidden/렌더링된
// 사각형이 없는 요소, 예: 검색창이 접혀 있을 때의 #convSearchInput)는
// 제외한다.
function getFocusableElements(container) {
    const selector = 'a[href], button:not([disabled]), textarea:not([disabled]), '
        + 'input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.from(container.querySelectorAll(selector)).filter((el) => {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return el.getClientRects().length > 0;
    });
}

// Drawer가 열려 있는 동안 배경(본문) 콘텐츠를 키보드 포커스/포인터
// 상호작용/스크린리더 탐색 대상에서 제외한다(요청서 10절). Tab
// 트랩(아래)이 키보드 쪽은 이미 막아주지만, inert는 마우스/터치로
// 배경을 조작하거나 스크린리더 가상 커서로 훑는 것까지 함께
// 막아주는 표준 속성이라 이중 방어로 추가한다 — 지원하지 않는
// 브라우저에서는 그냥 조용히 무시되는 progressive enhancement라
// 별도 폴리필은 두지 않는다.
function setBackgroundInert(isInert) {
    if (mainChatEl) mainChatEl.inert = isInert;
}

function openSidebar() {
    if (isMobileDrawerMode()) {
        appShellEl.classList.add('sidebar-collapsed');
        setBackgroundInert(true);
        // Drawer가 열리면 그 안의 첫 번째 조작 가능한 요소로 포커스를
        // 옮긴다(요청서 11절 Focus 관리). 클릭을 처리하는 바로 그
        // tick에 곧바로 focus()를 부르면(동기 호출이든 rAF/
        // setTimeout(0)이든) 방금 클릭된 햄버거 버튼이 포커스를
        // 계속 붙들고 있어 조용히 무시된다(Playwright로 실측: 80ms
        // 미만은 실패, 50ms부터 안정적으로 성공) — 사람이 체감하기엔
        // 충분히 짧은 80ms만 미뤄서 그 순간을 피해간다.
        setTimeout(() => {
            const [firstFocusable] = getFocusableElements(convSidebarEl);
            if (firstFocusable) firstFocusable.focus();
        }, 80);
    } else {
        appShellEl.classList.remove('sidebar-collapsed');
    }
    updateHamburgerAria();
}

function closeSidebar() {
    if (isMobileDrawerMode()) {
        appShellEl.classList.remove('sidebar-collapsed');
        setBackgroundInert(false);
    } else {
        appShellEl.classList.add('sidebar-collapsed');
    }
    // 닫을 때는 항상 햄버거 버튼으로 포커스를 되돌린다(요청서 11절).
    hamburgerBtnEl.focus();
    updateHamburgerAria();
}

hamburgerBtnEl.addEventListener('click', () => {
    if (isSidebarVisuallyOpen()) closeSidebar(); else openSidebar();
});

// Backdrop 클릭 시 닫힘(요청서 9절) — Backdrop은 모바일 Drawer가
// 열려 있을 때만 pointer-events:auto라 실제로는 그 상태에서만
// 클릭될 수 있지만, 방어적으로 조건을 한 번 더 확인한다.
mobileBackdropEl.addEventListener('click', () => {
    if (isMobileDrawerMode() && isSidebarVisuallyOpen()) closeSidebar();
});

// Escape로 닫힘 + Tab Focus Trap(요청서 2~4절). 데스크톱에서는
// 사이드바가 기본으로 열려 있는 상태라 Escape로 갑자기 접히거나
// Tab이 트랩되면 오히려 방해가 되므로, 모바일 Drawer 모드에서
// 열려 있을 때만 반응한다 — 그 외에는 이 리스너가 아무 것도 하지
// 않아 데스크톱의 기존 Sidebar 키보드 탐색을 그대로 둔다.
document.addEventListener('keydown', (e) => {
    if (!(isMobileDrawerMode() && isSidebarVisuallyOpen())) return;

    if (e.key === 'Escape') {
        closeSidebar();
        return;
    }

    if (e.key === 'Tab') {
        const focusables = getFocusableElements(convSidebarEl);
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (e.shiftKey) {
            // 첫 번째 요소(또는 Drawer 밖 어딘가)에서 Shift+Tab -> 마지막으로.
            if (active === first || !convSidebarEl.contains(active)) {
                e.preventDefault();
                last.focus();
            }
        } else {
            // 마지막 요소(또는 Drawer 밖 어딘가)에서 Tab -> 첫 번째로.
            if (active === last || !convSidebarEl.contains(active)) {
                e.preventDefault();
                first.focus();
            }
        }
    }
});

// 화면 폭이 브레이크포인트를 넘나들 때(예: 기기 회전, 창 크기 조절)
// aria-expanded 값이 실제 표시 상태와 어긋나지 않도록 다시 계산한다.
window.addEventListener('resize', updateHamburgerAria);
updateHamburgerAria();

// ================================================================
// 대화 관리(⋯) 메뉴 — 바깥 클릭/Escape로 닫기(요청서 4절)
// ================================================================
// 메뉴 버튼/드롭다운 자신을 클릭한 경우는 각 버튼의 클릭 핸들러가
// stopPropagation()으로 이미 처리하므로, 여기까지 버블링되어 온 클릭은
// 항상 "메뉴 바깥"을 클릭한 것으로 취급해도 안전하다.
document.addEventListener('click', () => {
    closeConvMenu();
});

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    // 우선순위: 삭제 확인 모달 > 이름 변경 입력 > ⋯ 메뉴. 한 번의 Escape는
    // 그 시점에 가장 "앞에 떠 있는" 상태 하나만 닫는다.
    if (state.pendingDeleteId) {
        cancelDeleteConversation();
    } else if (state.convRenamingId) {
        cancelRenameConversation();
    } else if (state.convMenuOpenId) {
        closeConvMenu();
    }
});

// ================================================================
// 부팅 — sessionStorage에서 대화 목록을 복원한다(요청서 12절 2단계).
// 가장 최근에 갱신된 대화가 있으면 새로고침 후에도 이어서 보여준다.
// ================================================================
function boot() {
    const loaded = loadConversations();
    state.conversations = pruneInactiveConversations(loaded);
    if (state.conversations.length > 0) {
        const sorted = state.conversations.slice().sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
        state.activeConversationId = sorted[0].id;
    } else if (loaded.length > 0) {
        // 비활성 초기화로 목록을 비웠다면 sessionStorage에도 즉시 반영한다.
        saveConversations();
    }
    renderAll();
}
boot();
