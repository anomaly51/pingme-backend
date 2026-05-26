const API_BASE = "http://localhost:8000";

let token = localStorage.getItem("pingme_token") || "";
let forms = [];
let reminders = [];
let socket = null;
let scheduleTimes = ["20:00"];
let reminderHistoryVisible = false;
let answerHistoryVisible = false;
let answerHistory = [];

const $ = (id) => document.getElementById(id);

function log(message, data) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  const payload = data ? `\n${JSON.stringify(maskSensitive(data), null, 2)}` : "";
  $("logOutput").textContent = `${line}${payload}\n\n${$("logOutput").textContent}`;
}

function showOutput(id, data) {
  $(id).textContent = JSON.stringify(maskSensitive(data), null, 2);
}

function maskSensitive(value) {
  if (Array.isArray(value)) return value.map(maskSensitive);
  if (!value || typeof value !== "object") return value;

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      if (["access_token", "refresh_token", "token"].includes(key)) {
        return [key, maskToken(item)];
      }
      return [key, maskSensitive(item)];
    }),
  );
}

function maskToken(value) {
  if (typeof value !== "string") return value;
  if (value.length <= 16) return "***";
  return `${value.slice(0, 10)}...${value.slice(-6)}`;
}

function setPill(id, text, state = "") {
  $(id).textContent = text;
  $(id).className = `pill${state ? ` ${state}` : ""}`;
}

function setStep(id, state) {
  $(id).classList.remove("done", "error");
  if (state) $(id).classList.add(state);
}

function setResult(id, text, state = "muted") {
  $(id).textContent = text;
  $(id).className = `result ${state}`.trim();
}

function updateAuthStatus() {
  if (token) {
    setPill("authStatus", "Вход выполнен");
    setStep("stepAuth", "done");
    return;
  }
  setPill("authStatus", "Нет входа", "muted");
  setStep("stepAuth", "");
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
  let payload = {};

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }

  if (!response.ok) {
    throw { status: response.status, payload };
  }

  return payload;
}

async function checkHealth() {
  try {
    const data = await request("/health/ready");
    const dbOk = data.checks?.database === true;
    const rabbitOk = data.checks?.rabbitmq === true;
    const text = `API: ${data.status}. База: ${dbOk ? "работает" : "ошибка"}. RabbitMQ: ${rabbitOk ? "работает" : "ошибка"}.`;

    setPill("apiStatus", data.status === "ok" ? "API работает" : "API частично работает", data.status === "ok" ? "" : "warn");
    setResult("healthResult", text, data.status === "ok" ? "" : "bad");
    setStep("stepHealth", data.status === "ok" ? "done" : "error");
    log("Проверка backend", data);
    return data;
  } catch (error) {
    setPill("apiStatus", "API недоступен", "bad");
    setResult("healthResult", formatError(error), "bad");
    setStep("stepHealth", "error");
    log("Backend недоступен", error.payload || { message: error.message });
    throw error;
  }
}

function connectSocket() {
  if (!token || typeof io === "undefined") return;
  if (socket) socket.disconnect();

  socket = io(API_BASE, {
    auth: { token },
  });

  socket.on("connect", () => {
    setPill("socketStatus", "Realtime подключен");
    log("Realtime подключен");
  });

  socket.on("disconnect", () => {
    setPill("socketStatus", "Realtime выключен", "muted");
  });

  socket.on("connect_error", (error) => {
    setPill("socketStatus", "Ошибка realtime", "bad");
    log("Ошибка realtime", { message: error.message });
  });

  socket.on("reminder.due", (reminder) => {
    log("Realtime: пришло напоминание", reminder);
    renderBanner(reminder);
    loadReminders();
  });
}

async function login() {
  const body = new URLSearchParams({
    username: $("emailInput").value.trim(),
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
  updateAuthStatus();
  connectSocket();
  log("Вход выполнен");
  await Promise.all([loadForms(), loadReminders()]);
}

async function register() {
  const data = await request("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email: $("emailInput").value.trim(),
      password: $("passwordInput").value,
    }),
  });
  showOutput("authOutput", data);
  log("Аккаунт создан. Теперь нужно подтвердить почту.", data);
}

async function requestCode() {
  const data = await request("/auth/verify-email/request", {
    method: "POST",
    body: JSON.stringify({ email: $("emailInput").value.trim() }),
  });
  showOutput("authOutput", data);
  log("Код подтверждения отправлен", data);
}

async function confirmCode() {
  const data = await request("/auth/verify-email/confirm", {
    method: "POST",
    body: JSON.stringify({
      email: $("emailInput").value.trim(),
      code: $("codeInput").value.trim(),
    }),
  });
  showOutput("authOutput", data);
  log("Почта подтверждена", data);
}

async function loadForms() {
  forms = await request("/forms");
  renderForms();
  renderFormOptions();
  setStep("stepForms", forms.length ? "done" : "");
  log("Формы загружены", { count: forms.length });
}

function renderForms() {
  const host = $("formsList");
  host.innerHTML = "";

  if (!forms.length) {
    host.innerHTML = '<div class="result muted">Форм пока нет. Создай первую форму активности.</div>';
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
      <div class="meta">${escapeHtml(form.description || "Без описания")}</div>
      <div class="meta">Время: ${formatScheduleTimes(form.schedule_crons).map(escapeHtml).join(", ") || "не задано"}</div>
      <div class="meta">Статус напоминаний: ${form.reminder_enabled ? "включены" : "выключены"}</div>
      <div class="actions">
        <button class="secondary" data-action="select-form" data-id="${form.form_id}">Использовать эту форму</button>
      </div>
    `;
    host.appendChild(item);
  }
}

function renderScheduleTimes() {
  const host = $("scheduleTimesHost");
  host.innerHTML = "";

  scheduleTimes.forEach((time, index) => {
    const row = document.createElement("span");
    row.className = `time-row${scheduleTimes.length === 1 ? " single" : ""}`;
    const removeButton =
      scheduleTimes.length > 1
        ? `<button class="ghost small" type="button" data-action="remove-schedule-time" data-index="${index}">Удалить</button>`
        : "";
    row.innerHTML = `
      <input class="schedule-time-input" type="time" value="${escapeHtml(time)}" aria-label="Время напоминания ${index + 1}" />
      ${removeButton}
    `;
    host.appendChild(row);
  });
}

function addScheduleTime() {
  scheduleTimes.push("20:00");
  renderScheduleTimes();
  const inputs = document.querySelectorAll(".schedule-time-input");
  inputs[inputs.length - 1]?.focus();
}

function syncScheduleTimesFromInputs() {
  scheduleTimes = [...document.querySelectorAll(".schedule-time-input")]
    .map((input) => input.value.trim())
    .filter(Boolean);
}

function renderFormOptions() {
  const selects = [$("answerFormSelect"), $("reminderFormSelect")];
  const previousValue = $("answerFormSelect").value || $("reminderFormSelect").value;

  for (const select of selects) {
    select.innerHTML = "";

    for (const form of forms) {
      const option = document.createElement("option");
      option.value = form.form_id;
      option.textContent = `#${form.form_id} - ${form.title}`;
      select.appendChild(option);
    }

    if (previousValue && forms.some((form) => String(form.form_id) === previousValue)) {
      select.value = previousValue;
    }
  }

  updateSelectedFormInfo();
}

function updateSelectedFormInfo() {
  const formId = Number($("answerFormSelect").value);
  const form = forms.find((item) => item.form_id === formId);

  if (!form) {
    setResult("selectedFormInfo", "Форма пока не выбрана.", "muted");
    setResult("reminderTargetInfo", "Сначала выбери или создай форму в шаге 3.", "muted");
    return;
  }

  $("reminderFormSelect").value = String(form.form_id);
  renderSelectedFormCard(form);
  setResult(
    "reminderTargetInfo",
    `Напоминание будет создано для формы #${form.form_id}: ${form.title}.`,
  );
}

function renderSelectedFormCard(form) {
  const times = formatScheduleTimes(form.schedule_crons);
  $("selectedFormInfo").className = "selected-form-card";
  $("selectedFormInfo").innerHTML = `
    <div class="selected-form-main">
      <div>
        <div class="mini-label">Сейчас тестируем</div>
        <strong>#${form.form_id} - ${escapeHtml(form.title)}</strong>
      </div>
    </div>
    <div class="selected-form-section">
      <div class="mini-label">Время напоминаний</div>
      <div class="time-chips">
        ${
          times.length
            ? times.map((time) => `<span class="time-chip">${escapeHtml(time)}</span>`).join("")
            : '<span class="muted-text">не задано</span>'
        }
      </div>
    </div>
  `;
}

function formatScheduleTimes(scheduleCrons = []) {
  return scheduleCrons
    .map((value) => String(value).replace(/^daily\s+/i, "").trim())
    .filter(Boolean);
}

function updateReminderFormSelection() {
  const formId = Number($("reminderFormSelect").value);
  const form = forms.find((item) => item.form_id === formId);

  if (!form) {
    setResult("reminderTargetInfo", "Сначала выбери или создай форму в шаге 3.", "muted");
    return;
  }

  $("answerFormSelect").value = String(form.form_id);
  updateSelectedFormInfo();
}

async function createForm() {
  const title = $("formTitleInput").value.trim();
  const skipDelay = Number($("skipDelayInput").value);
  const maxMinutes = Number($("maxHoursInput").value || 0) * 60;
  const scheduleCrons = buildScheduleCrons();

  if (!title) throw new Error("Введите название активности.");
  if (maxMinutes <= 0) throw new Error("Лимит ответа по длительности должен быть больше нуля.");
  if (!scheduleCrons.length) throw new Error("Добавьте хотя бы одно время напоминания.");

  const data = await request("/forms", {
    method: "POST",
    body: JSON.stringify({
      title,
      description: "Создано из локального тестового сценария",
      form_structure: {
        fields: [
          {
            name: "minutes",
            label: "Длительность занятия в минутах",
            type: "number",
            required: true,
            min: 0,
            max: maxMinutes,
          },
          {
            name: "mood",
            label: "Настроение",
            type: "select",
            options: ["terrible", "bad", "tired", "ok", "calm", "good", "great", "focused", "inspired"],
          },
        ],
      },
      schedule_crons: scheduleCrons,
      is_active: true,
      reminder_enabled: true,
      reminder_title: `Сколько времени: ${title.toLowerCase()}?`,
      reminder_payload: { activity: title },
      skip_retry_delay_seconds: skipDelay,
      delivery_retry_delay_seconds: skipDelay,
    }),
  });

  log("Форма создана", data);
  await loadForms();
  $("answerFormSelect").value = data.form_id;
  updateSelectedFormInfo();
}

function buildScheduleCrons() {
  syncScheduleTimesFromInputs();
  return scheduleTimes
    .filter(Boolean)
    .map((time) => `daily ${time}`);
}

async function loadReminders() {
  reminders = await request("/reminders?limit=20");
  renderReminders();
  if (reminders.length) setStep("stepReminder", "done");
  log("Напоминания загружены", { count: reminders.length });
}

function renderReminders() {
  const host = $("remindersList");
  const historyHost = $("reminderHistoryList");
  const activeReminders = reminders.filter((reminder) => isActiveReminder(reminder));
  const historyReminders = reminders.filter((reminder) => !isActiveReminder(reminder));

  host.innerHTML = "";
  historyHost.innerHTML = "";

  if (!activeReminders.length) {
    host.innerHTML = '<div class="result muted">Напоминаний пока нет. Нажми “Спросить сейчас”.</div>';
  }

  for (const reminder of activeReminders) {
    host.appendChild(createReminderItem(reminder, true));
  }

  if (!historyReminders.length) {
    historyHost.innerHTML = '<div class="result muted">История пока пустая.</div>';
  }

  for (const reminder of historyReminders) {
    historyHost.appendChild(createReminderItem(reminder, false));
  }

  $("toggleReminderHistoryBtn").textContent = reminderHistoryVisible
    ? `Скрыть историю (${historyReminders.length})`
    : `Показать историю (${historyReminders.length})`;
  $("reminderHistoryBlock").classList.toggle("hidden", !reminderHistoryVisible);
}

function createReminderItem(reminder, withActions) {
  const item = document.createElement("div");
  item.className = `item${withActions ? "" : " history-item"}`;
  item.innerHTML = `
    <div class="item-title">
      <span>${escapeHtml(reminder.title)}</span>
      <span class="pill muted">${translateStatus(reminder.status)}</span>
    </div>
    <div class="meta">Форма: ${reminder.form_id || "нет"} | очередь: ${translateEnqueue(reminder.enqueue_status)}</div>
    <div class="meta">${withActions ? "Следующий показ" : "Дата"}: ${formatDate(reminder.next_run_at)}</div>
    ${
      withActions
        ? `<div class="actions">
            <button class="secondary" data-action="skip" data-id="${reminder.id}">Позже на 30 минут</button>
            <button class="secondary" data-action="complete" data-id="${reminder.id}">Готово</button>
            <button class="ghost" data-action="cancel" data-id="${reminder.id}">Отменить</button>
          </div>`
        : ""
    }
  `;
  return item;
}

function isActiveReminder(reminder) {
  return reminder.status === "pending";
}

function toggleReminderHistory() {
  reminderHistoryVisible = !reminderHistoryVisible;
  renderReminders();
}

async function createReminderNow() {
  const formId = Number($("reminderFormSelect").value || $("answerFormSelect").value || forms[0]?.form_id);
  if (!formId) throw new Error("Сначала создай или выбери форму.");

  const form = forms.find((item) => item.form_id === formId);
  const data = await request("/reminders", {
    method: "POST",
    body: JSON.stringify({
      title: form?.reminder_title || "Пора заполнить активность",
      form_id: formId,
      payload: { source: "test_frontend", activity: form?.title },
      retry_delay_seconds: Number($("skipDelayInput").value),
      due_in_seconds: Number($("manualDelayInput").value),
    }),
  });

  log("Напоминание создано", data);
  renderBanner(data);
  setStep("stepReminder", "done");
  await loadReminders();
}

function renderBanner(reminder) {
  const host = $("bannerHost");
  host.innerHTML = "";

  const banner = document.createElement("div");
  banner.className = "banner";
  banner.innerHTML = `
    <strong>${escapeHtml(reminder.title)}</strong>
    <div class="meta">Напоминание #${reminder.id}. Проверь кнопки ниже или заполни форму на следующем шаге.</div>
    <div class="actions">
      <button data-action="fill" data-id="${reminder.id}" data-form="${reminder.form_id || ""}">Перейти к ответу</button>
      <button class="secondary" data-action="skip" data-id="${reminder.id}">Спросить через 30 минут</button>
      <button class="secondary" data-action="complete" data-id="${reminder.id}">Готово</button>
      <button class="ghost" data-action="cancel" data-id="${reminder.id}">Отменить</button>
    </div>
  `;
  host.appendChild(banner);
}

async function reminderAction(action, id) {
  const options = { method: "POST" };
  if (action === "skip") {
    options.body = JSON.stringify({ retry_delay_seconds: 1800 });
  }

  const data = await request(`/reminders/${id}/${action}`, options);
  log(`Действие с напоминанием: ${translateAction(action)}`, data);
  $("bannerHost").innerHTML = "";
  await loadReminders();
}

async function submitAnswer() {
  const formId = Number($("answerFormSelect").value);
  if (!formId) throw new Error("Сначала создай или выбери форму.");
  const totalMinutes = Number($("hoursInput").value || 0) * 60 + Number($("minutesInput").value || 0);
  const mood = $("moodInput").value;

  const data = await request(`/forms/${formId}/answers`, {
    method: "POST",
    body: JSON.stringify({
      answers_data: {
        minutes: totalMinutes,
        mood,
      },
    }),
  });

  showOutput("answerOutput", data);
  addAnswerHistoryItem(formId, totalMinutes, mood);
  setStep("stepAnswer", "done");
  log("Ответ сохранен", data);
  await loadReminders();
}

function addAnswerHistoryItem(formId, totalMinutes, mood) {
  const form = forms.find((item) => item.form_id === formId);
  answerHistory.unshift({
    formId,
    formTitle: form?.title || `Форма #${formId}`,
    minutes: totalMinutes,
    mood,
    createdAt: new Date(),
  });
  answerHistoryVisible = true;
  renderAnswerHistory();
}

function renderAnswerHistory() {
  const host = $("answerHistoryList");
  host.innerHTML = "";

  if (!answerHistory.length) {
    host.innerHTML = '<div class="result muted">Ответов пока нет. Сохрани активность, и она появится здесь.</div>';
  }

  for (const answer of answerHistory) {
    const item = document.createElement("div");
    item.className = "item answer-item";
    item.innerHTML = `
      <div class="item-title">
        <span>${escapeHtml(answer.formTitle)}</span>
        <span class="pill muted">${formatDuration(answer.minutes)}</span>
      </div>
      <div class="meta">Настроение: ${escapeHtml(translateMood(answer.mood))}</div>
      <div class="meta">Сохранено: ${formatDate(answer.createdAt)}</div>
    `;
    host.appendChild(item);
  }

  $("toggleAnswerHistoryBtn").textContent = answerHistoryVisible
    ? `Скрыть историю ответов (${answerHistory.length})`
    : `Показать историю ответов (${answerHistory.length})`;
  $("answerHistoryBlock").classList.toggle("hidden", !answerHistoryVisible);
}

function toggleAnswerHistory() {
  answerHistoryVisible = !answerHistoryVisible;
  renderAnswerHistory();
}

async function loadStats() {
  const formId = Number($("answerFormSelect").value);
  if (!formId) throw new Error("Сначала создай или выбери форму.");

  const data = await request(`/forms/${formId}/answers/stats`);
  showOutput("answerOutput", data);
  setStep("stepAnswer", "done");
  log("Статистика загружена", data);
}

function logout() {
  token = "";
  localStorage.removeItem("pingme_token");
  if (socket) socket.disconnect();
  setPill("socketStatus", "Realtime выключен", "muted");
  $("authOutput").textContent = "Вы вышли из аккаунта.";
  updateAuthStatus();
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

function formatDate(value) {
  if (!value) return "не задан";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU");
}

function formatError(error) {
  if (error?.payload?.detail) return `Ошибка ${error.status}: ${JSON.stringify(error.payload.detail)}`;
  if (error?.payload) return `Ошибка ${error.status || ""}: ${JSON.stringify(error.payload)}`;
  return error?.message || String(error);
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
  }[status] || status || "нет";
}

function translateAction(action) {
  return {
    skip: "позже",
    complete: "готово",
    cancel: "отмена",
  }[action] || action;
}

function translateMood(mood) {
  return {
    terrible: "ужасно",
    bad: "плохо",
    tired: "устал",
    ok: "нормально",
    calm: "спокойно",
    good: "хорошо",
    great: "отлично",
    focused: "сфокусирован",
    inspired: "вдохновлен",
  }[mood] || mood;
}

function formatDuration(totalMinutes) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours && minutes) return `${hours} ч ${minutes} мин`;
  if (hours) return `${hours} ч`;
  return `${minutes} мин`;
}

function bind(id, handler) {
  $(id).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;

    try {
      await handler();
    } catch (error) {
      const message = formatError(error);
      log("Ошибка", error.payload || { message });
      if (id.includes("health")) {
        setResult("healthResult", message, "bad");
      }
    } finally {
      button.disabled = false;
    }
  });
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;

  const action = target.dataset.action;
  const id = target.dataset.id;

  try {
    if (action === "select-form") {
      $("answerFormSelect").value = id;
      updateSelectedFormInfo();
      log("Форма выбрана", { form_id: Number(id) });
      return;
    }

    if (action === "remove-schedule-time") {
      syncScheduleTimesFromInputs();
      scheduleTimes.splice(Number(target.dataset.index), 1);
      if (!scheduleTimes.length) scheduleTimes = ["20:00"];
      renderScheduleTimes();
      return;
    }

    if (action === "fill") {
      if (target.dataset.form) $("answerFormSelect").value = target.dataset.form;
      updateSelectedFormInfo();
      $("stepAnswer").scrollIntoView({ behavior: "smooth", block: "start" });
      $("hoursInput").focus();
      return;
    }

    await reminderAction(action, id);
  } catch (error) {
    log("Ошибка", error.payload || { message: formatError(error) });
  }
});

$("answerFormSelect").addEventListener("change", updateSelectedFormInfo);
$("reminderFormSelect").addEventListener("change", updateReminderFormSelection);
$("clearLogBtn").addEventListener("click", () => {
  $("logOutput").textContent = "";
});

bind("healthBtn", checkHealth);
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
bind("addScheduleTimeBtn", addScheduleTime);
bind("toggleReminderHistoryBtn", toggleReminderHistory);
bind("toggleAnswerHistoryBtn", toggleAnswerHistory);

updateAuthStatus();
renderScheduleTimes();
renderAnswerHistory();
checkHealth().catch(() => {});

if (token) {
  connectSocket();
  Promise.allSettled([loadForms(), loadReminders()]).then(() => updateAuthStatus());
}
