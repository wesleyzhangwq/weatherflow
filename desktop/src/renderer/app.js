/**
 * WeatherFlow Desktop Pet — Renderer logic.
 *
 * Per weatherflow-architecture-v2.md:
 * - M2.2: Character mood maps to 6 rhythm labels
 * - M2.3: Click-to-chat + calibrated proactivity (subtle hint animation)
 */

// --- Config ---
const WF_API_BASE = "http://127.0.0.1:8765";
const POLL_INTERVAL_MS = 30000; // Poll for latest hypothesis every 30s

// --- Mood mapping (M2.2) ---
const MOOD_MAP = {
  Flow: { emoji: "🌟", mood: "flow" },
  Recovery: { emoji: "😴", mood: "recovery" },
  Steady: { emoji: "😊", mood: "steady" },
  Overload: { emoji: "😰", mood: "overload" },
  Blocked: { emoji: "😤", mood: "blocked" },
  Fragmented: { emoji: "😵‍💫", mood: "fragmented" },
};

const DEFAULT_MOOD = { emoji: "😊", mood: "steady" };

// --- State ---
let currentLabel = null;
let chatOpen = false;
let proactivityEnabled = true;

// --- DOM refs ---
const petContainer = document.getElementById("pet-container");
const petCharacter = document.getElementById("pet-character");
const petFace = document.getElementById("pet-face");
const petLabel = document.getElementById("pet-label");
const chatPanel = document.getElementById("chat-panel");
const chatMessages = document.getElementById("chat-messages");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const chatClose = document.getElementById("chat-close");

// --- Character mood update (M2.2) ---
function updateMood(label) {
  const config = MOOD_MAP[label] || DEFAULT_MOOD;
  petFace.textContent = config.emoji;
  petCharacter.setAttribute("data-mood", config.mood);
  petLabel.textContent = label || "Steady";

  // Calibrated proactivity hint (M2.3): subtle glow when hypothesis changes
  if (label && label !== currentLabel && proactivityEnabled) {
    petCharacter.classList.add("hint-active");
    setTimeout(() => petCharacter.classList.remove("hint-active"), 2000);
  }
  currentLabel = label;
}

// --- Poll for latest hypothesis (M2.2 SSE/poll subscription) ---
async function pollHypothesis() {
  try {
    const resp = await fetch(`${WF_API_BASE}/api/hypotheses?limit=1`);
    if (!resp.ok) return;
    const cards = await resp.json();
    if (cards.length > 0) {
      updateMood(cards[0].label);
    }
  } catch (err) {
    // Backend not available — stay in default mood
    console.debug("Hypothesis poll failed:", err.message);
  }
}

// --- Click-to-chat (M2.3) ---
petCharacter.addEventListener("click", () => {
  chatOpen = !chatOpen;
  chatPanel.classList.toggle("hidden", !chatOpen);
  if (chatOpen) {
    chatInput.focus();
    if (window.wfBridge) {
      window.wfBridge.toggleChat(true);
    }
  } else {
    if (window.wfBridge) {
      window.wfBridge.toggleChat(false);
    }
  }
});

chatClose.addEventListener("click", () => {
  chatOpen = false;
  chatPanel.classList.add("hidden");
  if (window.wfBridge) {
    window.wfBridge.toggleChat(false);
  }
});

// --- Chat messaging ---
let conversationId = null;

function ensureConversationId() {
  if (!conversationId) {
    conversationId = "desktop_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
  }
  return conversationId;
}

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = content;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  appendMessage("user", text);

  try {
    const resp = await fetch(`${WF_API_BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        conversation_id: ensureConversationId(),
      }),
    });

    if (!resp.ok) {
      appendMessage("assistant", "（连接失败）");
      return;
    }

    // Parse SSE stream
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.content) {
              // For final_answer or reasoning_step
              appendMessage("assistant", data.content);
            }
          } catch {
            // ignore parse errors in SSE
          }
        }
      }
    }
  } catch (err) {
    appendMessage("assistant", `（错误: ${err.message}）`);
  }
}

chatSend.addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

// --- IPC bridge (Electron) ---
if (window.wfBridge) {
  window.wfBridge.onHypothesisUpdate((data) => {
    if (data.label) updateMood(data.label);
  });

  window.wfBridge.onOpenChat(() => {
    chatOpen = true;
    chatPanel.classList.remove("hidden");
    chatInput.focus();
  });
}

// --- Init ---
pollHypothesis();
setInterval(pollHypothesis, POLL_INTERVAL_MS);
