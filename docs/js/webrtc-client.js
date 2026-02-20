/**
 * Pipecat Crush Quest - Daily Client
 * Connects to the Pipecat bot via Vercel serverless function -> Pipecat Cloud
 */

// Import Daily.co JavaScript SDK
import DailyIframe from 'https://esm.sh/@daily-co/daily-js@0.84.0';

// Configuration - uses relative path for Vercel serverless function
const BOT_SERVER_URL = window.CRUSH_QUEST_BOT_URL || '';

// State
let callObject = null;
let currentCallNumber = null;
let ringingInterval = null;
let audioContext = null;

/**
 * Play a classic phone ring tone using Web Audio API
 */
function startRinging() {
  if (ringingInterval) return;

  try {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();

    function playRingTone() {
      if (!audioContext) return;

      const now = audioContext.currentTime;
      const osc1 = audioContext.createOscillator();
      const osc2 = audioContext.createOscillator();
      const gainNode = audioContext.createGain();

      osc1.type = 'sine';
      osc2.type = 'sine';
      osc1.frequency.value = 440;
      osc2.frequency.value = 480;

      osc1.connect(gainNode);
      osc2.connect(gainNode);
      gainNode.connect(audioContext.destination);

      gainNode.gain.setValueAtTime(0.15, now);
      gainNode.gain.setValueAtTime(0, now + 0.4);
      gainNode.gain.setValueAtTime(0.15, now + 0.6);
      gainNode.gain.setValueAtTime(0, now + 1.0);

      osc1.start(now);
      osc2.start(now);
      osc1.stop(now + 1.0);
      osc2.stop(now + 1.0);
    }

    playRingTone();
    ringingInterval = setInterval(playRingTone, 3000);
  } catch (e) {
    console.warn('Could not create ring tone:', e);
  }
}

function stopRinging() {
  if (ringingInterval) {
    clearInterval(ringingInterval);
    ringingInterval = null;
  }
  if (audioContext) {
    audioContext.close().catch(() => {});
    audioContext = null;
  }
}

/**
 * Get or generate a caller ID for game logic
 */
function getCallerId() {
  const input = document.getElementById('caller-id-input');
  if (input && input.value.trim()) {
    const callerId = input.value.trim();
    localStorage.setItem('crushQuestCallerId', callerId);
    return callerId;
  }

  let callerId = localStorage.getItem('crushQuestCallerId');
  if (!callerId) {
    const randomNum = Math.floor(Math.random() * 9000000) + 1000000;
    callerId = `+1555${randomNum}`;
    localStorage.setItem('crushQuestCallerId', callerId);
  }

  if (input) {
    input.value = callerId;
  }

  return callerId;
}

/**
 * Update the UI to show connection status
 */
function updateStatus(status, message) {
  const statusEl = document.getElementById('call-status');
  const statusText = document.getElementById('call-status-text');

  if (statusEl) {
    statusEl.className = `call-status call-status-${status}`;
    statusEl.style.display = 'block';
  }

  if (statusText) {
    statusText.textContent = message;
  }

  const callButtons = document.querySelectorAll('.call-button');
  callButtons.forEach(btn => {
    if (status === 'connected' || status === 'connecting') {
      btn.disabled = true;
      btn.classList.add('disabled');
    } else {
      btn.disabled = false;
      btn.classList.remove('disabled');
    }
  });

  const hangupBtn = document.getElementById('hangup-button');
  if (hangupBtn) {
    hangupBtn.style.display = (status === 'connected') ? 'block' : 'none';
  }
}

/**
 * Start a call to a crush
 */
async function startCall(toNumber, crushName) {
  if (callObject) {
    console.warn('Already in a call');
    return;
  }

  const fromNumber = getCallerId();
  currentCallNumber = toNumber;

  console.log(`Starting call to ${crushName} (${toNumber}) from ${fromNumber}`);
  updateStatus('connecting', `Calling ${crushName}...`);
  startRinging();

  try {
    const endpoint = `${BOT_SERVER_URL}/api/connect`;
    console.log('Requesting room from:', endpoint);

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        to_number: toNumber,
        from_number: fromNumber
      })
    });

    if (!response.ok) {
      throw new Error(`Server error: ${response.status}`);
    }

    const { room_url, token } = await response.json();
    console.log('Got room URL:', room_url);

    callObject = DailyIframe.createCallObject({
      audioSource: true,
      videoSource: false,
    });

    callObject.on('joined-meeting', () => {
      console.log('Joined Daily room');
      stopRinging();
      updateStatus('connected', `Connected to ${crushName}`);
    });

    callObject.on('left-meeting', () => {
      console.log('Left Daily room');
      updateStatus('disconnected', 'Call ended');
      cleanup();
    });

    callObject.on('error', (error) => {
      console.error('Daily error:', error);
      updateStatus('error', `Error: ${error.errorMsg || 'Connection failed'}`);
      cleanup();
    });

    callObject.on('participant-joined', (event) => {
      console.log('Participant joined:', event.participant);
    });

    callObject.on('participant-left', (event) => {
      console.log('Participant left:', event.participant);
      if (!event.participant.local) {
        console.log('Bot left the room, ending call');
        updateStatus('disconnected', 'Call ended');
        endCall();
      }
    });

    callObject.on('track-started', (event) => {
      if (event.track.kind === 'audio' && !event.participant.local) {
        console.log('Remote audio track started');
        const audioEl = document.getElementById('bot-audio');
        if (audioEl) {
          const stream = new MediaStream([event.track]);
          audioEl.srcObject = stream;
          audioEl.play().catch(e => console.warn('Audio autoplay blocked:', e));
        }
      }
    });

    await callObject.join({ url: room_url, token });

  } catch (error) {
    console.error('Failed to start call:', error);
    updateStatus('error', `Failed to connect: ${error.message}`);
    cleanup();
  }
}

/**
 * End the current call
 */
async function endCall() {
  if (callObject) {
    console.log('Ending call');
    updateStatus('disconnecting', 'Hanging up...');
    const call = callObject;
    callObject = null;
    try {
      await call.leave();
      await call.destroy();
    } catch (error) {
      console.error('Error disconnecting:', error);
    }
    cleanup();
  }
}

/**
 * Clean up after a call
 */
function cleanup() {
  stopRinging();
  callObject = null;
  currentCallNumber = null;

  const audioEl = document.getElementById('bot-audio');
  if (audioEl) {
    audioEl.srcObject = null;
  }

  setTimeout(() => {
    const statusEl = document.getElementById('call-status');
    if (statusEl && !callObject) {
      statusEl.style.display = 'none';
    }
  }, 3000);
}

/**
 * Initialize the client UI
 */
function initializeUI() {
  getCallerId();

  document.querySelectorAll('.call-button').forEach(btn => {
    btn.addEventListener('click', (e) => {
      console.log('Call button clicked');
      const toNumber = btn.dataset.number;
      const crushName = btn.dataset.name;
      if (toNumber && crushName) {
        startCall(toNumber, crushName);
      }
    });
  });

  const hangupBtn = document.getElementById('hangup-button');
  if (hangupBtn) {
    hangupBtn.addEventListener('click', endCall);
  }

  const callerInput = document.getElementById('caller-id-input');
  if (callerInput) {
    callerInput.addEventListener('change', () => {
      localStorage.setItem('crushQuestCallerId', callerInput.value.trim());
    });
  }
}

window.CrushQuest = {
  startCall,
  endCall,
  getCallerId,
  initializeUI
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeUI);
} else {
  initializeUI();
}
