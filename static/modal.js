// Shared modal wiring for includes/warning.html (#myModal) and
// includes/confirm_modal.html (#confirmModal) -- both are shared HTML
// includes, so their element IDs (#myModal, .close, #err_message,
// #confirmModal, #confirm_yes_btn, #confirm_no_btn, #confirm_message)
// are guaranteed identical on every page that uses them. That makes it
// safe to wire the open/close *mechanics* up once, here, instead of
// every page re-declaring `var modal = ...` and re-assigning the same
// close handler after every single validation error.
//
// Loaded with `defer` from header.html, so it runs after the document
// (including whichever modal includes a given page pulled in) has
// finished parsing -- no DOMContentLoaded listener needed. Every
// lookup is null-checked since not every page includes both modals
// (or either one).
//
// showValidationError(message) is the one thing pages call directly:
// it sets the error message and shows the modal in a single line;
// the close handler only needs setting up once (below).
(function () {
	var warningModal = document.getElementById("myModal");
	var closeSpan = document.getElementsByClassName("close")[0];

	if (warningModal && closeSpan) {
		closeSpan.addEventListener("click", function () {
			warningModal.style.display = "none";
		});
	}

	window.showValidationError = function (message) {
		if (!warningModal) {
			return;
		}
		document.getElementById("err_message").innerHTML = message;
		warningModal.style.display = "block";
	};

	var confirmModal = document.getElementById("confirmModal");
	var confirmNoBtn = document.getElementById("confirm_no_btn");

	if (confirmModal && confirmNoBtn) {
		confirmNoBtn.addEventListener("click", function () {
			confirmModal.style.display = "none";
		});
	}

	// Pages that use the confirm modal still wire up #confirm_yes_btn
	// themselves (the action differs per page) and still set
	// #confirm_message and call confirmModal.style.display = "block"
	// themselves (what triggers it, and the message shown, differs
	// per page too) -- only the Cancel/close mechanics are generic.
	window.showConfirmModal = function (message) {
		if (!confirmModal) {
			return;
		}
		document.getElementById("confirm_message").innerHTML = message;
		confirmModal.style.display = "block";
	};
})();
