"use strict";
// Runs in <head> so the page never flashes the wrong theme. A choice made with the toggle wins;
// otherwise dojo follows the system setting.
(function () {
  let saved = null;
  try { saved = localStorage.getItem("dojo.theme"); } catch { /* storage blocked */ }
  const system = window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", saved === "light" || saved === "dark" ? saved : system);
})();
