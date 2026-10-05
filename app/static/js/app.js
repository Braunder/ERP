"use strict";

function confirmDelete() {
    return confirm("Удалить запись?");
}

(function () {
    const menuToggle = document.querySelector(".menu-toggle");
    const navLinks = document.querySelector(".nav-links");

    if (menuToggle && navLinks) {
        const setMenuOpen = (isOpen) => {
            navLinks.classList.toggle("open", isOpen);
            menuToggle.setAttribute("aria-expanded", String(isOpen));
        };

        menuToggle.addEventListener("click", (event) => {
            event.stopPropagation();
            setMenuOpen(!navLinks.classList.contains("open"));
        });

        document.addEventListener("click", (event) => {
            if (
                navLinks.classList.contains("open") &&
                !navLinks.contains(event.target) &&
                !menuToggle.contains(event.target)
            ) {
                setMenuOpen(false);
            }
        });
    }
})();
