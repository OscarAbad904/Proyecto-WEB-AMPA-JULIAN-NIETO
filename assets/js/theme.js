const toggle = document.getElementById("theme-toggle");
const root = document.documentElement;
const stored = localStorage.getItem("ampa-theme");
if (stored) {
  root.setAttribute("data-theme", stored);
}

toggle?.addEventListener("click", () => {
  const current = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", current);
  localStorage.setItem("ampa-theme", current);
});
