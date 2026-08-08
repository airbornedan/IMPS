// Ctrl/Cmd-click batch delete for item list rows (includes/includeitemlist.html).
// A plain click on a trash icon is untouched -- it still submits that
// row's own single-item form to /itemdel/<item_num> as always. Ctrl/Cmd-
// click instead marks the row as picked and adds it to a pending batch,
// with no navigation and no server round trip until "Delete selected"
// is actually clicked.
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

	var actionBar = document.getElementById("batchActionBar");
	var actionBarLabel = document.getElementById("batchActionBarLabel");
	var batchForm = document.getElementById("batchDeleteForm");
	var cancelBtn = document.getElementById("batchCancelBtn");
	var deleteBtn = document.getElementById("batchDeleteBtn");

	function refreshActionBar() {
		if (!actionBar) {
			return;
		}
		actionBarLabel.textContent = picked.size + " selected";
		actionBar.classList.toggle("visible", picked.size > 0);
	}

	function clearPicked() {
		document.querySelectorAll(".imps.icon-only.trash.picked").forEach(function (btn) {
			btn.classList.remove("picked");
			var row = btn.closest(".table_row");
			if (row) {
				row.classList.remove("picked");
			}
		});
		picked.clear();
		refreshActionBar();
	}

	document.addEventListener("click", function (event) {
		var btn = event.target.closest(".imps.icon-only.trash[data-item-num]");
		if (!btn || !(event.ctrlKey || event.metaKey)) {
			return;
		}
		event.preventDefault();

		var itemNum = btn.getAttribute("data-item-num");
		var row = btn.closest(".table_row");
		var nowPicked = btn.classList.toggle("picked");
		if (row) {
			row.classList.toggle("picked", nowPicked);
		}
		if (nowPicked) {
			picked.add(itemNum);
		} else {
			picked.delete(itemNum);
		}
		refreshActionBar();
	});

	if (cancelBtn) {
		cancelBtn.addEventListener("click", clearPicked);
	}

	if (deleteBtn && batchForm) {
		deleteBtn.addEventListener("click", function () {
			if (picked.size === 0) {
				return;
			}
			picked.forEach(function (itemNum) {
				var input = document.createElement("input");
				input.type = "hidden";
				input.name = "item_nums";
				input.value = itemNum;
				batchForm.appendChild(input);
			});
			batchForm.submit();
		});
	}
})();
