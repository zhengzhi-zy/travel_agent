// 旅行偏好标签配置：[后端值, 前端显示文本]
const preferenceOptions = [
  ["humanity", "人文"],
  ["art", "艺术"],
  ["nature", "自然"],
  ["food", "美食"],
  ["shopping", "购物"],
  ["nightlife", "夜生活"],
  ["family", "亲子"],
];

// 统一缓存所有DOM元素，避免重复查询，大幅提升性能
const els = {
  formPage: document.querySelector("#formPage"),
  resultPage: document.querySelector("#resultPage"),
  form: document.querySelector("#travelForm"),
  city: document.querySelector("#city"),
  startDate: document.querySelector("#startDate"),
  endDate: document.querySelector("#endDate"),
  budgetMin: document.querySelector("#budgetMin"),
  budgetMax: document.querySelector("#budgetMax"),
  extraPreferences: document.querySelector("#extraPreferences"),
  taboos: document.querySelector("#taboos"),
  travelers: document.querySelector("#travelers"),
  pace: document.querySelector("#pace"),
  hotelStyle: document.querySelector("#hotelStyle"),
  transportMode: document.querySelector("#transportMode"),
  transitPreferenceWrap: document.querySelector("#transitPreferenceWrap"),
  transitPreference: document.querySelector("#transitPreference"),
  preferenceChips: document.querySelector("#preferenceChips"),
  healthText: document.querySelector("#healthText"),
  runState: document.querySelector("#runState"),
  sourceBar: document.querySelector("#sourceBar"),
  progressPanel: document.querySelector("#progressPanel"),
  progressTitle: document.querySelector("#progressTitle"),
  progressPercent: document.querySelector("#progressPercent"),
  progressFill: document.querySelector("#progressFill"),
  progressDetail: document.querySelector("#progressDetail"),
  resultView: document.querySelector("#resultView"),
  resultNav: document.querySelector("#resultNav"),
  submitBtn: document.querySelector("#submitBtn"),
  backToFormBtn: document.querySelector("#backToFormBtn"),
};

// 存储用户选中的偏好标签，使用Set结构方便快速增删和判断存在性
const selectedPreferences = new Set(["humanity", "food"]);
const MAX_TRIP_DAYS = 7;
const LONG_TRIP_MESSAGE = "本工具适合 1-7 天轻量旅行建议，请把行程控制在 7 天以内。";
// SSE(服务器推送事件)连接对象，用于接收后端实时进度
let progressSource = null;
// 当前进度百分比，只会递增，保证用户体验流畅
let currentProgressPercent = 0;

// 规划过程的8个阶段，对应进度条的不同节点
const progressStages = [
  { percent: 8, title: "校验旅行需求", detail: "正在检查城市、日期、预算和出行方式。" },
  { percent: 18, title: "景点 Agent 规划搜索", detail: "AttractionSearchAgent 正在理解偏好和忌讳，并调用高德 POI 工具。" },
  { percent: 30, title: "天气 Agent 研究", detail: "WeatherSearchAgent 正在整理天气风险和出行建议。" },
  { percent: 42, title: "酒店 Agent 筛选", detail: "HotelSearchAgent 正在按住宿节奏和区域生成酒店候选。" },
  { percent: 55, title: "餐饮与预算交给最终 Agent", detail: "最终行程 Agent 将直接生成餐饮安排和价格估算。" },
  { percent: 68, title: "行程 Agent 编排", detail: "ItineraryPlanningAgent 正在把景点、酒店、餐饮、价格和天气合成每日行程。" },
  { percent: 82, title: "高德路线规划", detail: "正在为每天的地点链计算公交、步行、打车或自驾路线。" },
  { percent: 93, title: "整理可视化报告", detail: "正在汇总预算、风险提醒、搜索计划和详细路径。" },
];

function showPage(page) {
  els.formPage.classList.toggle("page-active", page === "form");
  els.resultPage.classList.toggle("page-active", page === "result");
}

function renderPreferenceChips() {
  els.preferenceChips.innerHTML = "";
  preferenceOptions.forEach(([value, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip ${selectedPreferences.has(value) ? "active" : ""}`;
    button.textContent = label;
    button.addEventListener("click", () => {
      if (selectedPreferences.has(value)) {
        selectedPreferences.delete(value);
      } else {
        selectedPreferences.add(value);
      }
      renderPreferenceChips();
    });
    els.preferenceChips.appendChild(button);
  });
}

// 根据出行方式控制公交偏好选项的显示/隐藏
function updateTransitPreferenceVisibility() {
  els.transitPreferenceWrap.style.display = els.transportMode.value === "public_transit" ? "grid" : "none";
}

async function loadHealth() {
  const response = await fetch("/api/health");
  const data = await response.json();
  els.healthText.textContent = data.llm_enabled
    ? `LLM 已启用 · ${data.provider}`
    : `LLM 未启用 · ${data.provider} · 当前会走本地兜底规划`;
}

function setState(text) {
  els.runState.textContent = text;
}

// 更新进度条的显示
function setProgress(stage) {
  const percent = Number(stage.percent || 0);
  currentProgressPercent = Math.max(currentProgressPercent, percent);
  els.progressPanel.hidden = false;
  els.progressTitle.textContent = stage.title || "正在规划";
  els.progressDetail.textContent = stage.detail || "后端正在处理这份旅行计划。";
  els.progressPercent.textContent = `${currentProgressPercent}%`;
  els.progressFill.style.width = `${currentProgressPercent}%`;
}

function startProgress() {
  stopProgress();
  currentProgressPercent = 0;
  setProgress({
    percent: 3,
    title: "任务已提交",
    detail: "正在连接后端真实进度通道。",
  });
}

function completeProgress() {
  stopProgress();
  currentProgressPercent = 100;
  setProgress({
    percent: 100,
    title: "旅行计划生成完成",
    detail: "报告、预算、路线和风险提醒已经整理好。",
  });
  window.setTimeout(() => {
    els.progressPanel.hidden = true;
  }, 700);
}

function failProgress() {
  stopProgress();
  setProgress({
    percent: Math.max(12, currentProgressPercent || 12),
    title: "生成过程遇到问题",
    detail: "请查看下方错误提示并返回编辑。",
  });
}

function stopProgress() {
  if (progressSource) {
    progressSource.close();
    progressSource = null;
  }
}

// 向后端发送创建规划任务的请求
async function createPlanTask(payload) {
  const response = await fetch("/api/plan/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),  // 将表单数据转为JSON字符串
  });

  if (!response.ok) {
    let errorPayload;
    try {
      errorPayload = await response.json();
    } catch {
       // 如果解析失败，使用纯文本错误信息
      errorPayload = { detail: await response.text() };
    }
    // 抛出错误，会被submitPlan函数的catch块捕获
    throw errorPayload;
  }

  return response.json();
}

// 通过SSE监听后端的实时进度和结果
function waitForPlanStream(taskId) {
  return new Promise((resolve, reject) => {
    let settled = false;
    progressSource = new EventSource(`/api/plan/stream/${encodeURIComponent(taskId)}`);

    progressSource.addEventListener("progress", (event) => {
      const data = parseSsePayload(event.data);
      if (data) {
        setProgress(data);
      }
    });

    progressSource.addEventListener("complete", (event) => {
      if (settled) return;
      settled = true;
      const data = parseSsePayload(event.data);
      completeProgress();
      resolve(data?.plan);
    });

    progressSource.addEventListener("failed", (event) => {
      if (settled) return;
      settled = true;
      const data = parseSsePayload(event.data);
      failProgress();
      reject(data || { detail: "SSE 进度通道连接失败。" });
    });

    progressSource.onerror = () => {
      if (settled) return;
      settled = true;
      failProgress();
      reject({ detail: "SSE 进度通道断开，请稍后重试。" });
    };
  });
}

function parseSsePayload(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return { detail: raw };
  }
}

// 从表单中收集数据，构建后端需要的请求格式
function buildPayload() {
  return {
    city: els.city.value.trim(),
    start_date: els.startDate.value,
    end_date: els.endDate.value,
    budget_min: Number(els.budgetMin.value),
    budget_max: Number(els.budgetMax.value),
    preferences: [...selectedPreferences],
    extra_preferences: els.extraPreferences.value.trim(),
    taboos: els.taboos.value.trim(),
    travelers: Number(els.travelers.value),
    pace: els.pace.value,
    hotel_style: els.hotelStyle.value,
    transport_mode: els.transportMode.value,
    transit_preference: els.transitPreference.value,
    departure_city: "",
  };
}

function getTripDayCount(startValue, endValue) {
  if (!startValue || !endValue) {
    return 0;
  }
  const start = new Date(`${startValue}T00:00:00`);
  const end = new Date(`${endValue}T00:00:00`);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
    return 0;
  }
  return Math.floor((end - start) / 86400000) + 1;
}

function updateDateSpanValidity({ report = false } = {}) {
  const dayCount = getTripDayCount(els.startDate.value, els.endDate.value);
  const isTooLong = dayCount > MAX_TRIP_DAYS;
  els.endDate.setCustomValidity(isTooLong ? LONG_TRIP_MESSAGE : "");
  els.submitBtn.disabled = isTooLong;
  if (report && isTooLong) {
    els.endDate.reportValidity();
  }
  return isTooLong ? { detail: LONG_TRIP_MESSAGE, focus: els.endDate } : null;
}

// 前端验证表单数据的合法性
function validatePayload(payload) {
  if (!payload.city) {
    return { detail: "请输入旅行城市。", focus: els.city };
  }
  if (payload.start_date && payload.end_date && payload.end_date < payload.start_date) {
    return { detail: "结束日期必须大于等于开始日期", focus: els.endDate };
  }
  const longTripError = updateDateSpanValidity();
  if (longTripError) {
    return longTripError;
  }
  if (Number.isFinite(payload.budget_min) && Number.isFinite(payload.budget_max) && payload.budget_max < payload.budget_min) {
    return { detail: "最高预算必须大于等于最低预算", focus: els.budgetMax };
  }
  return null;
}

// 转义HTML特殊字符，防止XSS跨站脚本攻击
function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function normalizeAddress(value) {
  return String(value || "").trim();
}

function timeSortKey(value) {
  const text = String(value || "").trim();
  const start = text.split("-", 1)[0].trim();
  const hourText = start.split(":", 1)[0].trim();
  const hour = Number.parseInt(hourText, 10);
  if (Number.isFinite(hour) && hour >= 0 && hour <= 23) {
    return [hour, text];
  }
  return [99, text];
}

function sortItemsByTime(items) {
  return [...items].sort((left, right) => {
    const [leftHour, leftText] = timeSortKey(left?.time_range);
    const [rightHour, rightText] = timeSortKey(right?.time_range);
    return leftHour - rightHour || leftText.localeCompare(rightText, "zh-Hans-CN");
  });
}

function buildLocationAddressMap(plan) {
  const addressMap = {};

  // 辅助函数：向映射表中添加地址
  const add = (name, address) => {
    const key = String(name || "").trim();
    const value = normalizeAddress(address);
    if (key && value && !addressMap[key]) {
      addressMap[key] = value;
    }
  };

  // 1. 从选中的景点中提取地址
  (plan.selected_attractions || []).forEach((item) => {
    add(item.name, item.location?.address);
    add(item.location?.name, item.location?.address);
  });

  // 2. 从推荐酒店中提取地址
  if (plan.recommended_hotel) {
    add(plan.recommended_hotel.name, plan.recommended_hotel.location?.address);
    add(plan.recommended_hotel.location?.name, plan.recommended_hotel.location?.address);
  }
  (plan.hotel_candidates || []).forEach((item) => {
    add(item.name, item.location?.address);
    add(item.location?.name, item.location?.address);
  });
  (plan.daily_stays || []).forEach((stay) => {
    [stay.start_hotel, stay.end_hotel].forEach((hotel) => {
      if (!hotel) return;
      add(hotel.name, hotel.location?.address);
      add(hotel.location?.name, hotel.location?.address);
    });
  });

  // 3. 从每日行程中提取地址
  (plan.daily_plans || []).forEach((day) => {
    (day.items || []).forEach((item) => {
      add(item.location_name, item.location_address);
      add(item.title, item.location_address);
      add(item.to_location, item.location_address);
    });
  });

  return addressMap;
}

function resolveItemAddress(item, addressMap) {
  return normalizeAddress(item.location_address)
    || addressMap[item.location_name]
    || addressMap[item.title]
    || addressMap[item.to_location]
    || "";
}

function transportModeLabel(value) {
  return {
    public_transit: "公共交通",
    self_drive: "自驾游",
    taxi: "打车",
    mixed: "混合出行",
  }[value] || value;
}

function transitPreferenceLabel(value) {
  return {
    recommended: "推荐",
    less_walking: "步行时间少",
    subway_priority: "地铁优先",
    bus_priority: "公交优先",
  }[value] || value;
}

function routeDataModeLabel(value) {
  return {
    live: "实时高德",
    live_outlier: "高德实时结果异常",
    live_walk: "实时高德步行",
    fallback: "本地估算",
  }[value] || value || "未知";
}

function routeFallbackReasonLabel(value) {
  if (!value) return "";
  if (value.includes("10021") || value.includes("CUQPS_HAS_EXCEEDED_THE_LIMIT")) {
    return "高德公交接口限流，已回退本地估算";
  }
  if (value.includes("origin_poi_geocode_failed")) {
    return "起点 POI 识别失败，已回退本地估算";
  }
  if (value.includes("destination_poi_geocode_failed")) {
    return "终点 POI 识别失败，已回退本地估算";
  }
  if (value.includes("amap_transit_empty")) {
    if (value.includes("short_distance_walk_api")) {
      return "高德未返回公交方案，因距离较短已改查实时步行路线";
    }
    return "高德未返回可用公交方案，当前只展示本地估算，不代表真实线路";
  }
  if (value.includes("route_distance_outlier") || value.includes("route_duration_outlier")) {
    return "路线距离或时间异常，可能存在地点匹配偏差，已保留你选择的出行方式";
  }
  if (value.includes("transit_request_exception")) {
    return "公交路径请求异常，已回退本地估算";
  }
  if (value.includes("driving_request_exception")) {
    return "驾车路径请求异常，已回退本地估算";
  }
  if (value.includes("live_transport_unavailable")) {
    return "实时交通结果不可用，已回退本地估算";
  }
  return value;
}

function segmentTypeLabel(value) {
  return {
    walk: "步行",
    subway: "地铁",
    railway: "铁路/城际",
    bus: "公交",
    transit: "公共交通",
    taxi: "打车",
    drive: "自驾",
    walk: "步行",
  }[value] || value;
}

function renderTransitLineMeta(segment) {
  const parts = [];
  if (segment.line_name) parts.push(escapeHtml(segment.line_name));
  if (segment.direction) parts.push(escapeHtml(segment.direction));
  return parts.length ? parts.join(" · ") : "";
}

function renderTransitStationMeta(segment) {
  const parts = [];
  if (segment.on_station || segment.off_station) {
    parts.push(`上车：${escapeHtml(segment.on_station || "-")} · 下车：${escapeHtml(segment.off_station || "-")}`);
  }
  if (segment.entrance || segment.exit) {
    parts.push(`入口：${escapeHtml(segment.entrance || "-")} · 出口：${escapeHtml(segment.exit || "-")}`);
  }
  if (segment.via_stops && segment.via_stops.length) {
    parts.push(`途经：${escapeHtml(segment.via_stops.join("、"))}`);
  }
  const alternatives = segment.details && Array.isArray(segment.details.alternatives)
    ? segment.details.alternatives
    : [];
  if (alternatives.length) {
    const lines = alternatives
      .map((item) => item.line_name || "")
      .filter(Boolean)
      .join("、");
    if (lines) {
      parts.push(`可选线路：${escapeHtml(lines)}`);
    }
  }
  return parts.map((item) => `<div class="route-segment-meta">${item}</div>`).join("");
}

function renderSearchPlan(plan) {
  const searchPlan = Array.isArray(plan.attraction_search_plan) ? plan.attraction_search_plan : [];
  const interpretation = plan.preference_interpretation || {};
  const positive = [
    ...(Array.isArray(interpretation.positive) ? interpretation.positive : []),
    ...(Array.isArray(interpretation.extra_positive) ? interpretation.extra_positive : []),
  ].filter(Boolean);
  const negative = Array.isArray(interpretation.negative) ? interpretation.negative.filter(Boolean) : [];

  if (!searchPlan.length && !positive.length && !negative.length) {
    return "";
  }

  return `
    <div class="agent-plan-card">
      <div class="mini-title">Agent 搜索计划</div>
      ${positive.length ? `<div class="mini-text">正向偏好：${escapeHtml(positive.join("、"))}</div>` : ""}
      ${negative.length ? `<div class="mini-text">负向约束：${escapeHtml(negative.join("、"))}</div>` : ""}
      ${searchPlan.length ? `
        <div class="search-query-list">
          ${searchPlan.map((item) => `
            <div class="search-query">
              <strong>${escapeHtml(item.query || item.theme || "未命名搜索")}</strong>
              <span>${escapeHtml(item.reason || "")}</span>
            </div>
          `).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

// 渲染AI Agent的运行诊断信息，用于调试和透明化
function diagnosticReasonLabel(value) {
  return {
    llm_output_json_parse_failed: "模型没有返回可解析 JSON",
    attraction_research_schema_validation_failed: "模型 JSON 不符合景点研究结构",
    selected_attractions_not_list: "selected_attractions 不是列表",
    agent_selected_no_attractions: "Agent 没有选出景点",
    mcp_candidate_pool_empty: "MCP 候选池为空",
    no_agent_attractions_matched_candidate_pool: "Agent 景点未匹配到 MCP 候选池",
    agent_grounding_failed: "Agent 输出未通过候选池验真",
    attraction_agent_postprocess_exception: "Agent 后处理异常",
    attraction_agent_unavailable_or_unverified: "Agent 不可用或结果未通过验真",
  }[value] || value || "无";
}

function renderAgentDiagnostics(plan) {
  const diagnostics = plan.agent_diagnostics || {};
  if (!diagnostics || !Object.keys(diagnostics).length) {
    return "";
  }
  const isFallback = Boolean(diagnostics.fallback_used);
  const statusText = isFallback
    ? "本轮已启用备用景点检索"
    : diagnostics.grounding_ok
      ? "景点 Agent 已通过候选池验真"
      : "景点 Agent 运行诊断";
  const rawPreview = String(diagnostics.raw_output_preview || "").trim();
  const removed = Array.isArray(diagnostics.removed_unverifiable) ? diagnostics.removed_unverifiable : [];
  const groundingRemoved = Array.isArray(diagnostics.grounding_removed) ? diagnostics.grounding_removed : [];
  return `
    <div class="agent-diagnostic-card ${isFallback ? "is-fallback" : "is-ok"}">
      <div class="agent-diagnostic-head">
        <div>
          <div class="mini-title">${escapeHtml(statusText)}</div>
          <div class="mini-text">原因：${escapeHtml(diagnosticReasonLabel(diagnostics.failure_reason))}</div>
        </div>
        <span class="section-tag">${escapeHtml(diagnostics.provider || "Agent")}</span>
      </div>
      <div class="diagnostic-grid">
        <div><span>JSON 解析</span><strong>${diagnostics.json_parse_ok ? "成功" : "失败"}</strong></div>
        <div><span>原始输出</span><strong>${Number(diagnostics.raw_output_length || 0)} 字符</strong></div>
        <div><span>模型原选</span><strong>${Number(diagnostics.raw_selected_count || 0)} 个</strong></div>
        <div><span>字段验真</span><strong>${Number(diagnostics.verified_selected_count || 0)} 个</strong></div>
        <div><span>MCP 候选池</span><strong>${Number(diagnostics.candidate_pool_size || 0)} 个</strong></div>
        <div><span>候选池匹配</span><strong>${Number(diagnostics.grounded_selected_count || 0)} 个</strong></div>
      </div>
      ${removed.length ? `
        <div class="diagnostic-note">
          字段缺失被移除：${escapeHtml(removed.map((item) => `${item.name || "未命名"}(${(item.missing || []).join("/")})`).join("、"))}
        </div>
      ` : ""}
      ${groundingRemoved.length ? `
        <div class="diagnostic-note">
          候选池未匹配：${escapeHtml(groundingRemoved.join("、"))}
        </div>
      ` : ""}
      ${rawPreview ? `
        <details class="diagnostic-raw">
          <summary>查看模型原始输出预览</summary>
          <div>${escapeHtml(rawPreview)}</div>
        </details>
      ` : ""}
    </div>
  `;
}

function renderRouteSegments(item) {
  if (!item.route_segments || !item.route_segments.length) {
    return "";
  }
  const alternatives = Array.isArray(item.route_alternatives) ? item.route_alternatives : [];
  return `
    <details class="route-details">
      <summary>查看详细路径</summary>
      ${item.route_data_mode ? `<div class="route-note">来源：${escapeHtml(routeDataModeLabel(item.route_data_mode))}</div>` : ""}
      ${item.route_strategy ? `<div class="route-note">策略：${escapeHtml(item.route_strategy)}</div>` : ""}
      ${item.route_fallback_reason ? `<div class="route-note">回退原因：${escapeHtml(routeFallbackReasonLabel(item.route_fallback_reason))}</div>` : ""}
      ${renderRouteSegmentList(item.route_segments)}
      ${renderRouteAlternatives(alternatives)}
    </details>
  `;
}

function renderRouteAlternatives(alternatives) {
  if (!alternatives.length) {
    return "";
  }
  return `
    <div class="route-alternatives">
      <div class="route-alternatives-title">备选方案</div>
      ${alternatives.map((alt, index) => `
        <details class="route-alt-card">
          <summary>
            <span>方案 ${index + 1}</span>
            <strong>${escapeHtml((alt.lines || []).join(" + ") || "公共交通方案")}</strong>
            <em>${Number(alt.duration_min || 0)}分钟 · ${Number(alt.distance_km || 0).toFixed(1)}公里 · ¥${Number(alt.cost || 0).toFixed(0)}</em>
          </summary>
          <div class="route-alt-meta">
            步行 ${Number(alt.walk_distance_m || 0).toFixed(0)} 米 · 换乘 ${Number(alt.transfers || 0).toFixed(0)} 次
          </div>
          ${renderRouteSegmentList(alt.route_segments || [])}
        </details>
      `).join("")}
    </div>
  `;
}

function renderRouteSegmentList(segments) {
  if (!segments || !segments.length) {
    return `<div class="route-note">该方案没有返回可展开的站点明细。</div>`;
  }
  return `
      <div class="route-segment-list">
        ${segments.map((segment, idx) => `
          <div class="route-segment">
            <div class="route-segment-head">${idx + 1}. ${escapeHtml(segmentTypeLabel(segment.segment_type))}</div>
            <div class="route-segment-text">${escapeHtml(segment.instruction || "无详细说明")}</div>
            <div class="route-segment-meta">
              ${segment.duration_min ? `${segment.duration_min} 分钟` : ""}
              ${segment.distance_m ? ` · ${segment.distance_m} 米` : ""}
              ${renderTransitLineMeta(segment) ? ` · ${renderTransitLineMeta(segment)}` : ""}
            </div>
            ${renderTransitStationMeta(segment)}
          </div>
        `).join("")}
      </div>
  `;
}

function renderPlanItem(item, addressMap = {}) {
  const address = resolveItemAddress(item, addressMap);

  if (item.item_type === "transport") {
    const chips = [
      item.transport_mode ? ["方式", item.transport_mode] : null,
      item.duration_min ? ["时间", `${Number(item.duration_min).toFixed(0)} 分钟`] : null,
      item.distance_km ? ["距离", `${Number(item.distance_km).toFixed(1)} 公里`] : null,
      ["费用", `¥${Number(item.estimated_cost || 0).toFixed(0)}`],
      item.route_data_mode ? ["来源", routeDataModeLabel(item.route_data_mode)] : null,
    ].filter(Boolean);

    return `
      <div class="item transport-item">
        <div class="item-time">${escapeHtml(item.time_range)}</div>
        <div class="item-body transport-body">
          <div class="transport-route">
            <span>${escapeHtml(item.from_location || "")}</span>
            <span class="route-arrow">→</span>
            <span>${escapeHtml(item.to_location || item.location_name || "")}</span>
          </div>
          ${address ? `<div class="transport-address">目的地地址：${escapeHtml(address)}</div>` : ""}
          <div class="transport-chips">
            ${chips.map(([label, value]) => `
              <span class="transport-chip">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value)}</strong>
              </span>
            `).join("")}
          </div>
          ${item.summary ? `<div class="transport-summary">${escapeHtml(item.summary)}</div>` : ""}
          ${item.route_fallback_reason ? `<div class="route-note">回退原因：${escapeHtml(routeFallbackReasonLabel(item.route_fallback_reason))}</div>` : ""}
          ${renderRouteSegments(item)}
        </div>
      </div>
    `;
  }

  return `
    <div class="item">
      <div class="item-time">${escapeHtml(item.time_range)}</div>
      <div class="item-body">
        <div class="item-title">${escapeHtml(item.title)}</div>
        <div class="item-meta">${escapeHtml(item.location_name)} · ¥${Number(item.estimated_cost).toFixed(0)}</div>
        <div class="item-address">地址：${escapeHtml(address || "暂无详细地址")}</div>
        <div class="item-summary">${escapeHtml(item.summary)}</div>
      </div>
    </div>
  `;
}

function sourceLabel(value) {
  const labels = {
    llm_generated: "LLM生成",
    program_fallback: "程序兜底",
    live_amap: "高德实时",
    live_qweather: "和风实时",
    live_poi_estimated_price: "高德POI+价格估算",
    local_sample: "本地样例",
    fallback: "本地兜底",
    agent_generated: "Agent整合",
  };
  return labels[value] || value || "未知";
}

function renderSources(plan) {
  els.sourceBar.innerHTML = `
    <div class="source-chip">规划来源：${escapeHtml(sourceLabel(plan.planning_source))}</div>
    <div class="source-chip">景点数据：${escapeHtml(sourceLabel(plan.attraction_data_source))}</div>
    <div class="source-chip">天气数据：${escapeHtml(sourceLabel(plan.weather_data_source))}</div>
    <div class="source-chip">酒店数据：${escapeHtml(sourceLabel(plan.hotel_data_source))}</div>
  `;
}

function extractErrorDetail(errorLike) {
  if (typeof errorLike === "string") {
    return errorLike;
  }
  const detail = errorLike?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const message = String(first?.msg || "输入参数校验失败").trim();
    const loc = Array.isArray(first?.loc) ? first.loc.join(" / ") : "";
    return loc ? `${message}（${loc}）` : message;
  }
  if (typeof errorLike?.message === "string" && errorLike.message.trim()) {
    return errorLike.message.trim();
  }
  return "生成失败";
}

function buildFriendlyError(errorLike) {
  const detail = extractErrorDetail(errorLike);
  const normalizedDetail = detail.toLowerCase().replace(/\s+/g, "");
  let title = "暂时无法生成这份行程";
  let hint = "请检查输入信息后重试。";

  if (detail.includes("请输入旅行城市")) {
    title = "还没有填写旅行城市";
    hint = "先输入一个清晰的中文或英文城市名，再继续生成行程。";
  } else if (isDateRangeError(normalizedDetail)) {
    title = "日期范围不正确";
    hint = "结束日期需要晚于或等于开始日期，请调整日期后再试。";
  } else if (isBudgetRangeError(normalizedDetail)) {
    title = "预算范围不正确";
    hint = "最高预算需要大于或等于最低预算，请调整预算区间。";
  } else if (detail.includes("value_error")) {
    title = "输入信息还不完整";
    hint = "请检查日期、预算、人数和城市是否填写正确。";
  } else if (detail.includes("城市名称编码异常")) {
    title = "城市名称没有识别成功";
    hint = "请重新输入清晰的中文或英文城市名，例如：广州、汕头、Beijing。";
  } else if (detail.includes("暂不支持城市")) {
    title = "当前城市暂不支持自动规划";
    hint = "可以换一个已知城市，或者换成地图服务能够识别的标准城市名再试。";
  } else if (detail.includes("暂无可用景点数据")) {
    title = "景点数据暂时没有准备好";
    hint = "这个城市可能缺少可用景点结果，建议换个写法，或稍后重试。";
  } else if (detail.includes("暂无可用酒店数据")) {
    title = "酒店数据暂时没有准备好";
    hint = "可以保留城市不变，稍后重试，或换一个更常见的城市写法。";
  } else if (detail.includes("暂无可用交通参考数据")) {
    title = "交通路线暂时没算出来";
    hint = "这通常是地图服务没有稳定返回路线结果。可以稍后重试，或改成中文城市名再试一次。";
  }

  return { title, detail, hint };
}

function isDateRangeError(normalizedDetail) {
  const patterns = [
    "end_datemustbegreaterthanorequaltostart_date",
    "结束日期必须大于或等于开始日期",
    "结束日期必须大于等于开始日期",
    "结束日期需要晚于或等于开始日期",
  ];
  return patterns.some((pattern) => normalizedDetail.includes(pattern.toLowerCase().replace(/\s+/g, "")));
}

function isBudgetRangeError(normalizedDetail) {
  const patterns = [
    "budget_maxmustbegreaterthanorequaltobudget_min",
    "最高预算必须大于或等于最低预算",
    "最高预算必须大于等于最低预算",
    "最高预算需要大于或等于最低预算",
    "大预算值必须大于或等于最小预算值",
  ];
  return patterns.some((pattern) => normalizedDetail.includes(pattern.toLowerCase().replace(/\s+/g, "")));
}

function resetResultView() {
  if (els.resultNav) {
    els.resultNav.hidden = true;
  }
  els.sourceBar.innerHTML = `
    <div class="source-chip">规划来源：未生成</div>
    <div class="source-chip">景点数据：未生成</div>
    <div class="source-chip">天气数据：未生成</div>
    <div class="source-chip">酒店数据：未生成</div>
  `;
  els.resultView.className = "result-view empty";
  els.resultView.innerHTML = `
    <div class="placeholder-title">还没有旅行计划</div>
    <p>提交表单后，这里会显示每日行程、预算拆分、酒店建议和交通路线说明。</p>
  `;
}

function bindErrorActions() {
  document.querySelector("#errorResetBtn")?.addEventListener("click", () => {
    resetResultView();
    setState("等待输入");
  });
  document.querySelector("#errorFocusBtn")?.addEventListener("click", () => {
    showPage("form");
    els.city.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function renderErrorCard(errorLike) {
  const friendly = buildFriendlyError(errorLike);
  if (els.resultNav) {
    els.resultNav.hidden = true;
  }
  els.sourceBar.innerHTML = `
    <div class="source-chip">规划来源：未生成</div>
    <div class="source-chip">状态：输入或数据需要调整</div>
  `;
  els.resultView.className = "result-view";
  els.resultView.innerHTML = `
    <section class="error-card">
      <div class="error-badge">本次未生成成功</div>
      <h2>${escapeHtml(friendly.title)}</h2>
      <p class="error-detail">${escapeHtml(friendly.detail)}</p>
      <div class="error-hint">
        <div class="error-hint-title">建议</div>
        <div>${escapeHtml(friendly.hint)}</div>
      </div>
      <div class="error-actions">
        <button type="button" class="secondary-button" id="errorResetBtn">清空结果</button>
        <button type="button" class="ghost-button" id="errorFocusBtn">返回编辑</button>
      </div>
    </section>
  `;
  bindErrorActions();
}

function collectRouteStops(plan) {
  const stops = [];
  (plan.daily_plans || []).forEach((day, dayIndex) => {
    sortItemsByTime(day.items || []).forEach((item) => {
      if (item.item_type === "transport") return;
      const name = item.location_name || item.title;
      if (!name) return;
      stops.push({
        day: dayIndex + 1,
        time: item.time_range || "",
        name,
        type: item.item_type || "stop",
      });
    });
  });
  return stops;
}

function renderRouteMap(plan) {
  const stops = collectRouteStops(plan);
  const dayCount = Array.isArray(plan.daily_plans) ? plan.daily_plans.length : 0;
  const transportCost = Number(plan.budget?.transport || 0);
  const stayHotels = new Set((plan.daily_stays || [])
    .map((stay) => stay.end_hotel?.name || stay.start_hotel?.name)
    .filter(Boolean));
  const hotelName = stayHotels.size
    ? `${stayHotels.size} 个住宿基点`
    : plan.recommended_hotel?.name || "暂无酒店推荐";
  const visibleStops = stops.slice(0, 12);
  const hiddenCount = Math.max(0, stops.length - visibleStops.length);

  return `
    <section class="report-section" id="route-map">
      <div class="section-title-row">
        <h2>路线总览</h2>
        <span class="section-tag">按每日停靠点生成</span>
      </div>
      <div class="route-map-panel">
        <div class="route-canvas">
          <div class="route-line"></div>
          <div class="route-stop-list">
            ${visibleStops.map((stop) => `
              <div class="route-stop">
                <div class="route-stop-day">第 ${stop.day} 天 · ${escapeHtml(stop.time)}</div>
                <div class="route-stop-name">${escapeHtml(stop.name)}</div>
              </div>
            `).join("") || `
              <div class="route-stop">
                <div class="route-stop-day">等待行程点</div>
                <div class="route-stop-name">当前没有可展示的路线停靠点</div>
              </div>
            `}
          </div>
        </div>
        <div class="route-map-side">
          <div class="map-stat"><strong>${dayCount}</strong><span>旅行天数</span></div>
          <div class="map-stat"><strong>${stops.length}</strong><span>停靠点数量${hiddenCount ? `，已折叠 ${hiddenCount} 个` : ""}</span></div>
          <div class="map-stat"><strong>¥${transportCost.toFixed(0)}</strong><span>交通预算预估</span></div>
          <div class="map-stat"><strong>${escapeHtml(hotelName)}</strong><span>住宿基点</span></div>
        </div>
      </div>
    </section>
  `;
}

function renderHotelCard(hotel, title = "") {
  if (!hotel) {
    return "<div class='mini-text'>暂无酒店推荐</div>";
  }
  return `
    <div class="hotel-card">
      ${title ? `<div class="hotel-card-kicker">${escapeHtml(title)}</div>` : ""}
      <div class="mini-title">${escapeHtml(hotel.name)}</div>
      <div class="mini-text">${escapeHtml(hotel.summary)}</div>
      <div class="mini-address">地址：${escapeHtml(normalizeAddress(hotel.location?.address) || "暂无详细地址")}</div>
      <div class="mini-text">¥${Number(hotel.nightly_price).toFixed(0)} / 晚 · ${escapeHtml(hotel.nearby_area)}</div>
      <div class="mini-text">价格来源：${escapeHtml(hotel.price_source || "estimated")}</div>
      ${hotel.booking_url ? `<a class="hotel-link" href="${encodeURI(hotel.booking_url)}" target="_blank" rel="noreferrer">查看 OTA 候选</a>` : ""}
    </div>
  `;
}

function renderDailyHotelCard(stay, dayIndex, hotelItem = null) {
  const startHotel = stay?.start_hotel || null;
  const endHotel = stay?.end_hotel || startHotel;
  if (!startHotel && !endHotel) {
    if (!hotelItem) {
      return "";
    }
    const itemName = hotelItem.location_name || hotelItem.title || "当日住宿安排";
    return `
      <section class="day-hotel-card">
        <div class="day-hotel-main">
          <div class="day-hotel-kicker">第 ${dayIndex + 1} 天住宿</div>
          <div class="day-hotel-name">${escapeHtml(itemName)}</div>
          <div class="day-hotel-meta">
            ${hotelItem.time_range ? `<span>${escapeHtml(hotelItem.time_range)}</span>` : ""}
            <span>住宿节点</span>
          </div>
        </div>
        <div class="day-hotel-detail">
          <div>${escapeHtml(hotelItem.summary || "当日酒店安排")}</div>
          <div class="mini-address">地址：${escapeHtml(normalizeAddress(hotelItem.location_address) || "暂无详细地址")}</div>
        </div>
      </section>
    `;
  }
  const hotel = endHotel || startHotel;
  const isChanged = Boolean(stay?.hotel_changed && startHotel && endHotel && startHotel.name !== endHotel.name);
  const price = stay?.charged_night && hotel
    ? `¥${Number(hotel.nightly_price || 0).toFixed(0)} / 晚`
    : "当日不新增住宿费用";
  const routeText = isChanged
    ? `${startHotel.name} → ${endHotel.name}`
    : hotel.name;

  return `
    <section class="day-hotel-card">
      <div class="day-hotel-main">
        <div class="day-hotel-kicker">第 ${dayIndex + 1} 天住宿</div>
        <div class="day-hotel-name">${escapeHtml(routeText)}</div>
        <div class="day-hotel-meta">
          <span>${escapeHtml(price)}</span>
          ${hotelItem?.time_range ? `<span>${escapeHtml(hotelItem.time_range)}</span>` : ""}
          <span>${escapeHtml(hotel.nearby_area || stay?.night_area || "夜间区域灵活")}</span>
          ${isChanged ? "<span>换宿</span>" : "<span>住宿基点</span>"}
        </div>
      </div>
      <div class="day-hotel-detail">
        <div>${escapeHtml(hotel.summary || stay?.reason || "当日住宿安排")}</div>
        <div class="mini-address">地址：${escapeHtml(normalizeAddress(hotel.location?.address) || "暂无详细地址")}</div>
        ${hotelItem?.summary ? `<div class="mini-text">${escapeHtml(hotelItem.summary)}</div>` : ""}
        ${stay?.reason ? `<div class="mini-text">${escapeHtml(stay.reason)}</div>` : ""}
      </div>
    </section>
  `;
}

function getDailyStayForDay(plan, dayIndex) {
  const stays = Array.isArray(plan.daily_stays) ? plan.daily_stays : [];
  const expectedDay = dayIndex + 1;
  return stays.find((stay) => Number(stay?.day_index) === expectedDay) || stays[dayIndex] || null;
}

function getDayHotelItem(day) {
  const items = Array.isArray(day?.items) ? day.items : [];
  return items.find((item) => item?.item_type === "hotel") || null;
}

function getVisibleDayItems(day) {
  const items = Array.isArray(day?.items) ? day.items : [];
  return items.filter((item) => item?.item_type !== "hotel");
}

function renderDailyStays(plan) {
  const stays = Array.isArray(plan.daily_stays) ? plan.daily_stays : [];
  if (!stays.length) {
    return "";
  }
  return `
    <div class="daily-stay-list">
      ${stays.map((stay) => {
        const startName = stay.start_hotel?.name || "灵活出发";
        const endName = stay.end_hotel?.name || "灵活住宿";
        const price = stay.charged_night && stay.end_hotel
          ? `¥${Number(stay.end_hotel.nightly_price || 0).toFixed(0)}`
          : "不计住宿";
        return `
          <div class="daily-stay-card">
            <div class="daily-stay-head">
              <strong>第 ${Number(stay.day_index || 0)} 天</strong>
              <span>${escapeHtml(price)}</span>
            </div>
            <div class="daily-stay-route">
              <span>${escapeHtml(startName)}</span>
              <span>→</span>
              <span>${escapeHtml(endName)}</span>
            </div>
            <div class="mini-text">夜间区域：${escapeHtml(stay.night_area || "灵活安排")}</div>
            <div class="mini-text">${escapeHtml(stay.reason || "")}</div>
            ${stay.hotel_changed ? `<div class="stay-badge">含换宿与行李寄存</div>` : ""}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderMetrics(plan, payload) {
  const dayCount = Array.isArray(plan.daily_plans) ? plan.daily_plans.length : 0;
  const attractionCount = Array.isArray(plan.selected_attractions) ? plan.selected_attractions.length : 0;
  const budgetTotal = Number(plan.budget?.total || 0);
  const chargedStays = (plan.daily_stays || []).filter((stay) => stay.charged_night && stay.end_hotel);
  const hotelPrice = chargedStays.length
    ? chargedStays.reduce((sum, stay) => sum + Number(stay.end_hotel?.nightly_price || 0), 0) / chargedStays.length
    : Number(plan.recommended_hotel?.nightly_price || 0);
  return `
    <div class="metric-grid">
      <div class="metric">
        <div class="metric-label">旅行天数</div>
        <div class="metric-value">${dayCount} 天</div>
      </div>
      <div class="metric">
        <div class="metric-label">入选景点</div>
        <div class="metric-value">${attractionCount} 个</div>
      </div>
      <div class="metric">
        <div class="metric-label">出行方式</div>
        <div class="metric-value">${escapeHtml(transportModeLabel(payload.transport_mode))}</div>
      </div>
      <div class="metric">
        <div class="metric-label">住宿均价</div>
        <div class="metric-value">¥${hotelPrice.toFixed(0)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">总预算</div>
        <div class="metric-value">¥${budgetTotal.toFixed(0)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">旅行节奏</div>
        <div class="metric-value">${escapeHtml(els.pace.options[els.pace.selectedIndex]?.text || payload.pace)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">同行人数</div>
        <div class="metric-value">${Number(payload.travelers || 0)} 人</div>
      </div>
      <div class="metric">
        <div class="metric-label">住宿偏好</div>
        <div class="metric-value">${escapeHtml(els.hotelStyle.options[els.hotelStyle.selectedIndex]?.text || payload.hotel_style)}</div>
      </div>
    </div>
  `;
}

function bindResultNav() {
  if (!els.resultNav) return;
  els.resultNav.hidden = false;
  const buttons = Array.from(els.resultNav.querySelectorAll(".nav-link"));
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = document.querySelector(`#${button.dataset.target}`);
      if (!target) return;
      buttons.forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  buttons[0]?.classList.add("active");
}

function renderPlan(plan) {
  renderSources(plan);
  const payload = buildPayload();
  const locationAddressMap = buildLocationAddressMap(plan);
  if (els.resultNav) {
    els.resultNav.hidden = false;
  }
  const daysHtml = plan.daily_plans.map((day, index) => {
    const hotelItem = getDayHotelItem(day);
    const visibleItems = getVisibleDayItems(day);
    return `
      <article class="day-card" id="day-${index + 1}">
        <div class="day-head">
          <h3>第 ${index + 1} 天 · ${escapeHtml(day.date)}</h3>
          <div class="mini-badge weather-pill">
            <span class="weather-dot"></span>
            ${escapeHtml(day.weather.condition)} ${day.weather.low_c}-${day.weather.high_c}C
          </div>
        </div>
        <div class="day-summary">
          <p class="route-summary">${escapeHtml(day.route_summary)}</p>
          <div class="day-meta-line">当日交通合计：¥${Number(day.total_transport_cost).toFixed(0)} / ${Number(day.total_transport_time_min).toFixed(0)} 分钟</div>
        </div>
        ${renderDailyHotelCard(getDailyStayForDay(plan, index), index, hotelItem)}
        <div class="item-list">
          ${visibleItems.map((item) => renderPlanItem(item, locationAddressMap)).join("")}
        </div>
      </article>
    `;
  }).join("");

  const attractionsHtml = plan.selected_attractions.map((item) => `
    <div class="mini-card">
      <div class="mini-title">${escapeHtml(item.name)}</div>
      <div class="mini-address">地址：${escapeHtml(normalizeAddress(item.location?.address) || "暂无详细地址")}</div>
      <div class="mini-text">${escapeHtml(item.summary)}</div>
    </div>
  `).join("");

  const hotelHtml = `
    ${renderHotelCard(plan.recommended_hotel, "首推住宿")}
    ${renderDailyStays(plan)}
  `;

  const transitPreferenceText = payload.transport_mode === "public_transit"
    ? `，偏好：${transitPreferenceLabel(payload.transit_preference)}`
    : "";

  els.resultView.className = "result-view";
  els.resultView.innerHTML = `
    <section class="report-section hero" id="overview">
      <div>
        <div class="eyebrow">旅行主题</div>
        <h2>${escapeHtml(plan.city)} · ${escapeHtml(plan.travel_theme)}</h2>
        <p>${escapeHtml(plan.overview)}</p>
        <p class="mini-text">当前方案按 ${escapeHtml(transportModeLabel(payload.transport_mode))}${escapeHtml(transitPreferenceText)} 生成交通建议。</p>
        ${renderMetrics(plan, payload)}
      </div>
      <div class="budget-box">
        <div class="budget-label">总预算预估</div>
        <div class="budget-total">¥${Number(plan.budget.total).toFixed(0)}</div>
      </div>
    </section>

    ${renderRouteMap(plan)}

    <section class="report-section columns">
      <div class="column" id="hotel">
        <div class="section-title-row">
          <h2>住宿建议</h2>
          <span class="section-tag">按每日路线基点选择</span>
        </div>
        ${hotelHtml}
      </div>
      <div class="column" id="budget">
        <div class="section-title-row">
          <h2>预算拆分</h2>
          <span class="section-tag">估算</span>
        </div>
        <div class="budget-list">
          <div><span>酒店</span><strong>¥${Number(plan.budget.hotel).toFixed(0)}</strong></div>
          <div><span>景点</span><strong>¥${Number(plan.budget.attractions).toFixed(0)}</strong></div>
          <div><span>餐饮</span><strong>¥${Number(plan.budget.food).toFixed(0)}</strong></div>
          <div><span>交通</span><strong>¥${Number(plan.budget.transport).toFixed(0)}</strong></div>
          <div><span>弹性预算</span><strong>¥${Number(plan.budget.contingency).toFixed(0)}</strong></div>
        </div>
      </div>
    </section>

    <section class="report-section columns">
      <div class="column" id="attractions">
        <div class="section-title-row">
          <h2>入选景点</h2>
          <span class="section-tag">${plan.selected_attractions.length} 个候选</span>
        </div>
        <div class="attraction-grid">${attractionsHtml || "<div class='mini-text'>暂无入选景点</div>"}</div>
      </div>
      <div class="column" id="agent-search">
        <div class="section-title-row">
          <h2>Agent 搜索依据</h2>
          <span class="section-tag">偏好与忌讳</span>
        </div>
        ${renderAgentDiagnostics(plan)}
        ${renderSearchPlan(plan) || "<div class='mini-card'><div class='mini-text'>暂无搜索计划记录</div></div>"}
      </div>
    </section>

    <section class="report-section days" id="days">
      <div class="section-title-row">
        <h2>每日行程</h2>
        <span class="section-tag">可展开交通细节与备选路线</span>
      </div>
      ${daysHtml}
    </section>

    <section class="report-section columns" id="risks">
      <div class="column">
        <div class="section-title-row">
          <h2>风险提醒</h2>
        </div>
        <ul class="plain-list">${plan.risk_alerts.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>暂无明显风险</li>"}</ul>
      </div>
      <div class="column">
        <div class="section-title-row">
          <h2>携带建议</h2>
        </div>
        <ul class="plain-list">${plan.packing_tips.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    </section>
  `;
  bindResultNav();
}

async function submitPlan(event) {
  event.preventDefault();
  const payload = buildPayload();
  const validationError = validatePayload(payload);
  if (validationError) {
    renderErrorCard(validationError);
    validationError.focus?.focus();
    validationError.focus?.reportValidity?.();
    setState("待调整");
    return;
  }

  showPage("result");
  setState("规划中");
  startProgress();
  els.submitBtn.disabled = true;

  try {
    const task = await createPlanTask(payload);
    const data = await waitForPlanStream(task.task_id);
    if (!data) {
      throw { detail: "后端完成了任务，但没有返回旅行计划内容。" };
    }
    renderPlan(data);
    setState("已完成");
  } catch (error) {
    failProgress();
    renderErrorCard(error);
    setState("失败");
  } finally {
    els.submitBtn.disabled = false;
    updateDateSpanValidity();
  }
}


function bindGlobalEvents() {
  els.transportMode.addEventListener("change", updateTransitPreferenceVisibility);
  [els.startDate, els.endDate].forEach((input) => {
    input.addEventListener("input", () => updateDateSpanValidity({ report: true }));
    input.addEventListener("change", () => updateDateSpanValidity({ report: true }));
  });
  els.form.addEventListener("submit", submitPlan);
  els.backToFormBtn.addEventListener("click", () => {
    stopProgress();
    els.progressPanel.hidden = true;
    showPage("form");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

renderPreferenceChips();
updateTransitPreferenceVisibility();
bindGlobalEvents();
loadHealth().catch(() => {
  els.healthText.textContent = "服务状态检查失败";
});
