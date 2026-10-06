const storageKey = 'gemini-chat-session';
let sessionId = sessionStorage.getItem(storageKey);
const messages = document.querySelector('#messages');
const status = document.querySelector('#status');
const input = document.querySelector('#message');
const send = document.querySelector('#send');
const newChat = document.querySelector('#new-chat');
const applyScoring = document.querySelector('#apply-scoring');
const scoringStatus = document.querySelector('#scoring-status');
const scoringStorageKey = 'draft-lab-confirmed-scoring';
let confirmedScoring = null;
let scoringPending = false;
try {
  const saved = JSON.parse(sessionStorage.getItem(scoringStorageKey));
  if (saved && typeof saved.weights === 'object' && saved.weights !== null) {
    confirmedScoring = saved.weights;
    scoringPending = Boolean(saved.pending);
    for (const field of document.querySelectorAll('[data-stat]')) {
      if (Object.hasOwn(confirmedScoring, field.dataset.stat)) field.value = confirmedScoring[field.dataset.stat];
    }
    scoringStatus.textContent = 'Confirmed scoring restored. Ask your question in chat.';
  }
} catch { sessionStorage.removeItem(scoringStorageKey); }

function saveScoring() {
  if (confirmedScoring) sessionStorage.setItem(scoringStorageKey, JSON.stringify({weights: confirmedScoring, pending: scoringPending}));
  if (typeof activeChat !== 'undefined' && activeChat) {
    activeChat.scoring = confirmedScoring;
    activeChat.scoringPending = scoringPending;
    saveChats();
  }
}
let busy = false;

const chatsKey = 'draft-lab-chat-tabs-v1';
const tabs = document.querySelector('#chat-tabs');
const defaultFields = Object.fromEntries([...document.querySelectorAll('[data-stat]')].map(f => [f.dataset.stat, f.defaultValue]));
let chatState;
try { chatState = JSON.parse(sessionStorage.getItem(chatsKey)); } catch {}
if (!chatState || !Array.isArray(chatState.chats) || !chatState.chats.length) {
  const first = {id: crypto.randomUUID(), title: 'New chat', sessionId,
    scoring: confirmedScoring, scoringPending, entries: [], draft: ''};
  chatState = {activeId: first.id, chats: [first]};
}
let activeChat = chatState.chats.find(c => c.id === chatState.activeId) || chatState.chats[0];
function saveChats() {
  chatState.activeId = activeChat.id;
  try { sessionStorage.setItem(chatsKey, JSON.stringify(chatState)); }
  catch { status.textContent = 'Browser storage is full. Keep this page open to retain your chat tabs.'; }
}
function renderTabs() {
  tabs.replaceChildren();
  for (const chat of chatState.chats) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chat-tab' + (chat.id === activeChat.id ? ' active' : '');
    button.textContent = chat.title;
    button.title = chat.title;
    button.setAttribute('aria-pressed', String(chat.id === activeChat.id));
    button.disabled = busy;
    button.addEventListener('click', () => { if (!busy) { switchChat(chat); restoreHistory(); } });
    tabs.append(button);
  }
}
function switchChat(chat) {
  activeChat.draft = input.value;
  activeChat = chat;
  sessionId = chat.sessionId;
  confirmedScoring = chat.scoring || null;
  scoringPending = Boolean(chat.scoringPending);
  for (const field of document.querySelectorAll('[data-stat]')) {
    field.value = confirmedScoring?.[field.dataset.stat] ?? defaultFields[field.dataset.stat];
  }
  scoringStatus.textContent = confirmedScoring ? 'Confirmed scoring for this chat.' : 'Confirm your league scoring, then ask your fantasy questions in chat.';
  messages.replaceChildren();
  for (const entry of chat.entries) addMessage(entry.role, entry.content, entry.tool_calls, false);
  input.value = chat.draft || '';
  status.textContent = '';
  if (sessionId) sessionStorage.setItem(storageKey, sessionId);
  else sessionStorage.removeItem(storageKey);
  saveChats();
  renderTabs();
  input.focus();
}
input.addEventListener('input', () => { activeChat.draft = input.value; saveChats(); });

function addToolCalls(parent, calls) {
  for (const call of calls || []) {
    const details = document.createElement('details');
    details.className = 'tool-call';
    const summary = document.createElement('summary');
    summary.textContent = `${call.result?.ok === false ? '⚠' : '↳'} Tool: ${call.name}`;
    details.append(summary);
    if (call.result?.ok === false) {
      const explanation = document.createElement('p');
      explanation.textContent = `${call.result.message} ${call.result.next_step}`;
      details.append(explanation);
    }
    for (const [label, value] of [['Arguments', call.args], ['Result', call.result]]) {
      const heading = document.createElement('strong');
      heading.textContent = label;
      const pre = document.createElement('pre');
      pre.textContent = JSON.stringify(value, null, 2);
      details.append(heading, pre);
    }
    parent.append(details);
  }
}

function renderAnswer(content) {
  const container = document.createElement('div');
  container.className = 'answer';
  // Render a small Markdown subset using DOM text nodes, never raw HTML.
  for (const line of content.split('\n')) {
    if (!line.trim()) continue;
    if (/^---+$/.test(line.trim())) {
      container.append(document.createElement('hr'));
      continue;
    }
    const isHeading = /^#{1,6}\s/.test(line);
    const element = document.createElement(isHeading ? 'h3' : 'p');
    let text = line.replace(/^#{1,6}\s+/, '').replace(/^>\s*/, '');
    text = text.replace(/^\s*[*-]\s+/, '• ');
    for (const part of text.split(/(\*\*[^*]+\*\*)/g)) {
      if (part.startsWith('**') && part.endsWith('**')) {
        const strong = document.createElement('strong');
        strong.textContent = part.slice(2, -2);
        element.append(strong);
      } else {
        element.append(document.createTextNode(part));
      }
    }
    container.append(element);
  }
  return container;
}

function addMessage(role, content, calls = [], remember = true) {
  if (remember) {
    activeChat.entries.push({role, content, tool_calls: calls});
    saveChats();
  }
  const article = document.createElement('article');
  article.className = role;
  const label = document.createElement('strong');
  label.textContent = role === 'user' ? 'You' : 'Your Fantasy Agent';
  const body = role === 'assistant' ? renderAnswer(content) : document.createElement('p');
  if (role !== 'assistant') body.textContent = content;
  article.append(label, body);
  if (role === 'assistant') {
    for (const call of calls) {
      if (call.name === 'analyze_buy_low_sell_high' && call.result?.ok && window.createFantasyTrend) {
        const chart = window.createFantasyTrend(call.result);
        if (chart) article.append(chart);
      }
    }
  }
  addToolCalls(article, calls);
  messages.append(article);
  article.scrollIntoView({ block: 'nearest' });
  return article;
}

function setBusy(value) {
  busy = value;
  for (const element of [send, newChat, applyScoring, ...document.querySelectorAll('[data-stat]')]) element.disabled = value;
  renderTabs();
}

newChat.addEventListener('click', () => {
  if (busy) return;
  const chat = {id: crypto.randomUUID(), title: 'New chat', sessionId: null,
    scoring: confirmedScoring ? {...confirmedScoring} : null,
    scoringPending: Boolean(confirmedScoring), entries: [], draft: ''};
  chatState.chats.push(chat);
  switchChat(chat);
});

function readScoringRules() {
  const weights = {};
  for (const field of document.querySelectorAll('[data-stat]')) {
    if (!field.checkValidity() || field.value === '') {
      field.reportValidity();
      status.textContent = 'Enter a valid number for every scoring field.';
      return;
    }
    weights[field.dataset.stat] = Number(field.value);
  }
  if (Object.values(weights).every(value => value === 0)) {
    status.textContent = 'At least one scoring weight must be nonzero.';
    return;
  }
  return weights;
}

for (const field of document.querySelectorAll('[data-stat]')) {
  field.addEventListener('input', () => {
    scoringStatus.textContent = 'Unconfirmed changes. Press Confirm Changes to apply them.';
  });
}

applyScoring.addEventListener('click', () => {
  const weights = readScoringRules();
  if (!weights) return;
  confirmedScoring = weights;
  scoringPending = true;
  saveScoring();
  scoringStatus.textContent = 'Scoring confirmed. These rules will apply to your next chat question.';
  input.focus();
});

input.addEventListener('keydown', (event) => {
  // Enter during Chinese/Japanese IME composition must only confirm the text.
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!busy) document.querySelector('#chat-form').requestSubmit();
  }
});

document.querySelector('#chat-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || busy) return;
  if (!activeChat.entries.some(e => e.role === 'user')) {
    activeChat.title = message.length > 32 ? message.slice(0, 32) + '…' : message;
  }
  const sentMessage = addMessage('user', message);
  input.value = '';
  activeChat.draft = '';
  saveChats();
  const pendingReply = addMessage('assistant', 'Thinking…', [], false);
  pendingReply.classList.add('pending-reply');
  pendingReply.setAttribute('aria-live', 'polite');
  setBusy(true);
  status.textContent = '';
  input.focus();
  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId, ...(scoringPending ? {scoring_weights: confirmedScoring} : {}) }),
    });
    const data = await response.json();
    pendingReply.remove();
    if (data.session_id) {
      sessionId = data.session_id;
      activeChat.sessionId = sessionId;
      saveChats();
      sessionStorage.setItem(storageKey, sessionId);
    }
    if (!response.ok) {
      if (data.tool_calls?.length) addMessage('assistant', 'The request failed after these tool calls. Your previous history was kept.', data.tool_calls);
      throw new Error(data.response || 'Chat request failed.');
    }
    if (scoringPending) {
      scoringPending = false;
      saveScoring();
      scoringStatus.textContent = 'Confirmed scoring sent. Continue in chat, or confirm new UI changes.';
    }
    addMessage('assistant', data.response, data.tool_calls);
    status.textContent = '';
  } catch (error) {
    pendingReply.remove();
    sentMessage.classList.add('failed-message');
    addMessage('assistant', `${error.message || 'Connection failed.'} Your message was kept here. Please send it again to retry.`);
    status.textContent = 'Message failed. Your earlier conversation is unchanged.';
  } finally {
    pendingReply.remove();
    setBusy(false);
    input.focus();
  }
});

async function restoreHistory() {
  if (!sessionId) return;
  setBusy(true);
  status.textContent = 'Restoring conversation…';
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`);
    if (response.status === 404) {
      sessionId = null;
      activeChat.sessionId = null;
      sessionStorage.removeItem(storageKey);
      scoringPending = Boolean(confirmedScoring);
      saveScoring();
      status.textContent = 'Saved messages are still visible. Server memory ended; your next message starts a new session.';
      return;
    }
    if (!response.ok) throw new Error('Could not restore this chat. Refresh to retry.');
    const data = await response.json();
    if (!activeChat.entries.length) {
      for (const message of data.messages) addMessage(message.role, message.content, message.tool_calls);
    }
    status.textContent = '';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    setBusy(false);
  }
}
input.value = activeChat.draft || '';
switchChat(activeChat);
restoreHistory();
