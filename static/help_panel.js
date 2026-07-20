// Context-sensitive help panel (slide-in from the right).
//
// header.html renders the button/panel/overlay markup and stamps the
// current page's help topic onto <body data-help-topic="...">
// (computed server-side in app/__init__.py's inject_help_topic(),
// which strips URL variables so e.g. /boxshowcontent/4 and
// /boxshowcontent/17 both resolve to the same "boxshowcontent"
// topic/help file). This script only wires up the open/close
// interaction and points the iframe at the right file.
//
// IMPS is a traditional server-rendered app -- every link click is a
// full page load, so nothing here can "survive" navigation on its
// own. To make help feel like it follows you from page to page, the
// open/closed state is stashed in sessionStorage on every toggle, and
// re-read on each page load: if it says "open", the panel reopens
// automatically, already pointed at the *new* page's help topic
// (since the iframe src is (re)computed fresh from data-help-topic
// each time, not carried over from the previous page).
//
// sessionStorage (not localStorage) is deliberate: help state
// shouldn't persist forever across unrelated future visits, just
// within "this browsing session while I'm working on something."
(function () {
	var STORAGE_KEY = "imps_help_open";

	var panel = document.getElementById("helpPanel");
	var overlay = document.getElementById("helpOverlay");
	var frame = document.getElementById("helpFrame");
	var openBtn = document.getElementById("helpButton");
	var closeBtn = document.getElementById("helpPanelClose");
	var searchBox = document.getElementById("helpSearchBox");
	var searchResults = document.getElementById("helpSearchResults");

	if (!panel || !overlay || !frame || !openBtn) {
		return;
	}

	var topic = document.body.getAttribute("data-help-topic") || "home";
	var helpUrl = "/static/help/imps_" + topic + "_help.html";

	function openHelp() {
		// Only (re)load the iframe if it isn't already showing this
		// page's help -- avoids a visible reload flash if the user
		// toggles the panel closed/open again on the same page.
		if (frame.getAttribute("src") !== helpUrl) {
			frame.setAttribute("src", helpUrl);
		}
		panel.classList.add("open");
		overlay.classList.add("open");
		try {
			sessionStorage.setItem(STORAGE_KEY, "1");
		} catch (e) {
			// sessionStorage can throw in locked-down/private-mode
			// contexts -- help still works, it just won't persist
			// across page loads in that case.
		}
	}

	function closeHelp() {
		panel.classList.remove("open");
		overlay.classList.remove("open");
		if (searchBox) {
			searchBox.value = "";
		}
		clearResults();
		try {
			sessionStorage.setItem(STORAGE_KEY, "0");
		} catch (e) {
			// see openHelp()
		}
	}

	openBtn.addEventListener("click", openHelp);
	if (closeBtn) {
		closeBtn.addEventListener("click", closeHelp);
	}
	overlay.addEventListener("click", closeHelp);

	var wasOpen = false;
	try {
		wasOpen = sessionStorage.getItem(STORAGE_KEY) === "1";
	} catch (e) {
		// see openHelp()
	}
	if (wasOpen) {
		openHelp();
	}

	////////////////////////////////////////////////////////////////
	// Search: GET /help/search?q=... (app/blueprints/help.py) scans
	// the help files fresh on first call and returns JSON hits, so
	// results always reflect whatever's currently in static/help/ --
	// no separate index to rebuild after editing a help file.
	//
	// Debounced so we're not firing a request on every single
	// keystroke; 200ms is short enough to still feel instant.
	var searchTimer = null;
	var currentRequestId = 0;

	function clearResults() {
		if (searchResults) {
			searchResults.innerHTML = "";
			searchResults.classList.remove("open");
		}
	}

	function renderResults(results, query) {
		if (!searchResults) {
			return;
		}
		if (results.length === 0) {
			searchResults.innerHTML =
				'<div class="help-search-empty">No matches for "' +
				escapeHtml(query) + '"</div>';
			searchResults.classList.add("open");
			return;
		}
		var html = "";
		for (var i = 0; i < results.length; i++) {
			var r = results[i];
			html +=
				'<div class="help-search-result" data-topic="' +
				escapeHtml(r.topic) + '">' +
				'<div class="help-search-result-title">' + escapeHtml(r.title) + '</div>' +
				'<div class="help-search-result-snippet">' + escapeHtml(r.snippet) + '</div>' +
				'</div>';
		}
		searchResults.innerHTML = html;
		searchResults.classList.add("open");

		var items = searchResults.querySelectorAll(".help-search-result");
		items.forEach(function (item) {
			item.addEventListener("click", function () {
				var topic = item.getAttribute("data-topic");
				frame.setAttribute("src", "/static/help/imps_" + topic + "_help.html");
				clearResults();
				searchBox.value = "";
			});
		});
	}

	function escapeHtml(s) {
		var div = document.createElement("div");
		div.textContent = s;
		return div.innerHTML;
	}

	function runSearch(query) {
		var requestId = ++currentRequestId;
		fetch("/help/search?q=" + encodeURIComponent(query))
			.then(function (resp) {
				return resp.ok ? resp.json() : [];
			})
			.then(function (results) {
				// Ignore stale responses if a newer search has since
				// been fired (e.g. slow network + fast typing).
				if (requestId !== currentRequestId) {
					return;
				}
				renderResults(results, query);
			})
			.catch(function () {
				// Search is a "nice to have" on top of browsing help
				// topic-by-topic -- a network hiccup here shouldn't
				// show the person an error, just no results.
				if (requestId === currentRequestId) {
					clearResults();
				}
			});
	}

	if (searchBox) {
		searchBox.addEventListener("input", function () {
			var query = searchBox.value.trim();
			clearTimeout(searchTimer);
			if (query === "") {
				clearResults();
				return;
			}
			searchTimer = setTimeout(function () {
				runSearch(query);
			}, 200);
		});
	}
})();
