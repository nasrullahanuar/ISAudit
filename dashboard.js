const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("transaction-file");
const selectedFile = document.getElementById("selected-file");
const uploadButton = document.getElementById("upload-button");
const uploadMessage = document.getElementById("upload-message");
const transactionRows = document.getElementById("transaction-rows");

const currencyFormatter = new Intl.NumberFormat("en-MY", {
  style: "currency",
  currency: "MYR",
  minimumFractionDigits: 2,
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  selectedFile.textContent = file ? file.name : "CSV or XLSX · up to 5 MB";
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];

  if (!file) {
    showUploadMessage("Choose a CSV or XLSX file first.", "error");
    return;
  }
  if (!/\.(csv|xlsx)$/i.test(file.name)) {
    showUploadMessage("Only .csv and .xlsx files are accepted.", "error");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showUploadMessage("The file exceeds the 5 MB upload limit.", "error");
    return;
  }

  uploadButton.disabled = true;
  uploadButton.textContent = "Validating file…";
  showUploadMessage("Checking columns and transaction values locally…");

  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/transactions", {
      method: "POST",
      body: formData,
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || "The file could not be uploaded.");
    }

    showUploadMessage(result.message, "success");
    await loadDashboard();
  } catch (error) {
    showUploadMessage(error.message || "The upload failed. Please try again.", "error");
  } finally {
    uploadButton.disabled = false;
    uploadButton.textContent = "Validate and upload";
  }
});

function showUploadMessage(message, type = "") {
  uploadMessage.textContent = message;
  uploadMessage.className = `upload-message ${type}`.trim();
}

function renderTransactions(transactions) {
  transactionRows.replaceChildren();
  if (transactions.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "table-empty";
    cell.textContent = "No transactions loaded.";
    row.append(cell);
    transactionRows.append(row);
    return;
  }

  for (const transaction of transactions) {
    const row = document.createElement("tr");
    const values = [
      transaction.transaction_id,
      transaction.transaction_date,
      transaction.vendor_name,
      transaction.invoice_number,
      currencyFormatter.format(Number(transaction.amount)),
      transaction.transaction_type,
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    transactionRows.append(row);
  }
}

async function loadDashboard() {
  try {
    const response = await fetch("/api/dashboard");
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not load dashboard data.");
    }

    document.getElementById("total-transactions").textContent =
      data.summary.total_transactions.toLocaleString();
    document.getElementById("total-value").textContent =
      `RM ${data.summary.total_amount_myr}`;
    document.getElementById("vendor-count").textContent =
      data.summary.vendor_count.toLocaleString();
    document.getElementById("recent-caption").textContent =
      `Showing up to ${data.recent_transactions.length} most recently uploaded rows.`;
    renderTransactions(data.recent_transactions);
  } catch (error) {
    showUploadMessage(error.message || "Could not load dashboard data.", "error");
  }
}

loadDashboard();
