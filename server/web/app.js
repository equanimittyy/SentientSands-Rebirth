const show = (id, text) => {
  document.getElementById(id).textContent = text;
};

try {
  const response = await fetch("/settings");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const settings = await response.json();
  show("server-status", "Running");
  show("campaign", settings.current_campaign);
  show("model", settings.current);
} catch (error) {
  show("server-status", `Not responding (${error.message})`);
}
