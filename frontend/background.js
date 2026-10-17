const BRIGHTSPACE_URL = /^https?:\/\/brightspace\.carleton\.ca\//i;

function enableActionClickPanel() {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error("setPanelBehavior failed:", err));
}

chrome.runtime.onInstalled.addListener(enableActionClickPanel);
enableActionClickPanel();

async function sendToTab(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (err) {
    // Tabs opened before the extension was installed/reloaded have no content script yet.
    if (!/Receiving end does not exist|Could not establish connection/i.test(String(err && err.message))) throw err;
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    return chrome.tabs.sendMessage(tabId, message);
  }
}

/** Ask the content script in the active tab to scrape whatever Brightspace page is open. */
async function scrapeActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab || !tab.id || !BRIGHTSPACE_URL.test(tab.url || "")) return { ok: false, notBrightspace: true };
  const data = await sendToTab(tab.id, { type: "lucid:scrape-page" });
  if (!data || !data.ok) return { ok: false, error: (data && data.error) || "The Brightspace page did not respond." };
  return { ok: true, data };
}

// The side panel can't always reach tabs directly; it asks the service worker to relay.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "lucid:scrape") return false;
  scrapeActiveTab().then(sendResponse, (err) => sendResponse({ ok: false, error: String((err && err.message) || err) }));
  return true; // async response
});
