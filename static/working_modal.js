// Shared wiring for includes/working_modal.html (#workingModal) --
// shown immediately on submit/click for slow actions (backup,
// restore) so a 4-5+ second wait doesn't look like a dead click.
// Disappears for free once the page navigates away; nothing closes it
// manually, so there's no dismiss handler here to wire up.
//
// Loaded with `defer` from header.html, same as modal.js. Add
// data-working to any <form> or <a> that triggers a slow action --
// no page-specific JS needed.
(function () {
	var workingModal = document.getElementById("workingModal");
	if (!workingModal) {
		return;
	}

	window.showWorkingModal = function () {
		workingModal.style.display = "block";
	};

	document.querySelectorAll("form[data-working]").forEach(function (form) {
		form.addEventListener("submit", function () {
			showWorkingModal();
		});
	});

	document.querySelectorAll("a[data-working]").forEach(function (link) {
		link.addEventListener("click", function () {
			showWorkingModal();
		});
	});
})();
