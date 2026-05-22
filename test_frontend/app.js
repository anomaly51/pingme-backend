const API_BASE = "http://localhost:8000";

let token = localStorage.getItem("pingme_token") || "";
let forms = [];
let reminders = [];
let socket = null;

const $ = (id) => document.getElementById(id);

function log(message, data) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  $("logOutput").textContent =
    `${line}${data ? `\n${JSON.stringify(data, null, 2)}` : ""}\n\n${$("logOutput").textContent}`;
}

function showOutput(id, data) {
  $(id).textContent = JSON.stringify(data, null, 2);
}

async function request(path, options = {}) {
  const headers = options.headers ? { ...options.headers } : {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw { status: response.status, payload };
  }
  return payload;
}

async function checkHealth() {
  try {
    const data = await request("/health/ready");
    $("apiStatus").textContent = data.status === "ok" ? "API работает" : "API частично работает";
    $("apiStatus").className = data.status === "ok" ? "pill" : "pill bad";
  } catch (error) {
    $("apiStatus").textContent = "API недоступен";
    $("apiStatus").className = "pill bad";
  }
}

function connectSocket() {
  if (!token || typeof io === "undefined") return;
  if (socket) socket.disconnect();

  socket = io(API_BASE, {
    auth: { token },
  });

  socket.on("connect", () => {
    $("socketStatus").textContent = "Realtime подключен";
    $("socketStatus").className = "pill";
    log("Realtime подключен");
  });

  socket.on("disconnect", () => {
    $("socketStatus").textContent = "Realtime выключен";
    $("socketStatus").className = "pill muted";
  });

  socket.on("connect_error", (error) => {
    $("socketStatus").textContent = "Ошибка realtime";
    $("socketStatus").className = "pill bad";
    log("Ошибка realtime", { message: error.message });
  });

  socket.on("reminder.due", (reminder) => {
    log("reminder.due", reminder);
    renderBanner(reminder);
    loadReminders();
  });
}

async function login() {
  const body = new URLSearchParams({
    username: $("emailInput").value,
    password: $("passwordInput").value,
  });
  const data = await request("/auth/login", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  token = data.access_token;
  localStorage.setItem("pingme_token", token);
  showOutput("authOutput", data);
    log("Вход выполнен");
  connectSocket();
  await Promise.all([loadForms(), loadReminders()]);
}

async function register() {
  const data = await request("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email: $("emailInput").value,
      password: $("passwordInput").value,
    }),
  });
  showOutput("authOutput", data);
  log("Аккаунт создан. Проверь почту и введи код.", data);
}

async function requestCode() {
  const data = await request("/auth/verify-email/request", {
    method: "POST",
    body: JSON.stringify({ email: $("emailInput").value }),
  });
  showOutput("authOutput", data);
  log("Код подтверждения отправлен");
}

async function confirmCode() {
  const data = await request("/auth/verify-email/confirm", {
    method: "POST",
    body: JSON.stringify({
      email: $("emailInput").value,
      code: $("codeInput").value.trim(),
    }),
  });
  showOutput("authOutput", data);
  log("Почта подтверждена");
}

async function loadForms() {
  forms = await request("/forms");
  renderForms();
  renderFormOptions();
  log("Формы загружены", { count: forms.length });
}

function renderForms() {
  const host = $("formsList");
  host.innerHTML = "";
  if (!forms.length) {
    host.innerHTML = '<div class="meta">Форм пока нет. Создай форму активности.</div>';
    return;
  }

  for (const form of forms) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <div class="item-title">
        <span>${escapeHtml(form.title)}</span>
        <span class="pill muted">#${form.form_id}</span>
      </div>
      <div class="meta">${escapeHtml(form.description || "")}</div>
      <div class="meta">Расписание: ${escapeHtml((form.schedule_crons || []).join(", ") || "не задано")}</div>
      <div class="meta">Напоминания: ${form.reminder_enabled ? "включены" : "выключены"}</div>
    `;
    host.appendChild(item);
  }
}

function renderFormOptions() {
  const select = $("answerFormSelect");
  select.innerHTML = "";
  for (const form of forms) {
    const option = document.createElement("option");
    option.value = form.form_id;
    option.textContent = `${form.form_id}: ${form.title}`;
    select.appendChild(option);
  }
}

async function createForm() {
  const title = $("formTitleInput").value.trim();
  const skipDelay = Number($("skipDelayInput").value);
  const maxMinutes = Number($("maxMinutesInput").value);
  const payload = {
    title,
    description: "Created from the local test console",
    form_structure: {
      fields: [
        {
          name: "minutes",
          label: "Сколько минут занимался",
          type: "number",
          required: true,
          min: 0,
          max: maxMinutes,
        },
        {
          name: "mood",
          label: "Настроение",
          type: "select",
          options: ["bad", "ok", "good"],
        },
      ],
    },
    schedule_crons: [$("scheduleInput").value.trim()],
    is_active: true,
    reminder_enabled: true,
    reminder_title: `Сколько времени: ${title.toLowerCase()}?`,
    reminder_payload: { activity: title },
    skip_retry_delay_seconds: skipDelay,
    delivery_retry_delay_seconds: skipDelay,
  };
  const data = await request("/forms", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  log("Форма создана", data);
  await loadForms();
}

async function loadReminders() {
  reminders = await request("/reminders?limit=20");
  renderReminders();
  log("Напоминания загружены", { count: reminders.length });
}

function renderReminders() {
  const host = $("remindersList");
  host.innerHTML = "";
  if (!reminders.length) {
    host.innerHTML = '<div class="meta">Напоминаний пока нет.</div>';
    return;
  }

  for (const reminder of reminders) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <div class="item-title">
        <span>${escapeHtml(reminder.title)}</span>
        <span class="pill muted">${translateStatus(reminder.status)}</span>
      </div>
      <div class="meta">Форма: ${reminder.form_id || "нет"} | очередь: ${translateEnqueue(reminder.enqueue_status)}</div>
      <div class="meta">Следующий показ: ${new Date(reminder.next_run_at).toLocaleString()}</div>
      <div class="row">
        <button class="secondary" data-action="skip" data-id="${reminder.id}">Позже на 30 минут</button>
        <button class="secondary" data-action="complete" data-id="${reminder.id}">Готово</button>
        <button class="ghost" data-action="cancel" data-id="${reminder.id}">Отменить</button>
      </div>
    `;
    host.appendChild(item);
  }
}

async function createReminderNow() {
  const formId = Number($("answerFormSelect").value || forms[0]?.form_id);
  if (!formId) throw new Error("Сначала создай форму.");
  const data = await request("/reminders", {
    method: "POST",
    body: JSON.stringify({
      title: "Сколько времени ты играл на гитаре?",
      form_id: formId,
      payload: { source: "test_frontend" },
      retry_delay_seconds: Number($("skipDelayInput").value),
      due_in_seconds: Number($("manualDelayInput").value),
    }),
  });
  log("Напоминание создано", data);
  renderBanner(data);
  await loadReminders();
}

function renderBanner(reminder) {
  const host = $("bannerHost");
  host.innerHTML = "";
  const banner = document.createElement("div");
  banner.className = "banner";
  banner.innerHTML = `
    <strong>${escapeHtml(reminder.title)}</strong>
    <div class="meta">Напоминание #${reminder.id}. Можно заполнить сейчас или попросить позже.</div>
    <div class="row">
      <button data-action="fill" data-id="${reminder.id}" data-form="${reminder.form_id || ""}">Заполнить</button>
      <button class="secondary" data-action="skip" data-id="${reminder.id}">Спросить через 30 минут</button>
      <button class="secondary" data-action="complete" data-id="${reminder.id}">Готово</button>
      <button class="ghost" data-action="cancel" data-id="${reminder.id}">Отменить</button>
    </div>
  `;
  host.appendChild(banner);
}

async function reminderAction(action, id) {
  let path = `/reminders/${id}/${action}`;
  const options = { method: "POST" };
  if (action === "skip") {
    options.body = JSON.stringify({ retry_delay_seconds: 1800 });
  }
  const data = await request(path, options);
  log(`Действие с напоминанием: ${translateAction(action)}`, data);
  $("bannerHost").innerHTML = "";
  await loadReminders();
}

async function submitAnswer() {
  const formId = Number($("answerFormSelect").value);
  if (!formId) throw new Error("Сначала создай форму.");
  const data = await request(`/forms/${formId}/answers`, {
    method: "POST",
    body: JSON.stringify({
      answers_data: {
        minutes: Number($("minutesInput").value),
        mood: $("moodInput").value,
      },
    }),
  });
  showOutput("answerOutput", data);
  log("Ответ сохранён", data);
  await loadReminders();
}

async function loadStats() {
  const formId = Number($("answerFormSelect").value);
  if (!formId) throw new Error("Сначала создай форму.");
  const data = await request(`/forms/${formId}/answers/stats`);
  showOutput("answerOutput", data);
  log("Статистика загружена", data);
}

function logout() {
  token = "";
  localStorage.removeItem("pingme_token");
  if (socket) socket.disconnect();
  $("socketStatus").textContent = "Realtime выключен";
  $("socketStatus").className = "pill muted";
  log("Выход выполнен");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char];
  });
}

function translateStatus(status) {
  return {
    pending: "ожидает",
    skipped: "отложено",
    completed: "завершено",
    cancelled: "отменено",
  }[status] || status;
}

function translateEnqueue(status) {
  return {
    pending: "ожидает",
    queued: "в очереди",
    failed: "ошибка",
  }[status] || status;
}

function translateAction(action) {
  return {
    skip: "позже",
    complete: "готово",
    cancel: "отмена",
  }[action] || action;
}

function bind(id, handler) {
  $(id).addEventListener("click", async () => {
    try {
      await handler();
    } catch (error) {
      const payload = error.payload || { message: error.message || String(error) };
      log("Ошибка", payload);
    }
  });
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  try {
    if (action === "fill") {
      if (target.dataset.form) $("answerFormSelect").value = target.dataset.form;
      $("minutesInput").focus();
      return;
    }
    await reminderAction(action, id);
  } catch (error) {
    log("Ошибка", error.payload || { message: error.message || String(error) });
  }
});

bind("loginBtn", login);
bind("registerBtn", register);
bind("requestCodeBtn", requestCode);
bind("confirmCodeBtn", confirmCode);
bind("refreshFormsBtn", loadForms);
bind("createFormBtn", createForm);
bind("refreshRemindersBtn", loadReminders);
bind("createReminderBtn", createReminderNow);
bind("submitAnswerBtn", submitAnswer);
bind("statsBtn", loadStats);
bind("logoutBtn", logout);
$("clearLogBtn").addEventListener("click", () => {
  $("logOutput").textContent = "";
});

checkHealth();
if (token) {
  connectSocket();
  Promise.allSettled([loadForms(), loadReminders()]);
}
