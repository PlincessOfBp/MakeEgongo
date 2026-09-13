(function () {
  var list = document.getElementById("hist-list");
  var bar = document.getElementById("hist-filters");
  if (!list || !bar) return;

  var entries = Array.prototype.slice.call(list.children);
  var active = "all";

  function apply() {
    entries.forEach(function (e) {
      var match = active === "all" || e.getAttribute("data-cat") === active;
      e.style.display = match ? "" : "none";
    });
  }

  bar.addEventListener("click", function (e) {
    var btn = e.target.closest(".filter-btn");
    if (!btn) return;
    active = btn.getAttribute("data-cat");
    Array.prototype.forEach.call(bar.querySelectorAll(".filter-btn"), function (b) {
      b.classList.toggle("active", b === btn);
    });
    apply();
  });
})();