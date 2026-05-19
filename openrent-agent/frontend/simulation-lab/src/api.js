const API_BASE =
  import.meta.env.VITE_SIMULATION_API_BASE || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        message = typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail);
      }
    } catch {
      // Leave the default message intact when the response is not JSON.
    }
    throw new Error(message);
  }

  return response.json();
}

export function runSimulation(payload) {
  return request("/simulation/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchSessions() {
  return request("/simulation/sessions");
}

export function fetchSession(sessionId) {
  return request(`/simulation/sessions/${sessionId}`);
}

export function fetchResults(sessionId) {
  return request(`/simulation/results/${sessionId}`);
}

export function fetchConversationDesigns() {
  return request("/simulation/conversation-designs");
}

export function fetchScenarios() {
  return request("/simulation/scenarios");
}

export function compareDesigns(payload) {
  return request("/simulation/compare-designs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startInteractiveSession(payload) {
  return request("/simulation/interactive/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendInteractiveMessage(sessionId, message) {
  return request(`/simulation/interactive/${sessionId}/message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function fetchInteractiveSession(sessionId) {
  return request(`/simulation/interactive/${sessionId}`);
}
