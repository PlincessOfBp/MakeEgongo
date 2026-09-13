(function () {
  var grid = document.getElementById("creation-grid");
  var typeBar = document.getElementById("type-filters");
  var charSel = document.getElementById("char-filter");
  if (!grid) return;

  var cards = Array.prototype.slice.call(grid.children);
  var activeType = "all";

  function apply() {
    var charVal = charSel ? charSel.value : "";
    cards.forEach(function (card) {
      var okType = activeType === "all" || card.getAttribute("data-type") === activeType;
      var okChar = !charVal || (card.getAttribute("data-chars") || "").split(",").indexOf(charVal) !== -1;
      card.style.display = okType && okChar ? "" : "none";
    });
  }

  if (typeBar) {
    typeBar.addEventListener("click", function (e) {
      var btn = e.target.closest(".filter-btn");
      if (!btn) return;
      activeType = btn.getAttribute("data-filter");
      Array.prototype.forEach.call(typeBar.querySelectorAll(".filter-btn"), function (b) {
        b.classList.toggle("active", b === btn);
      });
      apply();
    });
  }
  if (charSel) {
    charSel.addEventListener("change", apply);
  }
})();