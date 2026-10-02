export async function getJson(url) {
  return readJson(await fetch(url));
}

export async function sendJson(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson(response);
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.errors?.join(" ") || data.message || data.error;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data;
}

export function showMessage(element, text, isError = false) {
  element.textContent = text;
  element.classList.toggle("error", isError);
}
