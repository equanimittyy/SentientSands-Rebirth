import { getJson, sendJson, showMessage } from "./api.js";

const form = document.getElementById("profile-form");
const message = document.getElementById("profile-message");

async function save(event) {
  event.preventDefault();
  try {
    await sendJson("POST", "/player_profile", {
      character_bio: form.elements.character_bio.value,
      player_faction: form.elements.player_faction.value,
    });
    showMessage(message, "Saved. The next prompt uses the new text.");
  } catch (error) {
    showMessage(message, `Save failed: ${error.message}`, true);
  }
}

export async function initProfile() {
  try {
    const profile = await getJson("/player_profile");
    form.elements.character_bio.value = profile.character_bio;
    form.elements.player_faction.value = profile.player_faction;
    form.addEventListener("submit", save);
  } catch (error) {
    showMessage(message, `Could not load the player profile: ${error.message}`, true);
  }
}
