// BusMate AI Web App Script

let callSeconds = 0;
let callTimerInterval = null;
let currentLanguage = 'en';
let recognition = null;
let isListening = false;

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
  startCallTimer();
  loadStopsTable();
  autoSearch();
  initSpeechRecognition();
});

// Call timer
function startCallTimer() {
  const timerElem = document.getElementById('call-timer');
  callTimerInterval = setInterval(() => {
    callSeconds++;
    const mins = String(Math.floor(callSeconds / 60)).padStart(2, '0');
    const secs = String(callSeconds % 60).padStart(2, '0');
    if (timerElem) timerElem.textContent = `${mins}:${secs}`;
  }, 1000);
}

// Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  event.target.classList.add('active');
  const target = document.getElementById(`tab-${tabId}`);
  if (target) target.classList.add('active');
}

// Append Chat Message
function appendMessage(sender, text, isAgent = false) {
  const container = document.getElementById('chat-messages');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${isAgent ? 'agent' : 'caller'}`;

  const label = document.createElement('span');
  label.className = 'speaker-label';
  label.textContent = isAgent ? 'BusMate AI:' : 'Caller:';

  const p = document.createElement('p');
  p.textContent = text;

  msgDiv.appendChild(label);
  msgDiv.appendChild(p);
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

// Speak text using Web Speech API
function speakText(text, lang = 'en') {
  if (!('speechSynthesis' in window)) return;

  // Cancel prior speech
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  if (lang === 'te') {
    utterance.lang = 'te-IN';
  } else if (lang === 'hi') {
    utterance.lang = 'hi-IN';
  } else {
    utterance.lang = 'en-IN';
  }
  utterance.rate = 1.0;
  window.speechSynthesis.speak(utterance);
}

// Handle Form Submission
async function handleSend(e) {
  if (e) e.preventDefault();
  const input = document.getElementById('user-input');
  if (!input) return;

  const query = input.value.trim();
  if (!query) return;

  input.value = '';
  appendMessage('Caller', query, false);

  try {
    const res = await fetch('/api/simulate-call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query, session_id: 'web-session-1' })
    });

    if (!res.ok) throw new Error('Network error');

    const data = await res.json();
    appendMessage('BusMate AI', data.response, true);

    // Update detected language pill
    const pill = document.getElementById('detected-lang-pill');
    if (pill) {
      const langNames = { en: 'English', te: 'తెలుగు (Telugu)', hi: 'हिंदी (Hindi)' };
      pill.textContent = langNames[data.language] || data.language;
    }

    // Speak response
    speakText(data.response, data.language);

    // If a route was detected, update search tab too
    if (data.detected_route) {
      renderSingleRouteResult(data.detected_route);
    }
  } catch (err) {
    appendMessage('BusMate AI', 'Sorry, I had trouble processing your request. Please try again.', true);
  }
}

// Quick Prompt Handler
function sendPrompt(text) {
  const input = document.getElementById('user-input');
  if (input) {
    input.value = text;
    handleSend();
  }
}

// Voice Input using SpeechRecognition
function initSpeechRecognition() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    const mic = document.getElementById('mic-btn');
    if (mic) mic.style.display = 'none';
    return;
  }

  recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-IN';

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const input = document.getElementById('user-input');
    if (input) {
      input.value = transcript;
      handleSend();
    }
  };

  recognition.onend = () => {
    isListening = false;
    const mic = document.getElementById('mic-btn');
    if (mic) mic.classList.remove('listening');
  };

  recognition.onerror = () => {
    isListening = false;
    const mic = document.getElementById('mic-btn');
    if (mic) mic.classList.remove('listening');
  };
}

function toggleVoiceInput() {
  if (!recognition) return;
  const mic = document.getElementById('mic-btn');

  if (isListening) {
    recognition.stop();
    isListening = false;
    if (mic) mic.classList.remove('listening');
  } else {
    try {
      recognition.start();
      isListening = true;
      if (mic) mic.classList.add('listening');
    } catch (e) {
      console.warn(e);
    }
  }
}

// Auto Search in Explorer
async function autoSearch() {
  const src = document.getElementById('search-source').value;
  const dst = document.getElementById('search-dest').value;
  const container = document.getElementById('search-results');

  if (!src || !dst || src === dst) {
    container.innerHTML = `<div class="result-placeholder"><p>Please select two different stops to view routes.</p></div>`;
    return;
  }

  container.innerHTML = `<p style="color: #64748b;">Searching mock transit routes...</p>`;

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: src, destination: dst })
    });

    const routes = await res.json();
    if (!routes || routes.length === 0) {
      container.innerHTML = `<div class="result-placeholder"><p>No route found between selected stops.</p></div>`;
      return;
    }

    container.innerHTML = '';
    routes.forEach(route => {
      container.appendChild(createRouteElement(route));
    });
  } catch (e) {
    container.innerHTML = `<div class="result-placeholder"><p>Error searching routes.</p></div>`;
  }
}

// Create Route Card Element
function createRouteElement(route) {
  const card = document.createElement('div');
  card.className = 'route-item';

  const isDirect = route.is_direct;
  const legs = route.legs;

  let headerHtml = '';
  if (isDirect) {
    const leg = legs[0];
    headerHtml = `
      <div class="route-item-header">
        <span class="route-num-badge">${leg.route_number}</span>
        <span class="route-type-badge">${leg.service_type}</span>
      </div>
      <div class="route-meta">
        <span>⏱️ Duration: <strong>${route.total_duration_minutes} mins</strong></span>
        <span>💵 Fare: <strong>₹${route.total_fare_inr}</strong></span>
        <span>🟢 Direct Bus</span>
      </div>
      <div class="timeline">
        <div class="timeline-stop"><strong>Board:</strong> ${leg.board_stop_name} (${leg.board_stop_localized.te || ''})</div>
        ${leg.intermediate_stops.length > 0 ? `<div class="timeline-stop" style="color: #64748b; font-size: 0.8rem;">Via: ${leg.intermediate_stops.join(' ➔ ')}</div>` : ''}
        <div class="timeline-stop"><strong>Alight:</strong> ${leg.alight_stop_name} (${leg.alight_stop_localized.te || ''})</div>
      </div>
    `;
  } else {
    const leg1 = legs[0];
    const leg2 = legs[1];
    headerHtml = `
      <div class="route-item-header">
        <div>
          <span class="route-num-badge">${leg1.route_number}</span> + 
          <span class="route-num-badge">${leg2.route_number}</span>
        </div>
        <span class="route-type-badge">1 Transfer Journey</span>
      </div>
      <div class="route-meta">
        <span>⏱️ Duration: <strong>${route.total_duration_minutes} mins</strong></span>
        <span>💵 Fare: <strong>₹${route.total_fare_inr}</strong></span>
        <span>🔄 1 Transfer</span>
      </div>
      <div class="timeline">
        <div class="timeline-stop"><strong>Board Leg 1:</strong> ${leg1.board_stop_name} on <strong>${leg1.route_number}</strong></div>
        <div class="timeline-stop"><strong>Transfer At:</strong> ${leg1.alight_stop_name}</div>
        <div class="timeline-stop"><strong>Board Leg 2:</strong> ${leg2.board_stop_name} on <strong>${leg2.route_number}</strong></div>
        <div class="timeline-stop"><strong>Destination:</strong> ${leg2.alight_stop_name}</div>
      </div>
      <div class="transfer-alert">
        ℹ️ Change buses at <strong>${leg1.alight_stop_name}</strong> to catch <strong>${leg2.route_number}</strong>.
      </div>
    `;
  }

  // Multilingual speech summary snippet
  const summaryBox = `
    <div style="margin-top: 12px; padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 0.82rem; border-left: 3px solid #3b82f6;">
      <div><strong>Telugu:</strong> ${route.summary.te || ''}</div>
      <div style="margin-top: 4px;"><strong>Hindi:</strong> ${route.summary.hi || ''}</div>
    </div>
  `;

  card.innerHTML = headerHtml + summaryBox;
  return card;
}

// Render Single Route Result
function renderSingleRouteResult(routeData) {
  const container = document.getElementById('search-results');
  if (!container) return;
  container.innerHTML = '';
  container.appendChild(createRouteElement(routeData));
}

// Load Stops into Table
async function loadStopsTable() {
  const tbody = document.getElementById('stops-tbody');
  if (!tbody) return;

  try {
    const res = await fetch('/api/stops');
    const stops = await res.json();

    tbody.innerHTML = '';
    stops.forEach(s => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><code>${s.id}</code></td>
        <td><strong>${s.name}</strong></td>
        <td>${s.supported_languages.te || '-'}</td>
        <td>${s.supported_languages.hi || '-'}</td>
        <td style="color: #64748b;">${s.locality || '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error('Error loading stops', e);
  }
}
