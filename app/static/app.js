"use strict";
const html = document.documentElement;
const themeButton = document.getElementById("theme-toggle");
function applyTheme(theme) {
  html.dataset.bsTheme = theme;
  if (themeButton) themeButton.textContent = theme === "dark" ? "Light mode" : "Dark mode";
}
try { applyTheme(localStorage.getItem("theme") === "light" ? "light" : "dark"); } catch { applyTheme("dark"); }
themeButton?.addEventListener("click", () => {
  const theme = html.dataset.bsTheme === "dark" ? "light" : "dark";
  applyTheme(theme);
  try { localStorage.setItem("theme", theme); } catch { /* Preference remains effective for this page. */ }
});
const collectButton = document.getElementById("collect-all");
collectButton?.addEventListener("click", async () => {
  const message = document.getElementById("collection-message");
  collectButton.disabled = true;
  message.textContent = "Starting collection…";
  try {
    const response = await fetch("/api/scrape", {method:"POST", headers:{"X-CSRF-Token":document.querySelector('meta[name="csrf-token"]').content}});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Collection could not start.");
    for (let attempt = 0; attempt < 150; attempt++) {
      const statusResponse = await fetch(data.status_url);
      if (!statusResponse.ok) throw new Error("Could not read collection status.");
      const status = await statusResponse.json();
      if (status.run.outcome !== "RUNNING") {
        message.textContent = `${status.run.outcome}: ${status.run.records_discovered} found, ${status.run.records_added} added, ${status.run.records_updated} updated. ${status.run.errors || "Reload to see the run history."}`;
        return;
      }
      message.textContent = "Collection is running. You can continue reviewing opportunities.";
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    message.textContent = `Collection continues. Check run ${data.run_id} in the run history.`;
  } catch (error) { message.textContent = error.message; }
  finally { collectButton.disabled = false; }
});
