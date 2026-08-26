"use strict";

function confirmDelete() {
    return confirm("Удалить запись?");
}

(function () {
    const menuToggle = document.querySelector(".menu-toggle");
    const navLinks = document.querySelector(".nav-links");

    if (menuToggle && navLinks) {
        menuToggle.addEventListener("click", (event) => {
            event.stopPropagation();
            navLinks.classList.toggle("open");
        });

        document.addEventListener("click", (event) => {
            if (navLinks.classList.contains("open") && !navLinks.contains(event.target) && event.target !== menuToggle) {
                navLinks.classList.remove("open");
            }
        });
    }
})();
