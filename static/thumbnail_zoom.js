// Thumbnail hover-zoom is handled entirely by CSS (:hover) for mice/
// trackpads (see .thumbnail:hover in imps.css, gated behind
// @media (hover: hover) so it never applies here). Touch devices have
// no real "hover" -- browsers fake it with a "sticky hover" that
// clears on tapping elsewhere, but there's no built-in way for a
// second tap on the SAME element to un-zoom it. This script adds that
// second half for touch: tap once to zoom, tap again to shrink back,
// tap elsewhere to close.
//
// Deliberately scoped to !(hover: hover) -- i.e. only runs on devices
// that can't genuinely hover. Hovering already zooms the image via
// CSS with no class involved, so restricting this script to non-hover
// devices means a mouse click on a thumbnail does nothing at all --
// hover already owns zooming there -- and only touch, which has no
// hover to conflict with, gets the tap-toggle behavior.
//
// Delegated to `document` (rather than one listener per image) so it
// automatically covers every .thumbnail on every page -- inventory,
// search results, category view, box view, and the orphan photo
// cleanup page -- with a single shared script and no per-page setup.
(function () {
	if (window.matchMedia && window.matchMedia("(hover: hover)").matches) {
		return;
	}

	document.addEventListener("click", function (event) {
		var tapped = event.target.closest(".thumbnail");

		document.querySelectorAll(".thumbnail.zoomed").forEach(function (img) {
			if (img !== tapped) {
				img.classList.remove("zoomed");
			}
		});

		if (tapped) {
			tapped.classList.toggle("zoomed");
		}
	});
})();
