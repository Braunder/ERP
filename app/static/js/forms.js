"use strict";

(function () {
    const kindSelect = document.getElementById("kind-select");
    const categorySelect = document.getElementById("category-select");
    const subcategoryLabel = document.getElementById("subcategory-label");
    const subcategorySelect = document.getElementById("subcategory-select");
    const supplierSelect = document.getElementById("supplier-select");
    const productsTbody = document.getElementById("products-tbody");
    const addProductRowBtn = document.getElementById("add-product-row");
    const productRowTemplate = document.getElementById("product-row-template");

    const blocks = {
        guests: document.getElementById("guests-block"),
        payment: document.getElementById("payment-block"),
        supplier: document.getElementById("supplier-block"),
        employee: document.getElementById("employee-block"),
        responsible: document.getElementById("responsible-block"),
        products: document.getElementById("products-block"),
    };

    let categoryTree = [];
    let products = [];
    let productPrices = [];
    let rowIndex = 0;

    function findCategoryById(id) {
        const search = (nodes) => {
            for (const node of nodes) {
                if (node.id === id) return node;
                if (node.children && node.children.length) {
                    const found = search(node.children);
                    if (found) return found;
                }
            }
            return null;
        };
        return search(categoryTree);
    }

    async function loadCategories(kind) {
        const res = await fetch(`/api/categories?kind=${kind}&tree=1`);
        categoryTree = await res.json();
        const currentValue = categorySelect.value;
        categorySelect.innerHTML = '<option value="">—</option>';
        categoryTree.forEach((cat) => {
            // Показываем только корневые категории (без дочерних) в основном списке
            if (cat.children && cat.children.length > 0) {
                return; // пропускаем категории с детьми — они в подкатегории
            }
            const option = document.createElement("option");
            option.value = cat.id;
            option.textContent = cat.name;
            categorySelect.appendChild(option);
        });
        categorySelect.value = currentValue;
    }

    async function loadProductPrices() {
        const supplierId = supplierSelect.value;
        if (!supplierId) {
            productPrices = [];
            return;
        }
        const res = await fetch(`/api/product-prices?supplier_id=${supplierId}`);
        productPrices = await res.json();
    }

    function fillProductSelect(select) {
        const current = select.value;
        select.innerHTML = '<option value="">— выберите продукт —</option><option value="custom">Свой вариант</option>';
        products.forEach((product) => {
            const option = document.createElement("option");
            option.value = product.id;
            option.textContent = product.name;
            select.appendChild(option);
        });
        if (current) select.value = current;
    }

    function getPriceForProduct(productId) {
        const price = productPrices.find((p) => p.product_id === Number(productId));
        return price ? price.price : "";
    }

    function updateSubcategories() {
        const categoryId = Number(categorySelect.value);
        const category = findCategoryById(categoryId);
        if (category && category.children && category.children.length) {
            subcategoryLabel.style.display = "block";
            subcategorySelect.disabled = false;
            categorySelect.disabled = true;
            subcategorySelect.innerHTML = '<option value="">—</option>';
            category.children.forEach((child) => {
                const option = document.createElement("option");
                option.value = child.id;
                option.textContent = child.name;
                subcategorySelect.appendChild(option);
            });
        } else {
            subcategoryLabel.style.display = "none";
            subcategorySelect.disabled = true;
            categorySelect.disabled = false;
            subcategorySelect.innerHTML = '<option value="">—</option>';
            updateVisibility(category);
        }
    }

    function updateVisibility(category) {
        if (!category) {
            Object.values(blocks).forEach((el) => (el.style.display = "none"));
            return;
        }
        blocks.guests.style.display = category.requires_guests ? "block" : "none";
        const kind = kindSelect.value;
        blocks.payment.style.display = category.requires_payment_method && kind === "income" ? "block" : "none";
        blocks.supplier.style.display = category.requires_supplier ? "block" : "none";
        blocks.employee.style.display = category.requires_employee ? "block" : "none";
        blocks.responsible.style.display = category.requires_responsible ? "block" : "none";
        blocks.products.style.display = category.requires_products ? "block" : "none";
    }

    function addProductRow(data) {
        const clone = productRowTemplate.content.cloneNode(true);
        const row = clone.querySelector("tr");
        const idx = rowIndex++;
        row.dataset.index = idx;
        row.querySelectorAll("[name]").forEach((el) => {
            el.name = el.name.replace("__IDX__", idx);
        });

        const productSelect = row.querySelector(".product-select");
        const customInput = row.querySelector(".custom-name");
        const priceInput = row.querySelector(".price-input");
        const unitInput = row.querySelector(".unit-input");

        fillProductSelect(productSelect);

        productSelect.addEventListener("change", () => {
            if (productSelect.value === "custom") {
                customInput.disabled = false;
                customInput.focus();
                priceInput.value = "";
            } else {
                customInput.disabled = true;
                customInput.value = "";
                const product = products.find((p) => p.id === Number(productSelect.value));
                if (product) {
                    unitInput.value = product.unit;
                    const price = getPriceForProduct(product.id);
                    if (price !== "") priceInput.value = price;
                }
            }
        });

        row.querySelector(".remove-row").addEventListener("click", () => {
            row.remove();
            recalculateAmount();
        });

        row.querySelector(".price-input").addEventListener("input", recalculateAmount);
        row.querySelector(".quantity-input").addEventListener("input", recalculateAmount);

        if (data) {
            if (data.product_id) {
                productSelect.value = data.product_id;
                const product = products.find((p) => p.id === data.product_id);
                if (product) unitInput.value = data.unit || product.unit;
            } else {
                productSelect.value = "custom";
                customInput.disabled = false;
                customInput.value = data.name || "";
            }
            priceInput.value = data.price || "";
            unitInput.value = data.unit || "шт";
            row.querySelector(".quantity-input").value = data.quantity || 1;
        }

        productsTbody.appendChild(row);
        recalculateAmount();
    }

    function recalculateAmount() {
        const categoryId = Number(subcategorySelect.disabled ? categorySelect.value : subcategorySelect.value);
        const category = findCategoryById(categoryId);
        if (!category || !category.requires_products) return;
        if (kindSelect.value !== "expense") return;

        let total = 0;
        document.querySelectorAll(".product-row").forEach((row) => {
            const price = parseFloat(row.querySelector(".price-input").value) || 0;
            const qty = parseFloat(row.querySelector(".quantity-input").value) || 0;
            total += price * qty;
        });
        const amountInput = document.getElementById("amount-input");
        if (!amountInput.value) {
            amountInput.value = total.toFixed(2);
        }
    }

    async function initEditMode() {
        const op = window.ERP_FORM.operation;
        if (!op) return;

        await loadCategories(op.kind);
        const category = findCategoryById(op.category_id);
        if (!category) return;

        if (category.parent_id) {
            categorySelect.value = category.parent_id;
            updateSubcategories();
            subcategorySelect.value = op.category_id;
        } else {
            categorySelect.value = op.category_id;
            updateSubcategories();
        }

        const activeCategory = subcategorySelect.disabled ? category : findCategoryById(Number(subcategorySelect.value));
        updateVisibility(activeCategory);

        if (activeCategory && activeCategory.requires_products && op.items) {
            await loadProductPrices();
            op.items.forEach((item) => addProductRow(item));
        }
    }

    async function initCreateMode() {
        await loadCategories(kindSelect.value);
    }

    kindSelect.addEventListener("change", async () => {
        categorySelect.value = "";
        subcategorySelect.innerHTML = '<option value="">—</option>';
        subcategoryLabel.style.display = "none";
        subcategorySelect.disabled = true;
        categorySelect.disabled = false;
        updateVisibility(null);
        await loadCategories(kindSelect.value);
    });

    categorySelect.addEventListener("change", () => {
        updateSubcategories();
        const categoryId = Number(categorySelect.value);
        const category = findCategoryById(categoryId);
        if (category && (!category.children || !category.children.length)) {
            updateVisibility(category);
        }
    });

    subcategorySelect.addEventListener("change", () => {
        const categoryId = Number(subcategorySelect.value);
        const category = findCategoryById(categoryId);
        updateVisibility(category);
    });

    supplierSelect.addEventListener("change", async () => {
        await loadProductPrices();
        document.querySelectorAll(".product-select").forEach((select) => {
            if (select.value && select.value !== "custom") {
                const row = select.closest("tr");
                const price = getPriceForProduct(Number(select.value));
                if (price !== "") row.querySelector(".price-input").value = price;
            }
        });
    });

    addProductRowBtn.addEventListener("click", () => addProductRow());

    async function init() {
        await loadProducts();
        if (window.ERP_FORM && window.ERP_FORM.operation) {
            await initEditMode();
        } else {
            await initCreateMode();
        }
    }

    init();
})();
