// Ctrl/Cmd-click batch actions for item list rows (includes/includeitemlist.html).
// Three click targets, each identifying which action a selection is
// for: the trash icon (delete), the box-num cell (move to a different
// box), the category cell (recategorize). A plain click on any of
// them is untouched -- trash still does its normal single-item
// submit; box-num/category cells have no plain-click behavior at all.
// Ctrl/Cmd-click on a target of a DIFFERENT kind than the current
// selection clears everything and starts fresh with just that row,
// under the new action -- no mixed-action batches.
//
// Desktop only by design -- there's no touch equivalent of a modifier
// key, and includeitemlist_mobile.html (the tiled-thumbnail view) never
// gets these elements at all, so this script has nothing to do there.
//
// Delegated to `document` and null-checked throughout, same reasoning as
// modal.js -- includeitemlist.html (and this script with it) is shared
// across inventory, search results, category view, box view, and the
// orphan photo cleanup page, so a page without any of these elements
// just no-ops.
(function () {
	var picked = new Set();
	var currentAction = null; // null | "delete" | "box" | "cat"

	var actionBar = document.getElementById("batchActionBar");
	var countLabel = document.getElementById("batchCount");
	var table = document.getElementById("itemdisplaytable");

	var deleteForm = document.getElementById("batchDeleteForm");
	var recatForm = document.getElementById("batchRecatForm");
	var boxMoveForm = document.getElementById("batchBoxMoveForm");

	var deleteBtn = document.getElementById("batchDeleteBtn");
	var recatBtn = document.getElementById("batchRecatBtn");
	var boxMoveBtn = document.getElementById("batchBoxMoveBtn");
	var cancelBtn = document.getElementById("batchCancelBtn");

	var boxPicker = document.getElementById("batchBoxPicker");
	var boxInput = document.getElementById("batchBoxNum");
	var catPicker = document.getElementById("batchCatPicker");
	var catInput = document.getElementById("batchCatName");

	var validBoxes = window.IMPS_AVAILABLE_BOXES || [];

	// Right-aligns the action bar with the item table's own right edge
	// instead of the viewport center -- otherwise it reads as floating
	// over the page rather than belonging to the table, especially on
	// a wide window where the table doesn't span the full width.
	function alignActionBar() {
		if (!actionBar || !table) {
			return;
		}
		var gap = window.innerWidth - table.getBoundingClientRect().right;
		actionBar.style.right = Math.max(gap, 0) + "px";
	}

	function validateBoxInput() {
		if (!boxInput || !boxMoveBtn) {
			return;
		}
		var typed = boxInput.value.trim();
		if (typed === "") {
			boxInput.classList.remove("input-invalid");
			boxMoveBtn.disabled = true;
			return;
		}
		var num = Number(typed);
		var isValid = !isNaN(num) && validBoxes.indexOf(num) !== -1;
		boxInput.classList.toggle("input-invalid", !isValid);
		boxMoveBtn.disabled = !isValid;
	}

	function validateCatInput() {
		if (!catInput || !recatBtn) {
			return;
		}
		// No "invalid" state -- any non-empty name is acceptable, same
		// as get_or_create_cat_num(): a name that doesn't exist yet
		// just creates a new category.
		recatBtn.disabled = catInput.value.trim() === "";
	}

	function refreshActionBar() {
		if (!actionBar) {
			return;
		}
		alignActionBar();
		countLabel.textContent = picked.size + " selected";
		actionBar.classList.toggle("visible", picked.size > 0);

		if (deleteBtn) {
			deleteBtn.style.display = currentAction === "delete" ? "" : "none";
		}
		if (recatBtn) {
			recatBtn.style.display = currentAction === "cat" ? "" : "none";
		}
		if (boxMoveBtn) {
			boxMoveBtn.style.display = currentAction === "box" ? "" : "none";
		}
		if (boxPicker) {
			boxPicker.style.display = currentAction === "box" ? "" : "none";
		}
		if (catPicker) {
			catPicker.style.display = currentAction === "cat" ? "" : "none";
		}

		validateBoxInput();
		validateCatInput();
	}

	function resetSelection() {
		// .picked also lands on the trash icon itself (see
		// .imps.icon-only.trash.picked in imps.css), not just the row --
		// clear both.
		document.querySelectorAll(".picked").forEach(function (el) {
			el.classList.remove("picked");
		});
		picked.clear();
		currentAction = null;
	}

	function clearAll() {
		resetSelection();
		if (boxInput) {
			boxInput.value = "";
			boxInput.classList.remove("input-invalid");
		}
		if (catInput) {
			catInput.value = "";
		}
		refreshActionBar();
	}

	document.addEventListener("click", function (event) {
		var target = event.target.closest("[data-batch-action]");
		if (!target || !(event.ctrlKey || event.metaKey)) {
			return;
		}
		event.preventDefault();

		var row = target.closest(".table_row");
		if (!row) {
			return;
		}
		var itemNum = row.getAttribute("data-item-num");
		var action = target.getAttribute("data-batch-action");

		if (currentAction !== null && action !== currentAction) {
			resetSelection();
		}
		currentAction = action;

		var nowPicked = row.classList.toggle("picked");
		// Trash icon also gets its own .picked outline (see
		// .imps.icon-only.trash.picked in imps.css) -- box-num/category
		// cells have no equivalent, the row highlight alone covers them.
		if (action === "delete") {
			target.classList.toggle("picked", nowPicked);
		}
		if (nowPicked) {
			picked.add(itemNum);
		} else {
			picked.delete(itemNum);
			if (picked.size === 0) {
				currentAction = null;
			}
		}
		refreshActionBar();
	});

	if (cancelBtn) {
		cancelBtn.addEventListener("click", clearAll);
	}

	function submitBatch(form, extraFields) {
		if (picked.size === 0) {
			return;
		}
		picked.forEach(function (itemNum) {
			var input = document.createElement("input");
			input.type = "hidden";
			input.name = "item_nums";
			input.value = itemNum;
			form.appendChild(input);
		});
		(extraFields || []).forEach(function (field) {
			var input = document.createElement("input");
			input.type = "hidden";
			input.name = field.name;
			input.value = field.value;
			form.appendChild(input);
		});
		form.submit();
	}

	if (deleteBtn && deleteForm) {
		deleteBtn.addEventListener("click", function () {
			submitBatch(deleteForm);
		});
	}

	if (recatBtn && recatForm && catInput) {
		recatBtn.addEventListener("click", function () {
			if (recatBtn.disabled) {
				return;
			}
			submitBatch(recatForm, [{ name: "cat_name", value: catInput.value }]);
		});
	}

	if (boxMoveBtn && boxMoveForm && boxInput) {
		boxMoveBtn.addEventListener("click", function () {
			if (boxMoveBtn.disabled) {
				return;
			}
			submitBatch(boxMoveForm, [{ name: "box_num", value: boxInput.value }]);
		});
	}

	if (boxInput) {
		boxInput.addEventListener("input", validateBoxInput);
	}
	if (catInput) {
		catInput.addEventListener("input", validateCatInput);
	}

	window.addEventListener("resize", alignActionBar);
	alignActionBar();
})();
