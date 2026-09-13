document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.getElementById("nav-toggle");
  var nav = document.getElementById("main-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      nav.classList.toggle("open");
    });
  }
});

function $(id) { return document.getElementById(id); }

function scalarKD(a, b) {
  return (a + (b || "")).toLowerCase();
}