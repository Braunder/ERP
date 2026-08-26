/** Графики статистики на Chart.js. */

const PAYMENT_LABELS = {
  cash: "Нал",
  card: "Б/нал",
  transfer: "Перевод",
};

const COLORS = [
  "#0d6efd",
  "#20c997",
  "#dc3545",
  "#fd7e14",
  "#6610f2",
  "#0dcaf0",
  "#198754",
  "#d63384",
  "#6f42c1",
  "#adb5bd",
];

let periodChart = null;
let categoryChart = null;
let paymentChart = null;

function formatMoney(value) {
  const num = Number(value);
  return Number.isFinite(num)
    ? num.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value;
}

async function loadFilters() {
  try {
    const res = await fetch("/api/stats/filters");
    if (!res.ok) throw new Error("Ошибка загрузки фильтров");
    const data = await res.json();

    const categorySelect = document.getElementById("filter-category");
    categorySelect.innerHTML = '<option value="">Все категории</option>';
    for (const cat of data.categories) {
      const option = document.createElement("option");
      option.value = cat.id;
      option.textContent = `${cat.name} (${cat.kind === "income" ? "доход" : "расход"})`;
      categorySelect.appendChild(option);
    }

    const paymentSelect = document.getElementById("filter-payment");
    paymentSelect.innerHTML = '<option value="">Все</option>';
    for (const pm of data.payment_methods) {
      const option = document.createElement("option");
      option.value = pm.value;
      option.textContent = pm.label;
      paymentSelect.appendChild(option);
    }
  } catch (err) {
    console.error(err);
  }
}

function buildQueryParams() {
  const params = new URLSearchParams();
  const kind = document.getElementById("filter-kind").value;
  const categoryId = document.getElementById("filter-category").value;
  const dateFrom = document.getElementById("filter-date-from").value;
  const dateTo = document.getElementById("filter-date-to").value;
  const payment = document.getElementById("filter-payment").value;

  if (kind) params.set("kind", kind);
  if (categoryId) params.set("category_id", categoryId);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (payment) params.set("payment_method", payment);
  return params;
}

function hasData(data) {
  return (
    data.by_period.length > 0 ||
    data.by_category.length > 0 ||
    data.by_payment.length > 0
  );
}

function destroyCharts() {
  if (periodChart) {
    periodChart.destroy();
    periodChart = null;
  }
  if (categoryChart) {
    categoryChart.destroy();
    categoryChart = null;
  }
  if (paymentChart) {
    paymentChart.destroy();
    paymentChart = null;
  }
}

function renderPeriodChart(data) {
  const ctx = document.getElementById("period-chart").getContext("2d");
  const labels = data.by_period.map((row) => row.period);
  const income = data.by_period.map((row) => Number(row.income));
  const expense = data.by_period.map((row) => Number(row.expense));

  periodChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Доход",
          data: income,
          backgroundColor: "#198754",
        },
        {
          label: "Расход",
          data: expense,
          backgroundColor: "#dc3545",
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true },
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${formatMoney(ctx.raw)}`,
          },
        },
      },
    },
  });
}

function renderCategoryChart(data) {
  const ctx = document.getElementById("category-chart").getContext("2d");
  const labels = data.by_category.map((row) => row.category);
  const values = data.by_category.map((row) => Number(row.amount));
  const colors = labels.map((_, i) => COLORS[i % COLORS.length]);

  categoryChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: colors,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${formatMoney(ctx.raw)}`,
          },
        },
      },
    },
  });
}

function renderPaymentChart(data) {
  const ctx = document.getElementById("payment-chart").getContext("2d");
  const labels = data.by_payment.map((row) => row.label);
  const values = data.by_payment.map((row) => Number(row.amount));

  paymentChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Доход",
          data: values,
          backgroundColor: "#0d6efd",
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true },
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${formatMoney(ctx.raw)}`,
          },
        },
      },
    },
  });
}

async function loadData() {
  const params = buildQueryParams();
  try {
    const res = await fetch(`/api/stats/data?${params.toString()}`);
    if (!res.ok) throw new Error("Ошибка загрузки данных");
    const data = await res.json();

    document.getElementById("total-income").textContent = formatMoney(data.totals.income);
    document.getElementById("total-expense").textContent = formatMoney(data.totals.expense);
    document.getElementById("total-balance").textContent = formatMoney(data.totals.balance);

    destroyCharts();

    if (!hasData(data)) {
      document.getElementById("no-data").classList.remove("hidden");
      document.getElementById("charts-container").classList.add("hidden");
      return;
    }

    document.getElementById("no-data").classList.add("hidden");
    document.getElementById("charts-container").classList.remove("hidden");

    if (data.by_period.length > 0) renderPeriodChart(data);
    if (data.by_category.length > 0) renderCategoryChart(data);
    if (data.by_payment.length > 0) renderPaymentChart(data);
  } catch (err) {
    console.error(err);
    alert("Не удалось загрузить данные для графиков");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadFilters().then(loadData);
  document.getElementById("btn-apply").addEventListener("click", loadData);
});
