// Ctrl/Cmd-click batch merge for cp_categories.html/cp_locations.html
// name cells. Merge button submits the selection to a confirm page --
// no inline picker, unlike the item list's batch bar.
(function () {
	var picked = new Set();

	var actionBar = document.getElementById("mergeActionBar");
	var countLabel = document.getElementById("mergeCount");
	var mergeBtn = document.getElementById("mergeBtn");
	var cancelBtn = document.getElementById("mergeCancelBtn");
	var mergeForm = document.getElementById("mergeForm");

	if (!actionBar || !mergeForm) {
		return;
	}

	function refreshActionBar() {
		countLabel.textContent = picked.size + " selected";
		actionBar.classList.toggle("visible", picked.size > 0);
		mergeBtn.disabled = picked.size < 2;
	}

	function clearPicked() {
		document.querySelectorAll(".table_row.picked").forEach(function (row) {
			row.classList.remove("picked");
		});
		picked.clear();
		refreshActionBar();
	}

	document.addEventListener("click", function (event) {
		var target = event.target.closest('[data-batch-action="merge"]');
		if (!target || !(event.ctrlKey || event.metaKey)) {
			return;
		}
		event.preventDefault();

		var row = target.closest(".table_row");
		if (!row) {
			return;
		}
		var rowNum = row.getAttribute("data-merge-num");
		var nowPicked = row.classList.toggle("picked");
		if (nowPicked) {
			picked.add(rowNum);
		} else {
			picked.delete(rowNum);
		}
		refreshActionBar();
	});

	if (cancelBtn) {
		cancelBtn.addEventListener("click", clearPicked);
	}

	if (mergeBtn) {
		mergeBtn.addEventListener("click", function () {
			if (mergeBtn.disabled) {
				return;
			}
			picked.forEach(function (num) {
				var input = document.createElement("input");
				input.type = "hidden";
				input.name = mergeForm.getAttribute("data-field-name");
				input.value = num;
				mergeForm.appendChild(input);
			});
			mergeForm.submit();
		});
	}
})();
