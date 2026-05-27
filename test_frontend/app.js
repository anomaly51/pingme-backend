const API_BASE = "http://localhost:8000";

let token = localStorage.getItem("pingme_token") || "";
let forms = [];
let formGroups = [];
let reminders = [];
let socket = null;
let scheduleTimes = ["20:00"];
let formFields = [];
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
  await loadFormGroups();
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

async function loadForms(selectedFormId = null) {
  forms = await request("/forms");
  renderForms();
  renderFormOptions(selectedFormId);
  renderGroupFormOptions();
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
        <button data-action="answer-form" data-id="${form.form_id}">Ответить</button>
        <button class="ghost danger" data-action="delete-form" data-id="${form.form_id}">Удалить</button>
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
  renderScheduleCrons();
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
  renderScheduleCrons();
}

function renderScheduleCrons() {
  if (!$("scheduleCronsInput")) return;
  const crons = scheduleTimes.filter(Boolean).map((time) => `daily ${time}`);
  $("scheduleCronsInput").value = JSON.stringify(crons, null, 2);
  $("scheduleCronsInput").scrollTop = 0;
}

function renderFormOptions(selectedFormId = null) {
  const selects = [$("answerFormSelect"), $("reminderFormSelect")];
  const previousValue = selectedFormId
    ? String(selectedFormId)
    : $("answerFormSelect").value || $("reminderFormSelect").value;

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

function selectForm(formId, scrollToAnswer = false) {
  const value = String(formId);
  $("answerFormSelect").value = value;
  $("reminderFormSelect").value = value;
  updateSelectedFormInfo();
  if (scrollToAnswer) {
    $("stepAnswer").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderGroupFormOptions() {
  const select = $("groupFormsSelect");
  const selected = new Set([...select.selectedOptions].map((option) => option.value));
  select.innerHTML = "";

  for (const form of forms) {
    const option = document.createElement("option");
    option.value = form.form_id;
    option.textContent = `#${form.form_id} - ${form.title}`;
    option.selected = selected.has(String(form.form_id)) || selected.size === 0;
    select.appendChild(option);
  }
}

async function loadFormGroups() {
  if (!token) return;
  formGroups = await request("/form-groups");
  renderFormGroups();
  renderGroupOptions();
  log("Группы форм загружены", { count: formGroups.length });
}

function renderGroupOptions() {
  const selects = [$("answerGroupSelect"), $("reminderGroupSelect")].filter(Boolean);
  const previousValue = $("answerGroupSelect").value || $("reminderGroupSelect")?.value;

  for (const select of selects) {
    select.innerHTML = "";

    for (const group of formGroups) {
      const option = document.createElement("option");
      option.value = group.group_id;
      option.textContent = `#${group.group_id} - ${group.title}`;
      select.appendChild(option);
    }

    if (previousValue && formGroups.some((group) => String(group.group_id) === previousValue)) {
      select.value = previousValue;
    }
  }

  buildGroupAnswerJson();
}

function renderFormGroups() {
  const host = $("groupsList");
  host.innerHTML = "";

  if (!formGroups.length) {
    host.innerHTML = '<div class="result muted">Групп пока нет. Выбери несколько форм и создай группу.</div>';
    return;
  }

  for (const group of formGroups) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <div class="item-title">
        <span>${escapeHtml(group.title)}</span>
        <span class="pill muted">#${group.group_id}</span>
      </div>
      <div class="meta">Формы: ${group.form_ids.map((id) => `#${id}`).join(", ")}</div>
      <div class="actions">
        <button class="secondary" data-action="select-group" data-id="${group.group_id}">Использовать группу</button>
      </div>
    `;
    host.appendChild(item);
  }
}

function updateSelectedFormInfo() {
  const formId = Number($("answerFormSelect").value);
  const form = forms.find((item) => item.form_id === formId);

  if (!form) {
    setResult("selectedFormInfo", "Форма пока не выбрана.", "muted");
    setResult("reminderTargetInfo", "Сначала выбери или создай форму в шаге 3.", "muted");
    $("dynamicAnswerHost").innerHTML = "";
    return;
  }

  $("reminderFormSelect").value = String(form.form_id);
  renderSelectedFormCard(form);
  renderDynamicAnswerForm(form);
  buildAnswerJson();
  setResult(
    "reminderTargetInfo",
    `Напоминание будет создано для формы #${form.form_id}: ${form.title}.`,
  );
}

function renderSelectedFormCard(form) {
  const times = formatScheduleTimes(form.schedule_crons);
  const fields = getFormFields(form);
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
    <div class="selected-form-section">
      <div class="mini-label">Поля</div>
      <div class="field-chips">
        ${
          fields.length
            ? fields.map((field) => `<span class="time-chip">${escapeHtml(field.label || field.name)}</span>`).join("")
            : '<span class="muted-text">сырой JSON без fields/components</span>'
        }
      </div>
    </div>
  `;
}

function getFormFields(form) {
  const structure = form?.form_structure || {};
  const fields = Array.isArray(structure.fields)
    ? structure.fields
    : Array.isArray(structure.components)
      ? structure.components
      : [];
  return fields.filter((field) => field && typeof field === "object" && field.name);
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

function updateReminderGroupSelection() {
  const groupId = Number($("reminderGroupSelect").value);
  const group = formGroups.find((item) => item.group_id === groupId);

  if (!group) {
    setResult("reminderTargetInfo", "Сначала выбери или создай группу форм.", "muted");
    return;
  }

  $("answerGroupSelect").value = String(group.group_id);
  buildGroupAnswerJson();
  setResult(
    "reminderTargetInfo",
    `Напоминание будет создано для группы #${group.group_id}: ${group.title}.`,
  );
}

function setFormPreset(kind) {
  if (kind === "expenses") {
    $("formTitleInput").value = "Траты за день";
    setFieldEditorValues("comment", "Комментарий", "text", "", false);
    formFields = [
      {
        name: "amount",
        label: "Сколько потратил?",
        type: "number",
        required: true,
        min: 0,
      },
      {
        name: "category",
        label: "Категория",
        type: "multiselect",
        options: ["еда", "транспорт", "развлечения", "дом", "другое"],
      },
      {
        name: "need_reduce_spending",
        label: "Нужно экономить?",
        type: "boolean",
      },
    ];
  } else if (kind === "mood") {
    $("formTitleInput").value = "Настроение";
    setFieldEditorValues("sleep_hours", "Сон, часы", "number", "0, 24", false);
    formFields = [
      {
        name: "mood",
        label: "Настроение",
        type: "select",
        options: ["ужасно", "плохо", "нормально", "хорошо", "отлично"],
        required: true,
      },
      {
        name: "energy",
        label: "Энергия",
        type: "range",
        min: 0,
        max: 10,
      },
      {
        name: "note",
        label: "Комментарий",
        type: "text",
      },
    ];
  } else if (kind === "guitar") {
    $("formTitleInput").value = "Игра на гитаре";
    setFieldEditorValues("song", "Что играл?", "text", "", false);
    formFields = [
      {
        name: "minutes",
        label: "Длительность занятия в минутах",
        type: "number",
        required: true,
        min: 0,
        max: Number($("maxHoursInput").value || 10) * 60,
      },
      {
        name: "mood",
        label: "Настроение",
        type: "select",
        options: ["terrible", "bad", "tired", "ok", "calm", "good", "great", "focused", "inspired"],
      },
      {
        name: "progress",
        label: "Прогресс",
        type: "range",
        min: 0,
        max: 10,
      },
    ];
  } else {
    $("formTitleInput").value = "Новая форма";
    setFieldEditorValues("field_1", "Первое поле", "text", "", false);
    formFields = [];
  }
  renderFields();
  setResult("fieldEditorResult", "Можно добавить новое поле или удалить существующее.", "muted");
}

function setFieldEditorValues(name, label, type, options, required) {
  $("fieldNameInput").value = name;
  delete $("fieldNameInput").dataset.touched;
  $("fieldLabelInput").value = label;
  $("fieldTypeInput").value = type;
  $("fieldOptionsInput").value = options;
  $("fieldRequiredInput").checked = required;
}

function slugifyFieldName(value) {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_+|_+$/g, "");
  const translit = {
    сколько: "amount",
    потратил: "spent",
    настроение: "mood",
    комментарий: "comment",
    сон: "sleep",
    часы: "hours",
    энергия: "energy",
  }[normalized];
  const slug = translit || normalized.replace(/[^\w]/g, "");
  return /^[a-zA-Z_]/.test(slug) ? slug : `field_${formFields.length + 1}`;
}

function addFieldFromInputs() {
  const name = $("fieldNameInput").value.trim();
  const label = $("fieldLabelInput").value.trim() || name;
  const type = $("fieldTypeInput").value;

  if (!name) throw new Error("Укажи ключ поля.");
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) {
    throw new Error("Ключ поля должен быть похож на amount или mood_score.");
  }
  if (formFields.some((field) => field.name === name)) {
    throw new Error(`Поле ${name} уже есть.`);
  }

  formFields.push(buildFieldFromInputs(name, label, type));
  renderFields();
  setResult("fieldEditorResult", `Поле ${name} добавлено.`, "");
  setFieldEditorValues(nextFieldName(), "", "text", "", false);
}

function nextFieldName() {
  let index = formFields.length + 1;
  let name = `field_${index}`;
  while (formFields.some((field) => field.name === name)) {
    index += 1;
    name = `field_${index}`;
  }
  return name;
}

function buildFieldFromInputs(name, label, type) {
  const optionsRaw = $("fieldOptionsInput").value.trim();
  const field = {
    name,
    label,
    type,
  };
  if ($("fieldRequiredInput").checked) field.required = true;

  if (type === "select" || type === "multiselect") {
    field.options = optionsRaw
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  }
  if (type === "range" || type === "number") {
    const [minRaw, maxRaw] = optionsRaw.split(",").map((value) => value.trim());
    const min = Number(minRaw);
    const max = Number(maxRaw);
    if (Number.isFinite(min)) field.min = min;
    if (Number.isFinite(max)) field.max = max;
  }
  return field;
}

function renderFields() {
  const host = $("fieldsList");
  host.innerHTML = "";

  if (!formFields.length) {
    host.innerHTML = '<div class="result muted">Полей пока нет. Добавь поле или выбери preset.</div>';
  }

  formFields.forEach((field, index) => {
    const item = document.createElement("div");
    item.className = "field-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(field.label || field.name)}</strong>
        <div class="meta">${escapeHtml(field.name)} · ${escapeHtml(field.type)}${field.required ? " · required" : ""}</div>
      </div>
      <button class="ghost small" type="button" data-action="remove-field" data-index="${index}">Удалить</button>
    `;
    host.appendChild(item);
  });

  renderFormStructureJson();
  renderFormPreview();
}

function renderFormPreview() {
  const host = $("formPreviewHost");
  if (!host) return;

  if (!formFields.length) {
    host.innerHTML = '<div class="result muted">Добавь поле, и здесь появится предпросмотр формы.</div>';
    return;
  }

  host.innerHTML = "";
  const grid = document.createElement("div");
  grid.className = "dynamic-grid";
  for (const field of formFields) {
    const previewField = createDynamicField(field);
    for (const control of previewField.querySelectorAll("[data-answer-field]")) {
      delete control.dataset.answerField;
      delete control.dataset.answerType;
      control.disabled = true;
    }
    grid.appendChild(previewField);
  }
  host.appendChild(grid);
}

function renderFormStructureJson() {
  if (!$("formStructureInput")) return;
  const structure = {
    version: 1,
    components: formFields.map((field) => ({ ...field })),
    fields: formFields.map((field) => ({ ...field })),
  };
  $("formStructureInput").value = JSON.stringify(structure, null, 2);
  $("formStructureInput").scrollTop = 0;
}

function parseFormStructureJson() {
  const data = parseJsonObject("formStructureInput", "JSON структуры формы");
  return data;
}

function parseScheduleCronsJson() {
  let data;
  try {
    data = JSON.parse($("scheduleCronsInput").value);
  } catch (error) {
    throw new Error(`CRON JSON невалидный: ${error.message}`);
  }
  if (!Array.isArray(data) || data.some((item) => typeof item !== "string")) {
    throw new Error("CRON должен быть JSON-массивом строк.");
  }
  return data;
}

async function createForm() {
  const title = $("formTitleInput").value.trim();
  const skipDelay = Number($("skipDelayInput").value);
  const formStructure = parseFormStructureJson();
  const scheduleCrons = parseScheduleCronsJson();

  if (!title) throw new Error("Введите название активности.");
  if (!scheduleCrons.length) throw new Error("Добавьте хотя бы одно время или CRON строку.");

  const data = await request("/forms", {
    method: "POST",
    body: JSON.stringify({
      title,
      description: "Создано из универсального локального конструктора",
      form_structure: formStructure,
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
  await loadForms(data.form_id);
  selectForm(data.form_id, true);
  setResult("selectedFormInfo", `Создана и выбрана форма #${data.form_id}: ${title}.`);
}

async function createGuitarForm() {
  setFormPreset("guitar");
  $("formTitleInput").value = $("quickTitleInput").value.trim() || "Быстрая форма";
  await createForm();
}

async function createFormGroup() {
  const title = $("groupTitleInput").value.trim();
  const formIds = [...$("groupFormsSelect").selectedOptions].map((option) => Number(option.value));

  if (!title) throw new Error("Введите название группы.");
  if (!formIds.length) throw new Error("Выбери хотя бы одну форму для группы.");

  const data = await request("/form-groups", {
    method: "POST",
    body: JSON.stringify({
      title,
      description: "Группа из локального тестового интерфейса",
      form_ids: formIds,
      schedule_crons: parseScheduleCronsJson(),
      reminder_enabled: true,
      reminder_title: title,
      reminder_payload: { source: "test_frontend", form_ids: formIds },
      skip_retry_delay_seconds: Number($("skipDelayInput").value),
      delivery_retry_delay_seconds: Number($("skipDelayInput").value),
    }),
  });

  log("Группа форм создана", data);
  await loadFormGroups();
  $("answerGroupSelect").value = data.group_id;
  buildGroupAnswerJson();
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
    <div class="meta">Форма: ${reminder.form_id || "нет"} | группа: ${reminder.form_group_id || "нет"} | очередь: ${translateEnqueue(reminder.enqueue_status)}</div>
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

async function createGroupReminderNow() {
  const groupId = Number($("reminderGroupSelect").value || $("answerGroupSelect").value || formGroups[0]?.group_id);
  if (!groupId) throw new Error("Сначала создай или выбери группу форм.");

  const group = formGroups.find((item) => item.group_id === groupId);
  const data = await request("/reminders", {
    method: "POST",
    body: JSON.stringify({
      title: group?.reminder_title || group?.title || "Пора заполнить группу форм",
      form_group_id: groupId,
      payload: { source: "test_frontend", group_title: group?.title },
      retry_delay_seconds: Number($("skipDelayInput").value),
      due_in_seconds: Number($("manualDelayInput").value),
    }),
  });

  log("Групповое напоминание создано", data);
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
      <button data-action="fill" data-id="${reminder.id}" data-form="${reminder.form_id || ""}" data-group="${reminder.form_group_id || ""}">Перейти к ответу</button>
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

function renderDynamicAnswerForm(form) {
  const host = $("dynamicAnswerHost");
  const fields = getFormFields(form);
  host.innerHTML = "";

  if (!fields.length) {
    host.innerHTML = '<div class="result muted">У выбранной формы нет описанных fields/components. Заполни JSON ответа вручную.</div>';
    return;
  }

  const grid = document.createElement("div");
  grid.className = "dynamic-grid";
  for (const field of fields) {
    grid.appendChild(createDynamicField(field));
  }
  host.appendChild(grid);

  const actions = document.createElement("div");
  actions.className = "actions";
  actions.innerHTML = '<button id="syncDynamicAnswerBtn" class="secondary" type="button">Собрать JSON из полей</button>';
  host.appendChild(actions);
  $("syncDynamicAnswerBtn").addEventListener("click", syncAnswerJsonFromDynamicFields);
}

function createDynamicField(field) {
  const label = document.createElement("label");
  const title = field.label || field.name;
  label.textContent = title;

  const type = normalizeFieldType(field.type);
  let control;
  if (type === "select") {
    control = document.createElement("select");
    for (const optionValue of field.options || []) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      control.appendChild(option);
    }
  } else if (type === "multiselect") {
    control = document.createElement("select");
    control.multiple = true;
    control.size = Math.min(Math.max((field.options || []).length, 2), 5);
    for (const optionValue of field.options || []) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      option.selected = true;
      control.appendChild(option);
    }
  } else if (type === "boolean") {
    label.className = "checkbox-label dynamic-checkbox";
    control = document.createElement("input");
    control.type = "checkbox";
    control.checked = true;
  } else {
    control = document.createElement("input");
    control.type = {
      number: "number",
      range: "range",
      date: "date",
      time: "time",
      text: "text",
    }[type] || "text";
    if (field.min !== undefined) control.min = field.min;
    if (field.max !== undefined) control.max = field.max;
    control.value = defaultFieldValue(field, type);
  }

  control.dataset.answerField = field.name;
  control.dataset.answerType = type;
  label.appendChild(control);
  return label;
}

function normalizeFieldType(type) {
  if (type === "checkbox") return "boolean";
  if (["text", "number", "select", "multiselect", "boolean", "date", "time", "range"].includes(type)) return type;
  return "text";
}

function defaultFieldValue(field, type) {
  if (type === "number") return field.name.includes("amount") ? "42.5" : "1";
  if (type === "range") return String(Math.round(((Number(field.min) || 0) + (Number(field.max) || 10)) / 2));
  if (type === "date") return new Date().toISOString().slice(0, 10);
  if (type === "time") return "20:00";
  return "";
}

function syncAnswerJsonFromDynamicFields() {
  const data = {};
  for (const control of document.querySelectorAll("[data-answer-field]")) {
    const key = control.dataset.answerField;
    const type = control.dataset.answerType;
    if (type === "boolean") data[key] = control.checked;
    else if (type === "multiselect") {
      data[key] = [...control.selectedOptions].map((option) => option.value);
    }
    else if (type === "number" || type === "range") data[key] = Number(control.value);
    else data[key] = control.value;
  }
  $("answerJsonInput").value = JSON.stringify(data, null, 2);
}

async function submitAnswer() {
  const formId = Number($("answerFormSelect").value);
  if (!formId) throw new Error("Сначала создай или выбери форму.");
  const answersData = parseAnswerJson();

  const data = await request("/answers", {
    method: "POST",
    body: JSON.stringify({
      form_id: formId,
      answers_data: answersData,
    }),
  });

  showOutput("answerOutput", data);
  addAnswerHistoryItem(formId, answersData);
  setStep("stepAnswer", "done");
  log("Ответ сохранен", data);
  await loadReminders();
}

function buildAnswerJson() {
  const totalMinutes = Number($("hoursInput").value || 0) * 60 + Number($("minutesInput").value || 0);
  const mood = $("moodInput").value;
  const formId = Number($("answerFormSelect").value);
  const form = forms.find((item) => item.form_id === formId);
  const fields = getFormFields(form);

  if (fields.length) {
    const payload = buildExampleAnswersData(form);
    $("answerJsonInput").value = JSON.stringify(payload, null, 2);
    $("answerJsonInput").scrollTop = 0;
    renderDynamicAnswerForm(form);
    return;
  }

  const payload = {
    minutes: totalMinutes,
    mood,
    random_question_1: mood === "good" || mood === "great" ? "Good" : "Mixed",
    slider_value: Math.min(10, Math.max(0, Math.round(totalMinutes / 12))),
    source: "test_frontend",
    form_title: form?.title || null,
    nested_example: {
      checked: true,
      tags: ["raw-json", "no-field-validation"],
    },
  };

  $("answerJsonInput").value = JSON.stringify(payload, null, 2);
  $("answerJsonInput").scrollTop = 0;
}

function buildGroupAnswerJson() {
  const groupId = Number($("answerGroupSelect").value);
  const group = formGroups.find((item) => item.group_id === groupId);

  if (!group) {
    $("groupAnswerJsonInput").value = JSON.stringify({ answers: [] }, null, 2);
    $("groupAnswerJsonInput").scrollTop = 0;
    return;
  }

  const payload = {
    answers: group.forms.map((form) => ({
      form_id: form.form_id,
      answers_data: buildExampleAnswersData(form),
    })),
  };
  $("groupAnswerJsonInput").value = JSON.stringify(payload, null, 2);
  $("groupAnswerJsonInput").scrollTop = 0;
}

function buildExampleAnswersData(form) {
  const data = {};
  for (const field of getFormFields(form)) {
    if (field.type === "number") data[field.name] = field.name.includes("amount") ? 42.5 : 1;
    else if (field.type === "range") data[field.name] = Number(defaultFieldValue(field, "range"));
    else if (field.type === "select") data[field.name] = field.options?.[0] || "";
    else if (field.type === "multiselect") data[field.name] = field.options?.slice(0, 2) || [];
    else if (field.type === "checkbox" || field.type === "boolean") data[field.name] = true;
    else if (field.type === "date") data[field.name] = new Date().toISOString().slice(0, 10);
    else if (field.type === "time") data[field.name] = "20:00";
    else data[field.name] = "test value";
  }
  data.raw_extra = { source: "group_test_frontend" };
  return data;
}

function parseAnswerJson() {
  return parseJsonObject("answerJsonInput", "JSON ответа");
}

function parseJsonObject(id, label) {
  let data;
  try {
    data = JSON.parse($(id).value);
  } catch (error) {
    throw new Error(`${label} невалидный: ${error.message}`);
  }
  if (!data || Array.isArray(data) || typeof data !== "object") {
    throw new Error(`${label} должен быть объектом.`);
  }
  return data;
}

function parseGroupAnswerJson() {
  let data;

  try {
    data = JSON.parse($("groupAnswerJsonInput").value);
  } catch (error) {
    throw new Error(`JSON группы невалидный: ${error.message}`);
  }

  if (!data || !Array.isArray(data.answers)) {
    throw new Error('JSON группы должен быть объектом с массивом "answers".');
  }

  return data;
}

async function submitGroupAnswer() {
  const groupId = Number($("answerGroupSelect").value);
  if (!groupId) throw new Error("Сначала создай или выбери группу.");

  const payload = parseGroupAnswerJson();
  const data = await request(`/form-groups/${groupId}/answers`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  showOutput("answerOutput", data);
  answerHistory.unshift({
    formId: `group-${groupId}`,
    formTitle: `Группа #${groupId}`,
    answersData: payload,
    createdAt: new Date(),
  });
  answerHistoryVisible = true;
  renderAnswerHistory();
  setStep("stepAnswer", "done");
  log("Групповой ответ сохранен", data);
  await loadReminders();
}

function addAnswerHistoryItem(formId, answersData) {
  const form = forms.find((item) => item.form_id === formId);
  answerHistory.unshift({
    formId,
    formTitle: form?.title || `Форма #${formId}`,
    answersData,
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
        <span class="pill muted">#${answer.formId}</span>
      </div>
      <div class="meta">JSON: ${escapeHtml(JSON.stringify(answer.answersData))}</div>
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
      if (id === "addFieldBtn") {
        setResult("fieldEditorResult", message, "bad");
      }
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
      selectForm(id);
      log("Форма выбрана", { form_id: Number(id) });
      return;
    }

    if (action === "answer-form") {
      selectForm(id, true);
      buildAnswerJson();
      log("Переход к ответу по форме", { form_id: Number(id) });
      return;
    }

    if (action === "delete-form") {
      await deleteForm(Number(id));
      return;
    }

    if (action === "select-group") {
      $("answerGroupSelect").value = id;
      $("reminderGroupSelect").value = id;
      buildGroupAnswerJson();
      log("Группа выбрана", { group_id: Number(id) });
      return;
    }

    if (action === "remove-schedule-time") {
      syncScheduleTimesFromInputs();
      scheduleTimes.splice(Number(target.dataset.index), 1);
      if (!scheduleTimes.length) scheduleTimes = ["20:00"];
      renderScheduleTimes();
      return;
    }

    if (action === "remove-field") {
      formFields.splice(Number(target.dataset.index), 1);
      renderFields();
      return;
    }

    if (action === "fill") {
      if (target.dataset.form) $("answerFormSelect").value = target.dataset.form;
      if (target.dataset.group) $("answerGroupSelect").value = target.dataset.group;
      updateSelectedFormInfo();
      buildGroupAnswerJson();
      $("stepAnswer").scrollIntoView({ behavior: "smooth", block: "start" });
      $("hoursInput").focus();
      return;
    }

    await reminderAction(action, id);
  } catch (error) {
    log("Ошибка", error.payload || { message: formatError(error) });
  }
});

async function deleteForm(formId) {
  const form = forms.find((item) => item.form_id === formId);
  const name = form?.title || `форма #${formId}`;
  if (!confirm(`Удалить форму "${name}"? Ответы и связи с группами тоже могут быть удалены.`)) {
    return;
  }

  const data = await request(`/forms/${formId}`, { method: "DELETE" });
  log("Форма удалена", data);
  await loadForms();
  await loadFormGroups();
  await loadReminders();
}

$("answerFormSelect").addEventListener("change", updateSelectedFormInfo);
$("reminderFormSelect").addEventListener("change", updateReminderFormSelection);
$("reminderGroupSelect").addEventListener("change", updateReminderGroupSelection);
$("answerGroupSelect").addEventListener("change", buildGroupAnswerJson);
$("fieldLabelInput").addEventListener("input", () => {
  if (!$("fieldNameInput").dataset.touched) {
    $("fieldNameInput").value = slugifyFieldName($("fieldLabelInput").value);
  }
});
$("fieldNameInput").addEventListener("input", () => {
  $("fieldNameInput").dataset.touched = "true";
});
$("fieldTypeInput").addEventListener("change", () => {
  const type = $("fieldTypeInput").value;
  if (type === "select" || type === "multiselect") $("fieldOptionsInput").value = "вариант 1, вариант 2, вариант 3";
  else if (type === "range" || type === "number") $("fieldOptionsInput").value = "0, 10";
  else $("fieldOptionsInput").value = "";
});
$("clearLogBtn").addEventListener("click", () => {
  $("logOutput").textContent = "";
});

bind("healthBtn", checkHealth);
bind("loginBtn", login);
bind("registerBtn", register);
bind("requestCodeBtn", requestCode);
bind("confirmCodeBtn", confirmCode);
bind("refreshFormsBtn", loadForms);
bind("addFieldBtn", addFieldFromInputs);
bind("presetExpensesBtn", () => setFormPreset("expenses"));
bind("presetMoodBtn", () => setFormPreset("mood"));
bind("presetGuitarBtn", () => setFormPreset("guitar"));
bind("presetEmptyBtn", () => setFormPreset("empty"));
bind("createFormBtn", createForm);
bind("createGuitarFormBtn", createGuitarForm);
bind("createGroupBtn", createFormGroup);
bind("refreshGroupsBtn", loadFormGroups);
bind("refreshRemindersBtn", loadReminders);
bind("createReminderBtn", createReminderNow);
bind("createGroupReminderBtn", createGroupReminderNow);
bind("buildAnswerJsonBtn", buildAnswerJson);
bind("buildGroupAnswerJsonBtn", buildGroupAnswerJson);
bind("submitAnswerBtn", submitAnswer);
bind("submitGroupAnswerBtn", submitGroupAnswer);
bind("statsBtn", loadStats);
bind("logoutBtn", logout);
bind("addScheduleTimeBtn", addScheduleTime);
bind("toggleReminderHistoryBtn", toggleReminderHistory);
bind("toggleAnswerHistoryBtn", toggleAnswerHistory);

updateAuthStatus();
setFormPreset("expenses");
renderScheduleTimes();
buildAnswerJson();
buildGroupAnswerJson();
renderAnswerHistory();
checkHealth().catch(() => {});

if (token) {
  connectSocket();
  Promise.allSettled([loadForms(), loadReminders(), loadFormGroups()]).then(() => updateAuthStatus());
}
