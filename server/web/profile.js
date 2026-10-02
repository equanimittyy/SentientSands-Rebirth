import { getJson, sendJson, showMessage } from "./api.js";

const form = document.getElementById("profile-form");
const message = document.getElementById("profile-message");
let campaign = null;

export const profileCampaign = () => campaign;

async function save(event) {
  event.preventDefault();
  try {
    await sendJson("POST", "/player_profile", {
      campaign,
      character_bio: form.elements.character_bio.value,
      player_faction: form.elements.player_faction.value,
    });
    showMessage(message, "Saved. The next prompt uses the new text.");
  } catch (error) {
    showMessage(message, `Save failed: ${error.message}`, true);
  }
}

export async function loadProfile() {
  try {
    const profile = await getJson("/player_profile");
    form.elements.character_bio.value = profile.character_bio;
    form.elements.player_faction.value = profile.player_faction;
    const switched = campaign !== null && campaign !== profile.campaign;
    showMessage(message, switched ? `The active campaign changed to ${profile.campaign}, so this page now shows its profile.` : "");
    campaign = profile.campaign;
    return true;
  } catch (error) {
    showMessage(message, `Could not load the player profile: ${error.message}`, true);
    return false;
  }
}

form.addEventListener("submit", save);
